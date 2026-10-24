import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import OutboxEvent
from app.outbox import enqueue_event
from app.outbox_publisher import claim_pending, publish_pending


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

        saved_event = db.get(OutboxEvent, event_id)
        assert saved_event is not None
        assert saved_event.airline_id == airline["id"]
        assert saved_event.event_type == "TRANSACTION_WEIGHED"
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


def test_weigh_endpoint_persists_matching_outbox_event(client, make_airline):
    airline = make_airline("WX")

    response = client.post(
        "/weigh",
        headers={"X-Kiosk-Key": "test-kiosk"},
        json={
            "airline_code": "WX",
            "weight_kg": 25.2,
            "flight_number": "WX123",
        },
    )

    assert response.status_code == 201
    tx = response.json()

    with SessionLocal() as db:
        events = (
            db.query(OutboxEvent)
            .filter_by(
                airline_id=airline["id"],
                transaction_id=tx["id"],
                event_type="TRANSACTION_WEIGHED",
            )
            .all()
        )

    assert len(events) == 1
    assert json.loads(events[0].payload) == {
        "transaction_id": tx["id"],
        "weight_kg": 25.2,
        "fee_cents": tx["fee_cents"],
        "status": tx["status"],
        "flight_number": "WX123",
    }
    assert events[0].published_at is None
    assert events[0].attempts == 0


def test_publish_pending_records_success(client, make_airline):
    airline = make_airline("PS")
    delivered = []

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="TRANSACTION_WEIGHED",
            payload={"transaction_id": 456, "status": "weighed"},
        )
        event_id = event.id
        db.commit()

    with SessionLocal() as db:
        count = publish_pending(
            lambda event_id, event_type, payload: delivered.append(
                (event_id, event_type, payload)
            ),
        )
        db.commit()

    assert count == 1
    assert delivered == [
        (
            event_id,
            "TRANSACTION_WEIGHED",
            {"transaction_id": 456, "status": "weighed"},
        )
    ]

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved.published_at is not None
        assert saved.attempts == 0
        assert saved.last_error is None


def test_publish_pending_records_failure_for_retry(client, make_airline):
    airline = make_airline("PF")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 100},
        )
        event_id = event.id
        db.commit()

    def fail_delivery(event_id, event_type, payload):
        raise RuntimeError("temporary delivery failure")

    with SessionLocal() as db:
        count = publish_pending(fail_delivery)
        db.commit()

    assert count == 0

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved.published_at is None
        assert saved.attempts == 1
        assert saved.last_error == "temporary delivery failure"


def test_publish_pending_rejects_invalid_limit():
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="limit must be at least 1"):
            publish_pending(
                lambda event_id, event_type, payload: None,
                limit=0,
            )


def test_publish_pending_rejects_empty_worker_id():
    with pytest.raises(
        ValueError,
        match="worker_id must contain 1 to 100 characters",
    ):
        publish_pending(
            lambda event_id, event_type, payload: None,
            worker_id="",
        )


def test_claim_pending_assigns_event_to_worker(client, make_airline):
    airline = make_airline("CW")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="TRANSACTION_WEIGHED",
            payload={"transaction_id": 789},
        )
        event_id = event.id
        db.commit()

    with SessionLocal() as db:
        claimed = claim_pending(worker_id="worker-a", limit=10)

    assert len(claimed) == 1
    assert claimed[0]["id"] == event_id

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved.claimed_by == "worker-a"
        assert saved.claimed_until is not None
        assert saved.published_at is None


def test_claim_pending_skips_active_claim(client, make_airline):
    airline = make_airline("CS")

    with SessionLocal() as db:
        enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 200},
        )
        db.commit()

    with SessionLocal() as db:
        first = claim_pending(worker_id="worker-a")

    with SessionLocal() as db:
        second = claim_pending(worker_id="worker-b")

    assert len(first) == 1
    assert second == []


def test_claim_pending_recovers_expired_claim(client, make_airline):
    airline = make_airline("CE")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 300},
        )
        event_id = event.id
        db.commit()

    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)
        event.claimed_by = "worker-old"
        event.claimed_until = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        db.commit()

    with SessionLocal() as db:
        claimed = claim_pending(worker_id="worker-new")

    assert len(claimed) == 1
    assert claimed[0]["id"] == event_id

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)

        assert saved.claimed_by == "worker-new"
        assert saved.claimed_until is not None

        claimed_until = saved.claimed_until
        if claimed_until.tzinfo is None:
            claimed_until = claimed_until.replace(tzinfo=timezone.utc)

        assert claimed_until > datetime.now(timezone.utc)


def test_claim_pending_assigns_unique_claim_token(client, make_airline):
    airline = make_airline("CT")

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 400},
        )
        event_id = event.id
        db.commit()

    with SessionLocal() as db:
        first = claim_pending(worker_id="worker-a")

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved.claim_token is not None
        assert first[0]["claim_token"] == saved.claim_token
        first_token = saved.claim_token

        # Simulate the claim expiring and a different worker taking over.
        saved.claimed_until = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        db.commit()

    with SessionLocal() as db:
        second = claim_pending(worker_id="worker-b")

    assert len(second) == 1
    assert second[0]["id"] == event_id
    assert second[0]["claim_token"] != first_token

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)
        assert saved.claimed_by == "worker-b"
        assert saved.claim_token == second[0]["claim_token"]


def test_publish_pending_does_not_complete_expired_claim(
    client, make_airline
):
    airline = make_airline("EX")
    newer_claim = {}

    with SessionLocal() as db:
        event = enqueue_event(
            db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 500},
        )
        event_id = event.id
        db.commit()

    def expire_claim_during_delivery(event_id, event_type, payload):
        with SessionLocal() as other_db:
            saved = other_db.get(OutboxEvent, event_id)
            assert saved is not None

            saved.claimed_until = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )
            other_db.commit()

            reclaimed = claim_pending(worker_id="worker-new")

            assert len(reclaimed) == 1
            assert reclaimed[0]["id"] == event_id
            newer_claim.update(reclaimed[0])

    count = publish_pending(
        expire_claim_during_delivery,
        worker_id="worker-expiring",
    )

    assert count == 0
    assert newer_claim

    with SessionLocal() as db:
        saved = db.get(OutboxEvent, event_id)

        assert saved is not None
        assert saved.published_at is None
        assert saved.claimed_by == "worker-new"
        assert saved.claim_token == newer_claim["claim_token"]
        assert saved.claimed_until is not None
        assert saved.attempts == 0


def test_publisher_does_not_interfere_with_active_caller_transaction(
    client, make_airline
):
    airline = make_airline("TX")

    with SessionLocal() as setup_db:
        enqueue_event(
            setup_db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 600},
        )

        enqueue_event(
            setup_db,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload={"amount": 700},
        )

        setup_db.commit()

    with SessionLocal() as caller_db:
        caller_db.execute(text("SELECT 1"))
        assert caller_db.in_transaction()

        # Start a caller-owned transaction with an uncommitted change.
        caller_db.execute(
            text("CREATE TEMPORARY TABLE IF NOT EXISTS caller_transaction_probe "
                 "(value INTEGER)")
        )

        caller_db.execute(
            text("INSERT INTO caller_transaction_probe (value) VALUES (42)")
        )

        assert caller_db.in_transaction()

        claimed = claim_pending(worker_id="transaction-check", limit=1)
        assert len(claimed) == 1
        assert caller_db.in_transaction()

        delivered = []
        published = publish_pending(
            lambda event_id, event_type, payload: delivered.append(
                (event_id, payload)
            ),
            worker_id="publisher-check",
            limit=1,
        )

        assert published == 1
        claimed_payload = json.loads(claimed[0]["payload"])
        assert len(delivered) == 1
        assert delivered[0][1] in ({"amount": 600}, {"amount": 700})
        assert delivered[0][1] != claimed_payload
        assert isinstance(delivered[0][0], str)
        assert caller_db.in_transaction()

        # The caller's uncommitted data is still available in its own session.
        probe_values = caller_db.execute(
            text("SELECT value FROM caller_transaction_probe")
        ).scalars().all()
        assert probe_values == [42]

        caller_db.rollback()
