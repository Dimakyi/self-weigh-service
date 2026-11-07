import pytest
import uuid
from pydantic import ValidationError

from conftest import ADMIN, KIOSK
from app.db import SessionLocal
from app.main import app as api_app, get_scale, WeighRequest
from app.models import Transaction, Status
from sqlalchemy import select
from app import config
from app.models import AuditEvent, LedgerEntry, LedgerType, OutboxEvent
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from app.db import get_db


def weigh(client, code, kg, flight=None):
    return client.post("/weigh", headers=KIOSK,
                       json={"airline_code": code, "weight_kg": kg, "flight_number": flight})


def test_within_allowance_goes_straight_to_drop(client, make_airline):
    make_airline("SA")
    r = weigh(client, "SA", 18.6)
    assert r.status_code == 201 and r.json()["status"] == "READY_FOR_DROP"


def test_overweight_requires_payment_then_ready(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()
    assert tx["status"] == "AWAITING_PAYMENT" and tx["fee_cents"] == 45000
    low = client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK, json={"method": "card", "amount_cents": 1})
    assert low.status_code == 402
    ok = client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK, json={"method": "card", "amount_cents": 45000})
    assert ok.json()["status"] == "READY_FOR_DROP"


def test_payment_requires_kiosk_key(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()
    url = f"/transactions/{tx['id']}/pay"
    body = {"method": "card", "amount_cents": tx["fee_cents"]}

    missing_key = client.post(url, json=body)
    wrong_key = client.post(
        url,
        headers={"X-Kiosk-Key": "wrong"},
        json=body,
    )

    assert missing_key.status_code == 401
    assert wrong_key.status_code == 401


def test_cannot_pay_twice(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()
    body = {"method": "cash", "amount_cents": tx["fee_cents"]}

    url = f"/transactions/{tx['id']}/pay"

    first = client.post(url, headers=KIOSK, json=body)
    second = client.post(url, headers=KIOSK, json=body)

    assert first.status_code == 200
    assert second.status_code == 409

    with SessionLocal() as db:
        ledger_entries = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == tx["id"],
                LedgerEntry.entry_type == LedgerType.PAYMENT,
            )
        ).all()

        audit_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.transaction_id == tx["id"],
                AuditEvent.event_type == "PAYMENT_RECEIVED",
            )
        ).all()

        outbox_events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.transaction_id == tx["id"],
                OutboxEvent.event_type == "PAYMENT_RECEIVED",
            )
        ).all()

        assert len(ledger_entries) == 1
        assert len(audit_events) == 1
        assert len(outbox_events) == 1


def test_payment_retry_with_same_idempotency_key_returns_original(
    client, make_airline
):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()

    url = f"/transactions/{tx['id']}/pay"
    body = {"method": "card", "amount_cents": tx["fee_cents"]}
    headers = {**KIOSK, "Idempotency-Key": "payment-retry-001"}

    first = client.post(url, headers=headers, json=body)
    second = client.post(url, headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["status"] == "READY_FOR_DROP"

    with SessionLocal() as db:
        ledger_entries = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == tx["id"],
                LedgerEntry.entry_type == LedgerType.PAYMENT,
            )
        ).all()

        audit_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.transaction_id == tx["id"],
                AuditEvent.event_type == "PAYMENT_RECEIVED",
            )
        ).all()

        outbox_events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.transaction_id == tx["id"],
                OutboxEvent.event_type == "PAYMENT_RECEIVED",
            )
        ).all()

        assert len(ledger_entries) == 1
        assert len(audit_events) == 1
        assert len(outbox_events) == 1


def test_payment_retry_with_different_method_returns_conflict(
    client, make_airline
):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()

    url = f"/transactions/{tx['id']}/pay"
    headers = {**KIOSK, "Idempotency-Key": "payment-retry-002"}

    first = client.post(
        url,
        headers=headers,
        json={"method": "card", "amount_cents": tx["fee_cents"]},
    )

    second = client.post(
        url,
        headers=headers,
        json={"method": "cash", "amount_cents": tx["fee_cents"]},
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_payment_retry_with_different_amount_returns_conflict(
    client, make_airline
):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()

    url = f"/transactions/{tx['id']}/pay"
    headers = {**KIOSK, "Idempotency-Key": "payment-retry-003"}

    first = client.post(
        url,
        headers=headers,
        json={"method": "card", "amount_cents": tx["fee_cents"]},
    )

    second = client.post(
        url,
        headers=headers,
        json={"method": "card", "amount_cents": tx["fee_cents"] - 1},
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_simultaneous_payments_only_process_once(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()

    body = {"method": "cash", "amount_cents": tx["fee_cents"]}
    url = f"/transactions/{tx['id']}/pay"

    # Make both requests wait until they are ready to proceed.
    barrier = Barrier(2)

    def synchronized_get_db():
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            yield db
        finally:
            db.close()

    api_app.dependency_overrides[get_db] = synchronized_get_db

    def send_payment():
        with TestClient(api_app) as concurrent_client:
            response = concurrent_client.post(
                url,
                headers=KIOSK,
                json=body,
            )
            return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(
                lambda _: send_payment(),
                range(2),
            ))
    finally:
        api_app.dependency_overrides.pop(get_db, None)

    assert sorted(statuses) == [200, 409]

def test_simultaneous_payment_and_waiver_only_one_wins(client, make_airline):
    from app.models import Staff

    sa = make_airline("SA")
    staff_response = client.post(
        "/staff",
        headers=ADMIN,
        json={
            "staff_code": "RACE01",
            "name": "Race Test Staff",
            "waiver_limit_cents": 50_000,
        },
    )
    assert staff_response.status_code == 201, staff_response.text
    staff = staff_response.json()

    tx = weigh(client, "SA", 25.2).json()
    tx_id = tx["id"]

    barrier = Barrier(2)

    def synchronized_get_db():
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            yield db
        finally:
            db.close()

    api_app.dependency_overrides[get_db] = synchronized_get_db

    def send_payment():
        with TestClient(api_app) as concurrent_client:
            response = concurrent_client.post(
                f"/transactions/{tx_id}/pay",
                headers=KIOSK,
                json={
                    "method": "card",
                    "amount_cents": tx["fee_cents"],
                },
            )
            return response.status_code

    def send_waiver():
        with TestClient(api_app) as concurrent_client:
            response = concurrent_client.post(
                f"/transactions/{tx_id}/waive",
                headers={"X-Staff-Key": staff["api_key"]},
                json={"reason": "Approved during concurrency test"},
            )
            return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            payment_future = executor.submit(send_payment)
            waiver_future = executor.submit(send_waiver)

            payment_status = payment_future.result(timeout=20)
            waiver_status = waiver_future.result(timeout=20)
    finally:
        api_app.dependency_overrides.pop(get_db, None)

    assert sorted([payment_status, waiver_status]) == [200, 409]

    with SessionLocal() as db:
        final_tx = db.get(Transaction, tx_id)
        assert final_tx is not None
        assert final_tx.status == Status.READY_FOR_DROP

        ledger_entries = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == tx_id
            )
        ).all()

        audit_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.airline_id == sa["id"],
                AuditEvent.transaction_id == tx_id,
            )
        ).all()

        event_types = [event.event_type for event in audit_events]

        if payment_status == 200:
            assert final_tx.paid_at is not None
            assert final_tx.waived_at is None
            assert final_tx.waived_cents == 0

            assert sum(
                entry.entry_type == LedgerType.PAYMENT
                for entry in ledger_entries
            ) == 1

            assert "PAYMENT_RECEIVED" in event_types
            assert "FEE_WAIVED" not in event_types

        else:
            assert final_tx.waived_at is not None
            assert final_tx.paid_at is None
            assert final_tx.waived_cents == tx["fee_cents"]

            assert ledger_entries == []

            assert "FEE_WAIVED" in event_types
            assert "PAYMENT_RECEIVED" not in event_types

    verification = client.get(
        "/airlines/me/audit/verify",
        headers={"X-Api-Key": sa["api_key"]},
    )
    assert verification.status_code == 200
    assert verification.json()["valid"] is True


def test_overlimit_bag_rejected(client, make_airline):
    make_airline("SA")
    assert weigh(client, "SA", 45).json()["status"] == "REJECTED"


def test_simulated_scale_reading(client, make_airline):
    make_airline("SA")
    r = client.post("/weigh", headers=KIOSK, json={"airline_code": "SA"})
    assert r.status_code == 201

@pytest.mark.parametrize("environment", ["staging", "production"])
def test_manual_weights_rejected_outside_development(
    client, make_airline, monkeypatch, environment
):
    make_airline("SA")
    monkeypatch.setattr(config, "APP_ENV", environment)

    response = weigh(client, "SA", 20)

    assert response.status_code == 422

    with SessionLocal() as db:
        assert db.query(Transaction).count() == 0


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_simulated_scale_unavailable_outside_development(
    client, make_airline, monkeypatch, environment
):
    make_airline("SA")
    monkeypatch.setattr(config, "APP_ENV", environment)

    response = client.post(
        "/weigh",
        headers=KIOSK,
        json={"airline_code": "SA"},
    )

    assert response.status_code == 503

    with SessionLocal() as db:
        assert db.query(Transaction).count() == 0    


def test_each_airline_uses_its_own_rules(client, make_airline):
    make_airline("SA", allowance_kg=23, excess_rate_cents_per_kg=15000)
    make_airline("FA", allowance_kg=20, excess_rate_cents_per_kg=10000)
    assert weigh(client, "SA", 22).json()["fee_cents"] == 0
    assert weigh(client, "FA", 22).json()["fee_cents"] == 20000


def test_unknown_airline_rejected(client):
    assert weigh(client, "ZZ", 20).status_code == 404


def test_duplicate_airline_rejected(client, make_airline):
    make_airline("SA")
    r = client.post("/airlines", headers=ADMIN, json={"iata_code": "sa", "name": "Dup"})
    assert r.status_code == 409


# ---- isolation ----
def test_airline_sees_only_its_own_transactions(client, make_airline):
    sa, fa = make_airline("SA"), make_airline("FA")
    weigh(client, "SA", 20)
    weigh(client, "SA", 25)
    other = weigh(client, "FA", 21).json()
    mine = client.get("/airlines/me/transactions", headers={"X-Api-Key": sa["api_key"]}).json()
    assert len(mine) == 2 and all(t["airline_id"] == sa["id"] for t in mine)
    theirs = client.get("/airlines/me/transactions", headers={"X-Api-Key": fa["api_key"]}).json()
    assert [t["id"] for t in theirs] == [other["id"]]


def test_airline_cannot_fetch_another_airlines_transaction(client, make_airline):
    sa, _ = make_airline("SA"), make_airline("FA")
    other = weigh(client, "FA", 21).json()
    r = client.get(f"/airlines/me/transactions/{other['id']}", headers={"X-Api-Key": sa["api_key"]})
    assert r.status_code == 404


# ---- auth ----
def test_kiosk_endpoints_need_kiosk_key(client, make_airline):
    make_airline("SA")
    assert client.post("/weigh", json={"airline_code": "SA", "weight_kg": 20}).status_code == 401
    assert client.post("/weigh", headers={"X-Kiosk-Key": "wrong"},
                       json={"airline_code": "SA", "weight_kg": 20}).status_code == 401


def test_admin_endpoints_need_admin_key(client):
    assert client.get("/airlines").status_code == 401
    assert client.post("/airlines", headers=KIOSK, json={"iata_code": "SA", "name": "x"}).status_code == 401


def test_staff_management_endpoints_need_admin_key(client):
    staff_data = {
        "staff_code": "S099",
        "name": "Test Staff",
        "waiver_limit_cents": 100_000,
    }

    assert client.get("/staff").status_code == 401
    assert client.get("/staff", headers=KIOSK).status_code == 401

    assert client.post("/staff", json=staff_data).status_code == 401
    assert client.post(
        "/staff", headers=KIOSK, json=staff_data
    ).status_code == 401


def test_airline_endpoints_need_valid_airline_key(client, make_airline):
    make_airline("SA")
    assert client.get("/airlines/me").status_code == 401
    assert client.get("/airlines/me", headers={"X-Api-Key": "nope"}).status_code == 401


def test_api_key_is_not_stored_in_plaintext(client, make_airline):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Airline
    a = make_airline("SA")
    with SessionLocal() as db:
        row = db.scalar(select(Airline))
        assert row.api_key_hash != a["api_key"] and len(row.api_key_hash) == 64


def test_inactive_airline_key_is_rejected(client, make_airline):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Airline

    airline = make_airline("SA")
    with SessionLocal() as db:
        row = db.scalar(select(Airline))
        row.active = False
        db.commit()

    response = client.get(
        "/airlines/me",
        headers={"X-Api-Key": airline["api_key"]},
    )
    assert response.status_code == 401


def test_airline_allowance_cannot_exceed_max_bag_weight(client):
    response = client.post(
        "/airlines",
        headers=ADMIN,
        json={
            "iata_code": "XX",
            "name": "Test Air",
            "allowance_kg": 33,
            "max_bag_kg": 32,
        },
    )

    assert response.status_code == 422


def test_overpayment_is_rejected(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 25.2).json()

    response = client.post(
        f"/transactions/{tx['id']}/pay",
        headers=KIOSK,
        json={
            "method": "card",
            "amount_cents": tx["fee_cents"] + 1,
        },
    )

    assert response.status_code == 422

@pytest.mark.parametrize("weight", [0, -1])
def test_invalid_submitted_weight_is_rejected(
    client, make_airline, weight
):
    make_airline("SA")

    response = weigh(client, "SA", weight)

    assert response.status_code == 422


def test_nan_weight_returns_422_with_valid_json_error(client, make_airline):
    make_airline("SA")

    response = client.post(
        "/weigh",
        headers=KIOSK,
        content='{"airline_code":"SA","weight_kg":NaN}',
    )

    assert response.status_code == 422
    assert response.json()["detail"]
    assert "input" not in response.json()["detail"][0]


@pytest.mark.parametrize(
    "weight",
    [float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_submitted_weight_is_rejected(weight):
    with pytest.raises(ValidationError):
        WeighRequest(
            airline_code="SA",
            weight_kg=weight,
        )

class FixedScale:
    def __init__(self, reading):
        self.reading = reading

    def read_kg(self):
        return self.reading

@pytest.mark.parametrize(
    "reading",
    [float("nan"), float("inf"), float("-inf"), 0, -1],
)
def test_invalid_scale_reading_returns_503_without_transaction(
    client, make_airline, monkeypatch, reading
):
    make_airline("SA")

    monkeypatch.setitem(
        api_app.dependency_overrides,
        get_scale,
        lambda: FixedScale(reading),
    )

    response = client.post(
        "/weigh",
        headers=KIOSK,
        json={"airline_code": "SA"},
    )

    assert response.status_code == 503

    with SessionLocal() as db:
        assert db.query(Transaction).count() == 0


def test_dead_letter_listing_requires_admin_key(client):
    response = client.get("/admin/outbox/dead-lettered")

    assert response.status_code == 401


def test_dead_letter_listing_returns_only_dead_lettered_events(
    client, make_airline
):
    airline = make_airline("DL")
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        dead_event = OutboxEvent(
            id=str(uuid.uuid4()),
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload='{"amount_cents":100}',
            created_at=now,
            attempts=5,
            last_error="Delivery failed",
            dead_lettered_at=now,
        )
        pending_event = OutboxEvent(
            id=str(uuid.uuid4()),
            airline_id=airline["id"],
            event_type="TRANSACTION_WEIGHED",
            payload='{"weight_kg":20}',
            created_at=now,
            attempts=1,
        )
        db.add_all([dead_event, pending_event])
        db.commit()
        dead_event_id = dead_event.id

    response = client.get(
        "/admin/outbox/dead-lettered",
        headers=ADMIN,
    )

    assert response.status_code == 200
    results = response.json()

    assert len(results) == 1
    assert results[0]["id"] == dead_event_id
    assert results[0]["airline_id"] == airline["id"]
    assert results[0]["attempts"] == 5
    assert results[0]["last_error"] == "Delivery failed"


@pytest.mark.parametrize("limit", [0, 501])
def test_dead_letter_listing_rejects_invalid_limit(client, limit):
    response = client.get(
        f"/admin/outbox/dead-lettered?limit={limit}",
        headers=ADMIN,
    )

    assert response.status_code == 422


def test_requeue_dead_lettered_event_requires_admin_key(client):
    response = client.post(
        f"/admin/outbox/{uuid.uuid4()}/requeue"
    )

    assert response.status_code == 401


def test_requeue_dead_lettered_event_returns_404_for_unknown_id(client):
    response = client.post(
        f"/admin/outbox/{uuid.uuid4()}/requeue",
        headers=ADMIN,
    )

    assert response.status_code == 404


def test_requeue_rejects_event_that_is_not_dead_lettered(
    client, make_airline
):
    airline = make_airline("RQ")
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        event = OutboxEvent(
            id=str(uuid.uuid4()),
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload='{"amount_cents":100}',
            created_at=now,
            attempts=1,
        )
        db.add(event)
        db.commit()
        event_id = event.id

    response = client.post(
        f"/admin/outbox/{event_id}/requeue",
        headers=ADMIN,
    )

    assert response.status_code == 409


def test_requeue_dead_lettered_event_resets_state_and_records_audit(
    client, make_airline
):
    airline = make_airline("RQ")
    now = datetime.now(timezone.utc)
    event_id = str(uuid.uuid4())

    with SessionLocal() as db:
        event = OutboxEvent(
            id=event_id,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload='{"amount_cents":100}',
            created_at=now,
            attempts=5,
            last_error="Delivery failed",
            dead_lettered_at=now,
        )
        db.add(event)
        db.commit()

    response = client.post(
        f"/admin/outbox/{event_id}/requeue",
        headers=ADMIN,
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == event_id

    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)

        assert event is not None
        assert event.attempts == 0
        assert event.dead_lettered_at is None
        assert event.last_error is None
        assert event.next_attempt_at is None
        assert event.claimed_by is None
        assert event.claim_token is None
        assert event.claimed_until is None

        audit_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.airline_id == airline["id"],
                AuditEvent.event_type == "OUTBOX_EVENT_REQUEUED",
            )
        )

        assert audit_event is not None
        assert audit_event.actor == "admin"
        assert event_id in audit_event.payload
        assert "PAYMENT_RECEIVED" in audit_event.payload
        assert "5" in audit_event.payload


def test_requeue_same_event_twice_is_rejected(
    client, make_airline
):
    airline = make_airline("RQ")
    now = datetime.now(timezone.utc)
    event_id = str(uuid.uuid4())

    with SessionLocal() as db:
        event = OutboxEvent(
            id=event_id,
            airline_id=airline["id"],
            event_type="PAYMENT_RECEIVED",
            payload='{"amount_cents":100}',
            created_at=now,
            attempts=5,
            last_error="Delivery failed",
            dead_lettered_at=now,
        )
        db.add(event)
        db.commit()

    first = client.post(
        f"/admin/outbox/{event_id}/requeue",
        headers=ADMIN,
    )
    second = client.post(
        f"/admin/outbox/{event_id}/requeue",
        headers=ADMIN,
    )

    assert first.status_code == 200
    assert second.status_code == 409
