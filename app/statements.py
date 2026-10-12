"""Monthly airline statements. Generated once per airline per month, then stored as an immutable snapshot.

Basis: money figures are by ledger-entry date (when cash was recorded), so
opening balance + collected - service fees - payouts = closing balance, always.
Bag counts are by weigh date. Month boundaries use config.TIMEZONE.
"""
import csv
import hashlib
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, config
from app.models import (Airline, Collector, LedgerEntry, LedgerType, Staff, Statement, Status,
                        Transaction)


class StatementError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; they are always UTC here."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def local_str(dt: datetime) -> str:
    return _utc(dt).astimezone(_tz()).isoformat(timespec="seconds")


def day_bounds(day) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=_tz())
    nxt = datetime.fromordinal(day.toordinal() + 1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=_tz())
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def period_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=_tz())
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(ny, nm, 1, tzinfo=_tz())
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def csv_safe(value) -> str:
    """Stop spreadsheet formula injection from free-text fields (reasons, references)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def build_data(db: Session, airline: Airline, year: int, month: int, now: datetime) -> dict:
    start, end = period_bounds(year, month)

    # ---- bag counts (by weigh date)
    weighed = db.scalars(select(Transaction).where(
        Transaction.airline_id == airline.id, Transaction.created_at >= start,
        Transaction.created_at < end)).all()
    rejected = sum(1 for t in weighed if t.status == Status.REJECTED)
    over = sum(1 for t in weighed if t.fee_cents > 0)
    summary = {"bags_weighed": len(weighed), "bags_rejected": rejected,
               "bags_over_allowance": over,
               "bags_within_allowance": len(weighed) - rejected - over}

    # ---- waivers (by waiver date)
    wrows = db.execute(select(Transaction, Staff.staff_code)
                       .join(Staff, Transaction.waived_by_staff_id == Staff.id)
                       .where(Transaction.airline_id == airline.id, Transaction.waived_at >= start,
                              Transaction.waived_at < end)
                       .order_by(Transaction.waived_at, Transaction.id)).all()
    waivers = [{"date": local_str(t.waived_at), "transaction_id": t.id, "flight_number": t.flight_number,
                "weight_kg": t.weight_kg, "waived_cents": t.waived_cents, "staff_code": code,
                "reason": t.waiver_reason} for t, code in wrows]
    summary["bags_waived"] = len(waivers)
    summary["fees_waived_cents"] = sum(w["waived_cents"] for w in waivers)

    # ---- settlement (by ledger date)
    entries = db.execute(
        select(LedgerEntry, Transaction)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id, isouter=True)
        .where(LedgerEntry.airline_id == airline.id, LedgerEntry.created_at >= start,
               LedgerEntry.created_at < end)
        .order_by(LedgerEntry.created_at, LedgerEntry.id)).all()
    opening = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
        LedgerEntry.airline_id == airline.id, LedgerEntry.created_at < start)) or 0
    gross = sum(e.amount_cents for e, _ in entries if e.entry_type == LedgerType.PAYMENT)
    fees = -sum(e.amount_cents for e, _ in entries if e.entry_type == LedgerType.SERVICE_FEE)
    payouts = -sum(e.amount_cents for e, _ in entries if e.entry_type == LedgerType.PAYOUT)
    settlement = {"applicable": airline.collector == Collector.operator,
                  "opening_balance_cents": opening, "gross_collected_cents": gross,
                  "service_fees_cents": fees, "payouts_cents": payouts,
                  "closing_balance_cents": opening + gross - fees - payouts}

    by_method: dict[str, dict] = {}
    for e, t in entries:
        if e.entry_type == LedgerType.PAYMENT and t is not None:
            m = by_method.setdefault(t.payment_method or "unknown", {"count": 0, "cents": 0})
            m["count"] += 1
            m["cents"] += e.amount_cents

    # ---- event lines: the CSV. Money rows sum to (closing - opening).
    events = []
    for e, t in entries:
        events.append({"ts": local_str(e.created_at), "event_type": e.entry_type.value,
                       "transaction_id": e.transaction_id, "flight_number": t.flight_number if t else None,
                       "weight_kg": t.weight_kg if t else None, "amount_cents": e.amount_cents,
                       "waived_cents": 0, "payment_method": t.payment_method if t else None,
                       "staff_code": None, "reason": None, "reference": e.reference})
    for w in waivers:
        events.append({"ts": w["date"], "event_type": "WAIVER", "transaction_id": w["transaction_id"],
                       "flight_number": w["flight_number"], "weight_kg": w["weight_kg"],
                       "amount_cents": 0, "waived_cents": w["waived_cents"], "payment_method": None,
                       "staff_code": w["staff_code"], "reason": w["reason"], "reference": None})
    events.sort(key=lambda r: (r["ts"], r["transaction_id"] or 0, r["event_type"]))

    chain = audit.verify(db, airline.id)
    return {
        "statement_no": f"{airline.iata_code}-{year}-{month:02d}",
        "airline": {"iata_code": airline.iata_code, "name": airline.name, "currency": airline.currency,
                    "collector": airline.collector.value, "service_fee_bps": airline.service_fee_bps},
        "period": {"year": year, "month": month, "timezone": config.TIMEZONE,
                   "start_utc": start.isoformat(), "end_utc": end.isoformat()},
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": summary, "payments_by_method": by_method, "settlement": settlement,
        "waivers": waivers, "events": events,
        "integrity": {"audit_chain_valid": chain["valid"], "audit_events": chain["events_checked"],
                      "audit_head_hash": chain["head_hash"]},
    }


def generate(db: Session, airline: Airline, year: int, month: int, now: datetime) -> Statement:
    if not (1 <= month <= 12 and 2020 <= year <= 2100):
        raise StatementError("Invalid year or month", 422)
    _, end = period_bounds(year, month)
    if now < end:
        raise StatementError("That month hasn't ended yet; a statement can only cover a closed month", 400)
    if db.scalar(select(Statement).where(Statement.airline_id == airline.id, Statement.year == year,
                                          Statement.month == month)):
        raise StatementError("Statement already generated; statements are final", 409)
    data = build_data(db, airline, year, month, now)
    if not data["integrity"]["audit_chain_valid"]:
        raise StatementError("Audit chain failed verification; investigate before issuing a statement", 409)
    content_hash = hashlib.sha256(audit.canonical(data).encode()).hexdigest()
    stmt = Statement(airline_id=airline.id, year=year, month=month, statement_no=data["statement_no"],
                     data=audit.canonical(data), content_hash=content_hash, generated_at=now)
    db.add(stmt)
    # Anchor the statement in the airline's own audit chain.
    audit.append(db, airline.id, "STATEMENT_GENERATED", "admin",
                 payload={"statement_no": data["statement_no"], "content_hash": content_hash})
    db.commit()
    db.refresh(stmt)
    return stmt


def to_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["event_time_local", "event_type", "transaction_id", "flight_number", "weight_kg",
                "amount_cents", "waived_cents", "payment_method", "staff_code", "reason", "reference"])
    for r in data["events"]:
        w.writerow([r["ts"], r["event_type"], r["transaction_id"] or "", csv_safe(r["flight_number"]),
                    "" if r["weight_kg"] is None else r["weight_kg"], r["amount_cents"], r["waived_cents"],
                    r["payment_method"] or "", csv_safe(r["staff_code"]), csv_safe(r["reason"]),
                    csv_safe(r["reference"])])
    return buf.getvalue()
