
from datetime import datetime, timezone

from sqlalchemy import select, func, or_

from app.db import SessionLocal
from app.models import OutboxEvent


def get_outbox_statistics():
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        total_events = db.scalar(
            select(func.count()).select_from(OutboxEvent)
        )

        published_events = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.published_at.is_not(None))
        )

        dead_lettered_events = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.dead_lettered_at.is_not(None))
        )

        claimed_events = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                OutboxEvent.claimed_until > now,
            )
        )

        retrying_events = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                OutboxEvent.next_attempt_at > now,
            )
        )

        pending_events = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                or_(
                    OutboxEvent.next_attempt_at.is_(None),
                    OutboxEvent.next_attempt_at <= now,
                ),
                or_(
                    OutboxEvent.claimed_until.is_(None),
                    OutboxEvent.claimed_until < now,
                ),
            )
        )

        return {
            "total_events": total_events,
            "pending_events": pending_events,
            "claimed_events": claimed_events,
            "retrying_events": retrying_events,
            "published_events": published_events,
            "dead_lettered_events": dead_lettered_events,
        }
