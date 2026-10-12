from sqlalchemy import delete, update

from conftest import ADMIN, KIOSK
from app.db import SessionLocal
from app.models import AuditEvent

AK = lambda a: {"X-Api-Key": a["api_key"]}  # noqa: E731


def make_staff(client, code="S001", limit=50_000):
    r = client.post("/staff", headers=ADMIN, json={"staff_code": code, "name": code, "waiver_limit_cents": limit})
    assert r.status_code == 201, r.text
    return r.json()


def overweight(client, code="SA", kg=25.2):
    return client.post("/weigh", headers=KIOSK, json={"airline_code": code, "weight_kg": kg}).json()


def waive(client, tx, staff, reason="Flight delayed, gate agent approved"):
    return client.post(f"/transactions/{tx['id']}/waive", headers={"X-Staff-Key": staff["api_key"]},
                       json={"reason": reason})


# ---- waivers ----
def test_waiver_clears_fee_and_is_visible_to_airline(client, make_airline):
    sa, staff = make_airline("SA"), make_staff(client)
    tx = overweight(client)
    r = waive(client, tx, staff)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "READY_FOR_DROP" and body["waived_cents"] == 45000
    seen = client.get(f"/airlines/me/transactions/{tx['id']}", headers=AK(sa)).json()
    assert seen["waiver_reason"] == "Flight delayed, gate agent approved"


def test_waiver_needs_staff_key(client, make_airline):
    make_airline("SA")
    tx = overweight(client)
    assert client.post(f"/transactions/{tx['id']}/waive", json={"reason": "no key here"}).status_code == 401
    assert client.post(f"/transactions/{tx['id']}/waive", headers=KIOSK,
                       json={"reason": "kiosk key is not staff"}).status_code == 401


def test_waiver_needs_a_real_reason(client, make_airline):
    make_airline("SA")
    staff = make_staff(client)
    tx = overweight(client)
    assert waive(client, tx, staff, reason="ok").status_code == 422


def test_waiver_above_limit_refused(client, make_airline):
    make_airline("SA")
    staff = make_staff(client, limit=10_000)
    tx = overweight(client)            # fee 45000
    assert waive(client, tx, staff).status_code == 403
    assert client.get(f"/transactions/{tx['id']}").status_code in (404, 405)  # no unscoped read endpoint


def test_cannot_waive_free_or_paid_bag(client, make_airline):
    make_airline("SA")
    staff = make_staff(client)
    free = client.post("/weigh", headers=KIOSK, json={"airline_code": "SA", "weight_kg": 20}).json()
    assert waive(client, free, staff).status_code == 409
    tx = overweight(client)
    client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK, json={"method": "card", "amount_cents": 45000})
    assert waive(client, tx, staff).status_code == 409


def test_waived_fee_creates_no_ledger_money(client, make_airline):
    sa, staff = make_airline("SA"), make_staff(client)
    waive(client, overweight(client), staff)
    assert client.get(f"/airlines/{sa['id']}/balance", headers=ADMIN).json()["gross_collected_cents"] == 0


# ---- audit chain ----
def test_events_are_chained_and_verify(client, make_airline):
    sa, staff = make_airline("SA"), make_staff(client)
    t1 = overweight(client)
    client.post(f"/transactions/{t1['id']}/pay", headers=KIOSK, json={"method": "cash", "amount_cents": 45000})
    waive(client, overweight(client, kg=24), staff)
    client.post(f"/airlines/{sa['id']}/payouts", headers=ADMIN, json={"amount_cents": 1000, "reference": "EFT"})
    events = client.get("/airlines/me/audit", headers=AK(sa)).json()
    assert [e["event_type"] for e in events] == ["TRANSACTION_WEIGHED", "PAYMENT_RECEIVED",
                                                  "TRANSACTION_WEIGHED", "FEE_WAIVED", "PAYOUT_RECORDED"]
    assert events[0]["prev_hash"] == "0" * 64
    assert all(events[i]["prev_hash"] == events[i - 1]["hash"] for i in range(1, len(events)))
    v = client.get("/airlines/me/audit/verify", headers=AK(sa)).json()
    assert v["valid"] and v["events_checked"] == 5 and v["head_hash"] == events[-1]["hash"]


def test_waiver_event_records_who_and_why(client, make_airline):
    sa, staff = make_airline("SA"), make_staff(client, "S042")
    waive(client, overweight(client), staff, reason="Medical equipment, approved")
    ev = [e for e in client.get("/airlines/me/audit", headers=AK(sa)).json() if e["event_type"] == "FEE_WAIVED"][0]
    assert ev["actor"] == "staff:S042" and "Medical equipment" in ev["payload"]


def test_editing_an_old_event_is_detected(client, make_airline):
    sa = make_airline("SA")
    overweight(client)
    overweight(client, kg=24)
    with SessionLocal() as db:
        db.execute(update(AuditEvent).where(AuditEvent.seq == 1).values(payload='{"fee_cents":0}'))
        db.commit()
    v = client.get("/airlines/me/audit/verify", headers=AK(sa)).json()
    assert v["valid"] is False and v["first_bad_seq"] == 1


def test_deleting_a_middle_event_is_detected(client, make_airline):
    sa = make_airline("SA")
    for kg in (25, 24, 26):
        overweight(client, kg=kg)
    with SessionLocal() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.seq == 2))
        db.commit()
    v = client.get("/airlines/me/audit/verify", headers=AK(sa)).json()
    assert v["valid"] is False and v["first_bad_seq"] == 2


def test_chains_are_separate_per_airline(client, make_airline):
    sa, fa = make_airline("SA"), make_airline("FA")
    overweight(client, "SA")
    overweight(client, "FA")
    overweight(client, "FA", kg=24)
    assert len(client.get("/airlines/me/audit", headers=AK(sa)).json()) == 1
    assert len(client.get("/airlines/me/audit", headers=AK(fa)).json()) == 2
    # tampering with one airline's chain doesn't affect the other
    with SessionLocal() as db:
        db.execute(update(AuditEvent).where(AuditEvent.airline_id == sa["id"]).values(actor="someone"))
        db.commit()
    assert client.get("/airlines/me/audit/verify", headers=AK(sa)).json()["valid"] is False
    assert client.get("/airlines/me/audit/verify", headers=AK(fa)).json()["valid"] is True


def test_admin_can_verify_any_chain_and_audit_needs_auth(client, make_airline):
    sa = make_airline("SA")
    overweight(client)
    assert client.get(f"/airlines/{sa['id']}/audit/verify", headers=ADMIN).json()["valid"] is True
    assert client.get(f"/airlines/{sa['id']}/audit/verify").status_code == 401
    assert client.get("/airlines/me/audit").status_code == 401


def test_empty_chain_is_valid(client, make_airline):
    sa = make_airline("SA")
    v = client.get("/airlines/me/audit/verify", headers=AK(sa)).json()
    assert v["valid"] and v["events_checked"] == 0
