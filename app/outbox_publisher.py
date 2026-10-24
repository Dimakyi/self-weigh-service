import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import OutboxEvent


DeliveryFunction = Callable[[str, str, dict], None]


def claim_pending(
    *,
    worker_id: str,
    limit: int = 100,
    lease_seconds: int = 60,
) -> list[dict]:
    """Claim pending events in a short transaction."""
    if not worker_id or len(worker_id) > 100:
        raise ValueError("worker_id must contain 1 to 100 characters")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be at least 1")

    now = datetime.now(timezone.utc)
    claimed_until = now + timedelta(seconds=lease_seconds)
    claim_token = str(uuid.uuid4())

    with SessionLocal() as db:
        with db.begin():
            candidates = (
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.published_at.is_(None),
                    (OutboxEvent.claimed_until.is_(None))
                    | (OutboxEvent.claimed_until < now),
                )
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(limit)
            )

            if db.get_bind().dialect.name == "postgresql":
                candidates = candidates.with_for_update(skip_locked=True)

            event_ids = list(db.scalars(candidates))

            if not event_ids:
                return []

            db.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id.in_(event_ids),
                    OutboxEvent.published_at.is_(None),
                    (OutboxEvent.claimed_until.is_(None))
                    | (OutboxEvent.claimed_until < now),
                )
                .values(
                    claimed_by=worker_id,
                    claim_token=claim_token,
                    claimed_until=claimed_until,
                )
            )

            rows = db.execute(
                select(
                    OutboxEvent.id,
                    OutboxEvent.event_type,
                    OutboxEvent.payload,
                    OutboxEvent.claim_token,
                ).where(
                    OutboxEvent.id.in_(event_ids),
                    OutboxEvent.claim_token == claim_token,
                )
            ).all()

            return [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "payload": row.payload,
                    "claim_token": row.claim_token,
                }
                for row in rows
            ]
            

def publish_pending(
    deliver: DeliveryFunction,
    *,
    limit: int = 100,
    worker_id: str | None = None,
    lease_seconds: int = 60,
) -> int:
    """Deliver claimed events and record outcomes.

    Delivery is at-least-once; consumers should deduplicate by event ID.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be at least 1")

    if worker_id is None:
        worker_id = str(uuid.uuid4())
    elif not worker_id or len(worker_id) > 100:
        raise ValueError("worker_id must contain 1 to 100 characters")

    events = claim_pending(
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
    )

    published_count = 0

    for event in events:
        error = None

        try:
            payload = json.loads(event["payload"])
            deliver(event["id"], event["event_type"], payload)
        except Exception as exc:
            error = str(exc)[:1000] or type(exc).__name__

        now = datetime.now(timezone.utc)

        with SessionLocal() as db:
            with db.begin():
                result = db.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.id == event["id"],
                        OutboxEvent.claim_token == event["claim_token"],
                        OutboxEvent.published_at.is_(None),
                        OutboxEvent.claimed_until > now,
                    )
                    .values(
                        published_at=now if error is None else None,
                        attempts=OutboxEvent.attempts
                        + (1 if error is not None else 0),
                        last_error=error,
                        claimed_by=None,
                        claim_token=None,
                        claimed_until=None,
                    )
                )

                if result.rowcount == 1 and error is None:
                    published_count += 1

    return published_count
