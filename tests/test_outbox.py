import json

from app.db import SessionLocal
from app.models import OutboxEvent
from app.outbox import enqueue_event


def test_enqueue_event_adds_event_to_current_session(client, make_airline):
    airline = make_airline("OB")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="TRANSACTION_WEIGHED",
            payload={"transaction_id": 123, "status": "weighed"},
            transaction_id=None,
        )

        assert isinstance(event, OutboxEvent)
        assert event.airline_id == airline["id"]
        assert event.event_type == "TRANSACTION_WEIGHED"
        assert json.loads(event.payload) == {
            "transaction_id": 123,
            "status": "weighed",
        }
        assert event in db.new

        event_id = event.id
        db.commit()

    with SessionLocal() as db:
        saved_event = db.get(OutboxEvent, event_id)

        assert saved_event is not None
        assert saved_event.airline_id == airline["id"]
        assert json.loads(saved_event.payload) == {
            "transaction_id": 123,
            "status": "weighed",
        }


def test_enqueue_event_does_not_commit_automatically(client, make_airline):
    airline = make_airline("OT")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 100},
        )

        assert event in db.new
        assert event.published_at is None
        assert event.attempts == 0
        event_id = event.id
        db.rollback()

    with SessionLocal() as db:
        assert db.get(OutboxEvent, event_id) is None