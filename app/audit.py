"""Tamper-evident audit log: one SHA-256 hash chain per airline.

hash = sha256(prev_hash + canonical_json(event fields)). Changing, deleting or reordering any past event
breaks every later hash, so verify() detects it. This detects tampering; it does not prevent it. Someone
with full database access could rebuild a whole chain, so the latest hash should be published somewhere
the operator can't edit (the monthly statement does this in a later step).
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Airline, AuditEvent

GENESIS = "0" * 64


def canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash: str, seq: int, ts: str, airline_id: int, event_type: str,
            actor: str, transaction_id: int | None, payload: str) -> str:
    body = canonical({"seq": seq, "ts": ts, "airline_id": airline_id, "event_type": event_type,
                      "actor": actor, "transaction_id": transaction_id, "payload": payload})
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append(db: Session, airline_id: int, event_type: str, actor: str,
           transaction_id: int | None = None, payload: dict | None = None) -> AuditEvent:
    """Add an event to the airline's chain. Caller commits, so the event and the action are atomic."""
    db.flush()
    # Lock the airline row so concurrent writers can't fork the chain (a no-op on SQLite).
    db.execute(select(Airline.id).where(Airline.id == airline_id).with_for_update())
    last = db.scalar(select(AuditEvent).where(AuditEvent.airline_id == airline_id)
                     .order_by(AuditEvent.seq.desc()).limit(1))
    seq = last.seq + 1 if last else 1
    prev = last.hash if last else GENESIS
    ts = datetime.now(timezone.utc).isoformat()
    body = canonical(payload or {})
    event = AuditEvent(airline_id=airline_id, seq=seq, ts=ts, event_type=event_type, actor=actor,
                       transaction_id=transaction_id, payload=body, prev_hash=prev,
                       hash=_digest(prev, seq, ts, airline_id, event_type, actor, transaction_id, body))
    db.add(event)
    return event


def verify(db: Session, airline_id: int) -> dict:
    events = db.scalars(select(AuditEvent).where(AuditEvent.airline_id == airline_id)
                        .order_by(AuditEvent.seq)).all()
    prev, expected_seq = GENESIS, 1
    for e in events:
        ok = (e.seq == expected_seq and e.prev_hash == prev and
              e.hash == _digest(prev, e.seq, e.ts, e.airline_id, e.event_type, e.actor,
                                e.transaction_id, e.payload))
        if not ok:
            return {"valid": False, "events_checked": expected_seq - 1,
                    "first_bad_seq": expected_seq, "head_hash": prev}
        prev, expected_seq = e.hash, expected_seq + 1
    return {"valid": True, "events_checked": len(events), "first_bad_seq": None, "head_hash": prev}
