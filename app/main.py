"""Self Weigh Service API: weigh -> (pay) -> proceed to bag drop, separated per airline."""

import json
from datetime import date, datetime, timezone
from enum import Enum

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, config, ledger, pricing, statement_pdf, statements
from app.db import Base, engine, get_db
from app.models import (Airline, AuditEvent, CashReconciliation, Collector, LedgerEntry, LedgerType,
                        Staff, Statement, Status, Transaction)
from app.scale import Scale, SimulatedScale
from app.security import (current_airline, current_staff, hash_key, new_airline_key,
                          new_staff_key, require_admin, require_kiosk)
from app.outbox import enqueue_event

Base.metadata.create_all(engine)
app = FastAPI(title="Self Weigh Service", description="Weigh. Pay. Drop.")
_scale: Scale = SimulatedScale()


def get_scale() -> Scale:
    return _scale


def get_now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentMethod(str, Enum):
    card = "card"
    mobile = "mobile"
    cash = "cash"


# ---------- schemas ----------
class AirlineCreate(BaseModel):
    iata_code: str = Field(min_length=2, max_length=3, pattern="^[A-Za-z0-9]+$")
    name: str = Field(min_length=1, max_length=100)
    allowance_kg: float = Field(config.DEFAULT_ALLOWANCE_KG, gt=0)
    max_bag_kg: float = Field(config.DEFAULT_MAX_BAG_KG, gt=0)
    excess_rate_cents_per_kg: int = Field(config.DEFAULT_EXCESS_RATE_CENTS_PER_KG, ge=0)
    currency: str = Field("ZAR", min_length=3, max_length=3)
    collector: Collector = Collector.operator
    service_fee_bps: int = Field(500, ge=0, le=10_000, description="Operator cut in basis points (500 = 5%)")


class AirlineOut(BaseModel):
    id: int
    iata_code: str
    name: str
    allowance_kg: float
    max_bag_kg: float
    excess_rate_cents_per_kg: int
    currency: str
    collector: Collector
    service_fee_bps: int
    active: bool
    model_config = {"from_attributes": True}


class AirlineCreated(AirlineOut):
    api_key: str = Field(description="Shown once. Store it safely; only its hash is kept.")


class WeighRequest(BaseModel):
    airline_code: str
    flight_number: str | None = Field(None, max_length=10)
    weight_kg: float | None = Field(None, description="Omit to read from the (simulated) scale")


class PayRequest(BaseModel):
    method: PaymentMethod
    amount_cents: int

class PassengerVerificationRequest(BaseModel):
    passenger_name: str = Field(min_length=1, max_length=100)
    boarding_pass_name: str = Field(min_length=1, max_length=100)
    flight_number: str = Field(min_length=1, max_length=10)
    boarding_pass_flight: str = Field(min_length=1, max_length=10)

    @field_validator(
        "passenger_name",
        "boarding_pass_name",
        "flight_number",
        "boarding_pass_flight",
    )
    @classmethod
    def reject_blank_details(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank")
        return value

class BalanceOut(BaseModel):
    airline_id: int
    iata_code: str
    currency: str
    collector: Collector
    gross_collected_cents: int
    service_fees_cents: int
    paid_out_cents: int
    balance_due_cents: int


class LedgerEntryOut(BaseModel):
    id: int
    transaction_id: int | None
    entry_type: LedgerType
    amount_cents: int
    reference: str | None
    model_config = {"from_attributes": True}


class PayoutRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    reference: str | None = Field(None, max_length=100, description="e.g. bank transfer reference")


class StaffCreate(BaseModel):
    staff_code: str = Field(min_length=2, max_length=20, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    waiver_limit_cents: int = Field(50_000, ge=0, description="Largest single fee this person may waive")


class StaffOut(BaseModel):
    id: int
    staff_code: str
    name: str
    waiver_limit_cents: int
    active: bool
    model_config = {"from_attributes": True}


class StaffCreated(StaffOut):
    api_key: str = Field(description="Shown once. Store it safely; only its hash is kept.")


class WaiveRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=300, description="Required, and shown to the airline")


class AuditEventOut(BaseModel):
    seq: int
    ts: str
    event_type: str
    actor: str
    transaction_id: int | None
    payload: str
    prev_hash: str
    hash: str
    model_config = {"from_attributes": True}


class AuditVerifyOut(BaseModel):
    valid: bool
    events_checked: int
    first_bad_seq: int | None
    head_hash: str


class StatementListItem(BaseModel):
    statement_no: str
    year: int
    month: int
    generated_at: datetime
    content_hash: str
    model_config = {"from_attributes": True}


class ReconcileRequest(BaseModel):
    business_date: date
    counted_cents: int = Field(ge=0, description="Cash actually counted from the kiosk cash boxes")
    counted_by: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(None, max_length=300)


class ReconcileOut(BaseModel):
    business_date: date
    expected_cents: int
    counted_cents: int
    variance_cents: int
    balanced: bool
    counted_by: str
    notes: str | None


class TransactionOut(BaseModel):
    id: int
    airline_id: int
    flight_number: str | None
    weight_kg: float
    excess_kg: int
    fee_cents: int
    waived_cents: int
    waiver_reason: str | None
    status: Status
    payment_method: str | None
    message: str
    model_config = {"from_attributes": True}

# ---------- kiosk: simulated passenger verification ----------
@app.post(
    "/passenger/verify",
    dependencies=[Depends(require_kiosk)],
)
def verify_passenger(body: PassengerVerificationRequest):
    matched = (
        body.passenger_name.casefold() == body.boarding_pass_name.casefold()
        and body.flight_number.upper() == body.boarding_pass_flight.upper()
    )

    return {
        "matched": matched,
        "mode": "SIMULATION",
        "message": (
            "Passenger name and flight details match in simulation. "
            "This is not official identity verification."
            if matched
            else
            "Passenger name or flight details do not match in simulation. "
            "This is not official identity verification."
        ),
    }

# ---------- admin: manage airlines ----------
@app.post("/airlines", response_model=AirlineCreated, status_code=201, dependencies=[Depends(require_admin)])
def create_airline(body: AirlineCreate, db: Session = Depends(get_db)):
    code = body.iata_code.upper()
    if db.scalar(select(Airline).where(Airline.iata_code == code)):
        raise HTTPException(409, f"Airline {code} already exists")
    key = new_airline_key()
    airline = Airline(**body.model_dump(exclude={"iata_code"}), iata_code=code, api_key_hash=hash_key(key))
    db.add(airline)
    db.commit()
    db.refresh(airline)
    return AirlineCreated(**AirlineOut.model_validate(airline).model_dump(), api_key=key)


@app.get("/airlines", response_model=list[AirlineOut], dependencies=[Depends(require_admin)])
def list_airlines(db: Session = Depends(get_db)):
    return db.scalars(select(Airline).order_by(Airline.iata_code)).all()


# ---------- kiosk: weigh and pay ----------
def _airline_by_code(db: Session, code: str) -> Airline:
    airline = db.scalar(select(Airline).where(Airline.iata_code == code.upper()))
    if airline is None or not airline.active:
        raise HTTPException(404, "Unknown or inactive airline")
    return airline


@app.post("/weigh", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_kiosk)])
def weigh(req: WeighRequest, db: Session = Depends(get_db), scale: Scale = Depends(get_scale)):
    airline = _airline_by_code(db, req.airline_code)
    weight = req.weight_kg if req.weight_kg is not None else scale.read_kg()
    q = pricing.quote(weight, pricing.Policy(airline.allowance_kg, airline.max_bag_kg,
                                             airline.excess_rate_cents_per_kg))
    if q.rejected:
        status, msg = Status.REJECTED, q.reason
    elif q.within_allowance:
        status, msg = Status.READY_FOR_DROP, "Within allowance. Proceed to bag drop."
    else:
        status, msg = Status.AWAITING_PAYMENT, f"{q.excess_kg} kg over allowance. Please pay."
    tx = Transaction(airline_id=airline.id, flight_number=req.flight_number, weight_kg=weight,
                     excess_kg=q.excess_kg, fee_cents=q.fee_cents, status=status, message=msg)
    db.add(tx)
    db.flush()
    audit.append(db, airline.id, "TRANSACTION_WEIGHED", "kiosk", tx.id,
                 {"weight_kg": weight, "fee_cents": q.fee_cents, "status": status.value,
                  "flight_number": req.flight_number})
    enqueue_event(
        db,
        airline_id=airline.id,
        transaction_id=tx.id,
        event_type="TRANSACTION_WEIGHED",
        payload={
            "transaction_id": tx.id,
            "weight_kg": weight,
            "fee_cents": q.fee_cents,
            "status": status.value,
            "flight_number": req.flight_number,
        },
    )
    db.commit()
    db.refresh(tx)
    return tx


@app.post("/transactions/{tx_id}/pay", response_model=TransactionOut, dependencies=[Depends(require_kiosk)])
def pay(tx_id: int, req: PayRequest, db: Session = Depends(get_db)):
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(404, "Transaction not found")
    if tx.status != Status.AWAITING_PAYMENT:
        raise HTTPException(409, f"Transaction is {tx.status.value}, no payment due")
    if req.amount_cents < tx.fee_cents:
        raise HTTPException(402, "Amount is less than the fee due")
    tx.payment_method = req.method.value
    tx.paid_at = datetime.now(timezone.utc)
    tx.status = Status.READY_FOR_DROP
    tx.message = "Payment received. Proceed to bag drop."
    ledger.record_payment(db, db.get(Airline, tx.airline_id), tx)  # same commit: payment + ledger are atomic
    audit.append(db, tx.airline_id, "PAYMENT_RECEIVED", "kiosk", tx.id,
                 {"method": req.method.value, "fee_cents": tx.fee_cents})
    db.commit()
    db.refresh(tx)
    return tx


@app.post("/transactions/{tx_id}/waive", response_model=TransactionOut)
def waive(tx_id: int, body: WaiveRequest, staff: Staff = Depends(current_staff),
          db: Session = Depends(get_db)):
    """Authorised staff waive a fee. Needs a personal key and a reason, respects a per-person limit,
    and is permanently recorded and visible to the airline."""
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(404, "Transaction not found")
    if tx.status != Status.AWAITING_PAYMENT:
        raise HTTPException(409, f"Transaction is {tx.status.value}, nothing to waive")
    if tx.fee_cents > staff.waiver_limit_cents:
        raise HTTPException(403, "Fee is above your waiver limit; ask a supervisor")
    tx.waived_cents = tx.fee_cents
    tx.waived_by_staff_id = staff.id
    tx.waived_at = datetime.now(timezone.utc)
    tx.waiver_reason = body.reason
    tx.status = Status.READY_FOR_DROP
    tx.message = "Fee waived by authorised staff. Proceed to bag drop."
    audit.append(db, tx.airline_id, "FEE_WAIVED", f"staff:{staff.staff_code}", tx.id,
                 {"waived_cents": tx.waived_cents, "reason": body.reason})
    db.commit()
    db.refresh(tx)
    return tx


# ---------- airline: read only its own records ----------
@app.get("/airlines/me", response_model=AirlineOut)
def my_airline(airline: Airline = Depends(current_airline)):
    return airline


@app.get("/airlines/me/balance", response_model=BalanceOut)
def my_balance(airline: Airline = Depends(current_airline), db: Session = Depends(get_db)):
    return ledger.balance(db, airline)


@app.get("/airlines/me/ledger", response_model=list[LedgerEntryOut])
def my_ledger(airline: Airline = Depends(current_airline), db: Session = Depends(get_db)):
    return db.scalars(select(LedgerEntry).where(LedgerEntry.airline_id == airline.id)
                      .order_by(LedgerEntry.id)).all()


@app.get("/airlines/me/transactions", response_model=list[TransactionOut])
def my_transactions(limit: int = 100, airline: Airline = Depends(current_airline),
                    db: Session = Depends(get_db)):
    q = (select(Transaction).where(Transaction.airline_id == airline.id)
         .order_by(Transaction.id.desc()).limit(min(limit, 500)))
    return db.scalars(q).all()


@app.get("/airlines/me/transactions/{tx_id}", response_model=TransactionOut)
def my_transaction(tx_id: int, airline: Airline = Depends(current_airline),
                   db: Session = Depends(get_db)):
    tx = db.scalar(select(Transaction).where(Transaction.id == tx_id,
                                             Transaction.airline_id == airline.id))
    if tx is None:  # same 404 whether it doesn't exist or belongs to another airline
        raise HTTPException(404, "Transaction not found")
    return tx


@app.get("/airlines/me/audit", response_model=list[AuditEventOut])
def my_audit(airline: Airline = Depends(current_airline), db: Session = Depends(get_db)):
    return db.scalars(select(AuditEvent).where(AuditEvent.airline_id == airline.id)
                      .order_by(AuditEvent.seq)).all()


@app.get("/airlines/me/audit/verify", response_model=AuditVerifyOut)
def my_audit_verify(airline: Airline = Depends(current_airline), db: Session = Depends(get_db)):
    return audit.verify(db, airline.id)


def _stmt(db: Session, airline_id: int, year: int, month: int) -> Statement:
    stmt = db.scalar(select(Statement).where(Statement.airline_id == airline_id, Statement.year == year,
                                             Statement.month == month))
    if stmt is None:
        raise HTTPException(404, "Statement not found")
    return stmt


def _stmt_json(stmt: Statement) -> dict:
    return {"content_hash": stmt.content_hash, "statement": json.loads(stmt.data)}


def _stmt_pdf(stmt: Statement) -> Response:
    pdf = statement_pdf.render(json.loads(stmt.data), stmt.content_hash)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{stmt.statement_no}.pdf"'})


def _stmt_csv(stmt: Statement) -> Response:
    return Response(statements.to_csv(json.loads(stmt.data)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{stmt.statement_no}.csv"'})


@app.get("/airlines/me/statements", response_model=list[StatementListItem])
def my_statements(airline: Airline = Depends(current_airline), db: Session = Depends(get_db)):
    return db.scalars(select(Statement).where(Statement.airline_id == airline.id)
                      .order_by(Statement.year.desc(), Statement.month.desc())).all()


@app.get("/airlines/me/statements/{year}/{month}")
def my_statement(year: int, month: int, airline: Airline = Depends(current_airline),
                 db: Session = Depends(get_db)):
    return _stmt_json(_stmt(db, airline.id, year, month))


@app.get("/airlines/me/statements/{year}/{month}/pdf")
def my_statement_pdf(year: int, month: int, airline: Airline = Depends(current_airline),
                     db: Session = Depends(get_db)):
    return _stmt_pdf(_stmt(db, airline.id, year, month))


@app.get("/airlines/me/statements/{year}/{month}/csv")
def my_statement_csv(year: int, month: int, airline: Airline = Depends(current_airline),
                     db: Session = Depends(get_db)):
    return _stmt_csv(_stmt(db, airline.id, year, month))


# ---------- admin: staff ----------
@app.post("/staff", response_model=StaffCreated, status_code=201, dependencies=[Depends(require_admin)])
def create_staff(body: StaffCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Staff).where(Staff.staff_code == body.staff_code)):
        raise HTTPException(409, "Staff code already exists")
    key = new_staff_key()
    staff = Staff(**body.model_dump(), api_key_hash=hash_key(key))
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return StaffCreated(**StaffOut.model_validate(staff).model_dump(), api_key=key)


@app.get("/staff", response_model=list[StaffOut], dependencies=[Depends(require_admin)])
def list_staff(db: Session = Depends(get_db)):
    return db.scalars(select(Staff).order_by(Staff.staff_code)).all()


# Declared last: '/airlines/{airline_id}/...' must not shadow '/airlines/me/...'
# ---------- admin: settlement ----------
def _get_airline(db: Session, airline_id: int) -> Airline:
    airline = db.get(Airline, airline_id)
    if airline is None:
        raise HTTPException(404, "Airline not found")
    return airline


@app.get("/airlines/{airline_id}/balance", response_model=BalanceOut, dependencies=[Depends(require_admin)])
def airline_balance(airline_id: int, db: Session = Depends(get_db)):
    return ledger.balance(db, _get_airline(db, airline_id))


@app.get("/airlines/{airline_id}/ledger", response_model=list[LedgerEntryOut], dependencies=[Depends(require_admin)])
def airline_ledger(airline_id: int, db: Session = Depends(get_db)):
    _get_airline(db, airline_id)
    return db.scalars(select(LedgerEntry).where(LedgerEntry.airline_id == airline_id)
                      .order_by(LedgerEntry.id)).all()


@app.post("/airlines/{airline_id}/payouts", response_model=LedgerEntryOut, status_code=201,
          dependencies=[Depends(require_admin)])
def create_payout(airline_id: int, body: PayoutRequest, db: Session = Depends(get_db)):
    airline = _get_airline(db, airline_id)
    try:
        return ledger.record_payout(db, airline, body.amount_cents, body.reference)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/airlines/{airline_id}/audit/verify", response_model=AuditVerifyOut,
         dependencies=[Depends(require_admin)])
def airline_audit_verify(airline_id: int, db: Session = Depends(get_db)):
    _get_airline(db, airline_id)
    return audit.verify(db, airline_id)


# ---------- admin: statements ----------
@app.post("/airlines/{airline_id}/statements/{year}/{month}", status_code=201,
          dependencies=[Depends(require_admin)])
def generate_statement(airline_id: int, year: int, month: int, db: Session = Depends(get_db),
                       now: datetime = Depends(get_now)):
    """Generate the final statement for a closed month. Can only be done once per airline per month."""
    try:
        stmt = statements.generate(db, _get_airline(db, airline_id), year, month, now)
    except statements.StatementError as e:
        raise HTTPException(e.status_code, str(e))
    return _stmt_json(stmt)


@app.get("/airlines/{airline_id}/statements/{year}/{month}", dependencies=[Depends(require_admin)])
def admin_statement(airline_id: int, year: int, month: int, db: Session = Depends(get_db)):
    return _stmt_json(_stmt(db, airline_id, year, month))


@app.get("/airlines/{airline_id}/statements/{year}/{month}/pdf", dependencies=[Depends(require_admin)])
def admin_statement_pdf(airline_id: int, year: int, month: int, db: Session = Depends(get_db)):
    return _stmt_pdf(_stmt(db, airline_id, year, month))


@app.get("/airlines/{airline_id}/statements/{year}/{month}/csv", dependencies=[Depends(require_admin)])
def admin_statement_csv(airline_id: int, year: int, month: int, db: Session = Depends(get_db)):
    return _stmt_csv(_stmt(db, airline_id, year, month))


# ---------- admin: end-of-day cash reconciliation (all airlines, all kiosks) ----------
def _recon_out(r: CashReconciliation) -> ReconcileOut:
    return ReconcileOut(business_date=r.business_date, expected_cents=r.expected_cents,
                        counted_cents=r.counted_cents, variance_cents=r.variance_cents,
                        balanced=r.variance_cents == 0, counted_by=r.counted_by, notes=r.notes)


@app.post("/reconciliations", response_model=ReconcileOut, status_code=201,
          dependencies=[Depends(require_admin)])
def reconcile_cash(body: ReconcileRequest, db: Session = Depends(get_db)):
    """Expected cash = fees paid in cash that day (every airline, collector mode ignored: the cash is
    physically in the kiosk either way). One reconciliation per day; it cannot be redone."""
    if db.scalar(select(CashReconciliation).where(CashReconciliation.business_date == body.business_date)):
        raise HTTPException(409, "That day has already been reconciled")
    start, end = statements.day_bounds(body.business_date)
    expected = db.scalar(select(func.coalesce(func.sum(Transaction.fee_cents), 0)).where(
        Transaction.payment_method == "cash", Transaction.paid_at >= start, Transaction.paid_at < end)) or 0
    rec = CashReconciliation(business_date=body.business_date, expected_cents=expected,
                             counted_cents=body.counted_cents, variance_cents=body.counted_cents - expected,
                             counted_by=body.counted_by, notes=body.notes)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _recon_out(rec)


@app.get("/reconciliations", response_model=list[ReconcileOut], dependencies=[Depends(require_admin)])
def list_reconciliations(only_variances: bool = False, db: Session = Depends(get_db)):
    q = select(CashReconciliation).order_by(CashReconciliation.business_date.desc()).limit(366)
    if only_variances:
        q = q.where(CashReconciliation.variance_cents != 0)
    return [_recon_out(r) for r in db.scalars(q).all()]
