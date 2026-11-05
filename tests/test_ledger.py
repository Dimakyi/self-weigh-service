import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import ADMIN, KIOSK
from app.db import SessionLocal, engine, get_db
from app.ledger import split_fee
from app.main import app as api_app
from app.models import AuditEvent, LedgerEntry, LedgerType

H = lambda a: {"X-Api-Key": a["api_key"]}  # noqa: E731


def pay_overweight(client, code, kg):
    tx = client.post("/weigh", headers=KIOSK, json={"airline_code": code, "weight_kg": kg}).json()
    client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK,
                json={"method": "card", "amount_cents": tx["fee_cents"]})
    return tx


def balance(client, airline):
    return client.get(f"/airlines/{airline['id']}/balance", headers=ADMIN).json()


def test_split_fee_always_adds_up():
    for gross in (1, 99, 15000, 45001, 123457):
        cut, share = split_fee(gross, 500)
        assert cut + share == gross and cut >= 0


def test_payment_creates_ledger_split(client, make_airline):
    sa = make_airline("SA", service_fee_bps=500)
    pay_overweight(client, "SA", 25.2)          # fee 45000, cut 2250
    b = balance(client, sa)
    assert b["gross_collected_cents"] == 45000
    assert b["service_fees_cents"] == 2250
    assert b["balance_due_cents"] == 42750


def test_unpaid_and_free_bags_create_no_ledger_entries(client, make_airline):
    sa = make_airline("SA")
    client.post("/weigh", headers=KIOSK, json={"airline_code": "SA", "weight_kg": 20})   # free
    client.post("/weigh", headers=KIOSK, json={"airline_code": "SA", "weight_kg": 25})   # unpaid
    assert balance(client, sa)["gross_collected_cents"] == 0


def test_payout_reduces_balance_and_cannot_exceed_it(client, make_airline):
    sa = make_airline("SA", service_fee_bps=0)
    pay_overweight(client, "SA", 24)            # 15000
    r = client.post(f"/airlines/{sa['id']}/payouts", headers=ADMIN, json={"amount_cents": 10000, "reference": "EFT-1"})
    assert r.status_code == 201
    assert balance(client, sa)["balance_due_cents"] == 5000
    over = client.post(f"/airlines/{sa['id']}/payouts", headers=ADMIN, json={"amount_cents": 5001})
    assert over.status_code == 409
    assert balance(client, sa)["balance_due_cents"] == 5000


def test_airline_direct_creates_no_operator_ledger(client, make_airline):
    fa = make_airline("FA", collector="airline_direct")
    pay_overweight(client, "FA", 25)
    b = balance(client, fa)
    assert b["gross_collected_cents"] == 0 and b["balance_due_cents"] == 0


def test_airlines_see_only_their_own_balance_and_ledger(client, make_airline):
    sa, fa = make_airline("SA"), make_airline("FA")
    pay_overweight(client, "SA", 25)
    pay_overweight(client, "FA", 24)
    assert client.get("/airlines/me/balance", headers=H(sa)).json()["gross_collected_cents"] == 30000
    assert client.get("/airlines/me/balance", headers=H(fa)).json()["gross_collected_cents"] == 15000
    assert {e["transaction_id"] for e in client.get("/airlines/me/ledger", headers=H(sa)).json()}.isdisjoint(
        {e["transaction_id"] for e in client.get("/airlines/me/ledger", headers=H(fa)).json()})


def test_settlement_admin_endpoints_need_admin_key(client, make_airline):
    sa = make_airline("SA")
    assert client.get(f"/airlines/{sa['id']}/balance").status_code == 401
    assert client.post(f"/airlines/{sa['id']}/payouts", headers=KIOSK, json={"amount_cents": 1}).status_code == 401


def test_ledger_has_no_edit_or_delete_endpoints(client, make_airline):
    sa = make_airline("SA")
    assert client.delete(f"/airlines/{sa['id']}/ledger", headers=ADMIN).status_code == 405
    assert client.put(f"/airlines/{sa['id']}/ledger", headers=ADMIN, json={}).status_code == 405


def test_simultaneous_payouts_cannot_exceed_balance(client, make_airline):
    # PostgreSQL is required to test SELECT FOR UPDATE properly.
    if engine.dialect.name != "postgresql":
        pytest.skip("Payout row-locking concurrency test requires PostgreSQL")

    sa = make_airline("SA", service_fee_bps=0)

    # Create exactly 45,000 cents available for payout.
    pay_overweight(client, "SA", 25.2)

    barrier = Barrier(2)

    def synchronized_get_db():
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            yield db
        finally:
            db.close()

    api_app.dependency_overrides[get_db] = synchronized_get_db

    def send_payout(reference):
        with TestClient(api_app) as concurrent_client:
            response = concurrent_client.post(
                f"/airlines/{sa['id']}/payouts",
                headers=ADMIN,
                json={
                    "amount_cents": 30_000,
                    "reference": reference,
                },
            )
            return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(
                send_payout,
                ["RACE-PAYOUT-1", "RACE-PAYOUT-2"],
            ))
    finally:
        api_app.dependency_overrides.pop(get_db, None)

    assert sorted(statuses) == [201, 409]

    # Only one payout should be recorded.
    with SessionLocal() as db:
        payouts = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.airline_id == sa["id"],
                LedgerEntry.entry_type == LedgerType.PAYOUT,
            )
        ).all()

        assert len(payouts) == 1
        assert payouts[0].amount_cents == -30_000

        payout_audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.airline_id == sa["id"],
                AuditEvent.event_type == "PAYOUT_RECORDED",
            )
        ).all()

        assert len(payout_audits) == 1

    final_balance = balance(client, sa)
    assert final_balance["paid_out_cents"] == 30_000
    assert final_balance["balance_due_cents"] == 15_000