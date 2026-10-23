import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now():
    return datetime.now(timezone.utc)


class Collector(str, enum.Enum):
    operator = "operator"                # airport/operator collects, then settles with the airline
    airline_direct = "airline_direct"    # money goes straight to the airline (used in a later step)


class LedgerType(str, enum.Enum):
    PAYMENT = "PAYMENT"          # + fee collected on the airline's behalf
    SERVICE_FEE = "SERVICE_FEE"  # - operator's cut, retained
    PAYOUT = "PAYOUT"            # - money actually paid out to the airline


class Status(str, enum.Enum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    READY_FOR_DROP = "READY_FOR_DROP"
    REJECTED = "REJECTED"


class Airline(Base):
    __tablename__ = "airlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iata_code: Mapped[str] = mapped_column(String(3), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    allowance_kg: Mapped[float] = mapped_column(Float)
    max_bag_kg: Mapped[float] = mapped_column(Float)
    excess_rate_cents_per_kg: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    service_fee_bps: Mapped[int] = mapped_column(Integer, default=500)  # operator cut, basis points (500 = 5%)
    collector: Mapped[Collector] = mapped_column(Enum(Collector), default=Collector.operator)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the airline's key
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airline_id: Mapped[int] = mapped_column(ForeignKey("airlines.id"), index=True)
    flight_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    excess_kg: Mapped[int] = mapped_column(Integer, default=0)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[Status] = mapped_column(Enum(Status))
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(String(200), default="")
    waived_cents: Mapped[int] = mapped_column(Integer, default=0)
    waived_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    waiver_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Staff(Base):
    """Airport staff who may waive fees, each with a personal key and a waiver limit."""
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    waiver_limit_cents: Mapped[int] = mapped_column(Integer, default=50_000)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Hash-chained, one chain per airline. Each hash covers the previous hash plus this event's content."""
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("airline_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airline_id: Mapped[int] = mapped_column(ForeignKey("airlines.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[str] = mapped_column(String(40))          # ISO string, stored as text so hashes re-verify exactly
    event_type: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(60))
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str] = mapped_column(Text)           # canonical JSON
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class LedgerEntry(Base):
    """Append-only. Sum of amount_cents per airline = what the operator owes that airline."""
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airline_id: Mapped[int] = mapped_column(ForeignKey("airlines.id"), index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    entry_type: Mapped[LedgerType] = mapped_column(Enum(LedgerType))
    amount_cents: Mapped[int] = mapped_column(Integer)   # signed
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Statement(Base):
    """A finalised monthly statement. Stored once; PDF and CSV are rendered from this snapshot."""
    __tablename__ = "statements"
    __table_args__ = (UniqueConstraint("airline_id", "year", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airline_id: Mapped[int] = mapped_column(ForeignKey("airlines.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    statement_no: Mapped[str] = mapped_column(String(30))
    data: Mapped[str] = mapped_column(Text)               # canonical JSON snapshot
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 of data; also written to the audit chain
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CashReconciliation(Base):
    """End-of-day cash check across all kiosks: expected (from records) vs counted (from the cash box)."""
    __tablename__ = "cash_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[object] = mapped_column(Date, unique=True)
    expected_cents: Mapped[int] = mapped_column(Integer)
    counted_cents: Mapped[int] = mapped_column(Integer)
    variance_cents: Mapped[int] = mapped_column(Integer)   # counted - expected
    counted_by: Mapped[str] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OutboxEvent(Base):
    """Durable events waiting to be delivered to downstream systems."""
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_pending", "published_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    airline_id: Mapped[int] = mapped_column(
        ForeignKey("airlines.id"), index=True
    )

    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
