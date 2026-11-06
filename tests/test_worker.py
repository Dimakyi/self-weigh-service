import json
import logging
import threading

from sqlalchemy import select

from app import outbox_publisher, worker
from app.db import SessionLocal
from app.models import OutboxEvent
from app.outbox import enqueue_event


def _queue(airline_id, n=1):
    ids = []
    with SessionLocal() as db:
        for i in range(n):
            ids.append(
                enqueue_event(
                    db,
                    airline_id=airline_id,
                    event_type="TRANSACTION_WEIGHED",
                    payload={"n": i},
                ).id
            )
        db.commit()
    return ids


def _published(ids):
    with SessionLocal() as db:
        rows = db.scalars(select(OutboxEvent).where(OutboxEvent.id.in_(ids))).all()
        return {r.id: r.published_at is not None for r in rows}


def test_worker_publishes_pending_events_then_stops(client, make_airline):
    airline = make_airline("W1")
    ids = _queue(airline["id"], 3)
    stop = threading.Event()
    delivered = []

    def deliver(event_id, event_type, payload):
        delivered.append(event_id)
        if len(delivered) == 3:
            stop.set()

    worker.run_forever(deliver, stop=stop, poll_seconds=0.01, worker_id="t")

    assert sorted(delivered) == sorted(ids)
    assert all(_published(ids).values())


def test_worker_exits_promptly_when_stop_already_set(client):
    stop = threading.Event()
    stop.set()
    calls = []

    worker.run_forever(lambda *a: calls.append(a), stop=stop, poll_seconds=30)

    assert calls == []


def test_worker_keeps_running_after_delivery_failure(client, make_airline):
    airline = make_airline("W2")
    ids = _queue(airline["id"], 1)
    stop = threading.Event()
    attempts = []

    def flaky(event_id, event_type, payload):
        attempts.append(event_id)
        if len(attempts) == 1:
            raise RuntimeError("broker down")
        stop.set()

    worker.run_forever(flaky, stop=stop, poll_seconds=0.01, worker_id="t")

    assert len(attempts) == 2
    assert _published(ids) == {ids[0]: True}
    with SessionLocal() as db:
        assert db.get(OutboxEvent, ids[0]).attempts == 1


def test_worker_survives_batch_error(client, monkeypatch):
    stop = threading.Event()
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        if len(calls) >= 2:
            stop.set()
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker, "publish_pending", broken)

    worker.run_forever(lambda *a: None, stop=stop, poll_seconds=0.01, worker_id="t")

    assert len(calls) == 2


def test_log_delivery_writes_event_to_log(caplog):
    with caplog.at_level(logging.INFO, logger="selfweigh.worker"):
        worker.log_delivery("evt-1", "FEE_WAIVED", {"b": 2, "a": 1})

    assert "evt-1" in caplog.text
    assert "FEE_WAIVED" in caplog.text
    assert json.dumps({"a": 1, "b": 2}) in caplog.text


def test_default_worker_id_fits_column():
    assert 1 <= len(worker.default_worker_id()) <= 100
