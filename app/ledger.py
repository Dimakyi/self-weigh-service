"""Settlement ledger. Append-only entries; the balance is always computed from them, never stored."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models import Airline, Collector, LedgerEntry, LedgerType, Transaction


def split_fee(gross_cents: int, service_fee_bps: int) -> tuple[int, int]:
    """Return (operator_cut, airline_share). Cut is rounded down so the two always add up exactly."""
    cut = gross_cents * service_fee_bps // 10_000
    return cut, gross_cents - cut


def record_payment(db: Session, airline: Airline, tx: Transaction) -> None:
    """Add ledger entries for a paid transaction. Caller commits, so payment and ledger are atomic.

    airline_direct: the airline is paid at source, so nothing is owed through this ledger.
    """
    if airline.collector != Collector.operator or tx.fee_cents <= 0:
        return
    cut, _ = split_fee(tx.fee_cents, airline.service_fee_bps)
    db.add(LedgerEntry(airline_id=airline.id, transaction_id=tx.id,
                       entry_type=LedgerType.PAYMENT, amount_cents=tx.fee_cents))
    if cut:
        db.add(LedgerEntry(airline_id=airline.id, transaction_id=tx.id,
                           entry_type=LedgerType.SERVICE_FEE, amount_cents=-cut))


def _sum(db: Session, airline_id: int, entry_type: LedgerType) -> int:
    return db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
        LedgerEntry.airline_id == airline_id, LedgerEntry.entry_type == entry_type)) or 0


def balance(db: Session, airline: Airline) -> dict:
    gross = _sum(db, airline.id, LedgerType.PAYMENT)
    fees = -_sum(db, airline.id, LedgerType.SERVICE_FEE)
    paid_out = -_sum(db, airline.id, LedgerType.PAYOUT)
    return {"airline_id": airline.id, "iata_code": airline.iata_code, "currency": airline.currency,
            "collector": airline.collector, "gross_collected_cents": gross,
            "service_fees_cents": fees, "paid_out_cents": paid_out,
            "balance_due_cents": gross - fees - paid_out}


def record_payout(db: Session, airline: Airline, amount_cents: int, reference: str | None) -> LedgerEntry:
    due = balance(db, airline)["balance_due_cents"]
    if amount_cents > due:
        raise ValueError(f"Payout exceeds balance due ({due} cents)")
    entry = LedgerEntry(airline_id=airline.id, entry_type=LedgerType.PAYOUT,
                        amount_cents=-amount_cents, reference=reference)
    db.add(entry)
    audit.append(db, airline.id, "PAYOUT_RECORDED", "admin",
                 payload={"amount_cents": amount_cents, "reference": reference})
    db.commit()
    db.refresh(entry)
    return entry
