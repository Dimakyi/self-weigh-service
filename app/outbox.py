import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import OutboxEvent


def enqueue_event(
    db: Session,
    *,
    airline_id: int,
    event_type: str,
    payload: dict,
    transaction_id: int | None = None,
) -> OutboxEvent:
    """Add an event to the outbox within the caller's transaction."""
    event = OutboxEvent(
        id=str(uuid4()),
        airline_id=airline_id,
        transaction_id=transaction_id,
        event_type=event_type,
        payload=json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
        attempts=0,
    )
    db.add(event)
    return event
