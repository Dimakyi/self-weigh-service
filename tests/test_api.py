from conftest import ADMIN, KIOSK


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


def test_cannot_pay_twice(client, make_airline):
    make_airline("SA")
    tx = weigh(client, "SA", 24).json()
    body = {"method": "cash", "amount_cents": tx["fee_cents"]}
    client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK, json=body)
    assert client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK, json=body).status_code == 409


def test_overlimit_bag_rejected(client, make_airline):
    make_airline("SA")
    assert weigh(client, "SA", 45).json()["status"] == "REJECTED"


def test_simulated_scale_reading(client, make_airline):
    make_airline("SA")
    r = client.post("/weigh", headers=KIOSK, json={"airline_code": "SA"})
    assert r.status_code == 201


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
