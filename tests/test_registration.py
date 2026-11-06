from sqlalchemy import select

from conftest import ADMIN
from app.db import SessionLocal
from app.models import Staff
from app.security import hash_key


def test_airline_registration_returns_profile_and_one_time_key(client):
    response = client.post(
        "/airlines",
        headers=ADMIN,
        json={"iata_code": "sa", "name": "South Africa Air"},
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["iata_code"] == "SA"
    assert data["name"] == "South Africa Air"
    assert data["active"] is True
    assert data["api_key"].startswith("swk_")


def test_staff_registration_returns_profile_and_one_time_key(client):
    response = client.post(
        "/staff",
        headers=ADMIN,
        json={
            "staff_code": "S001",
            "name": "Test Staff",
            "waiver_limit_cents": 75_000,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["staff_code"] == "S001"
    assert data["name"] == "Test Staff"
    assert data["waiver_limit_cents"] == 75_000
    assert data["active"] is True
    assert data["api_key"].startswith("sws_")


def test_duplicate_staff_code_rejected(client):
    payload = {
        "staff_code": "S001",
        "name": "Test Staff",
        "waiver_limit_cents": 50_000,
    }

    first = client.post("/staff", headers=ADMIN, json=payload)
    assert first.status_code == 201, first.text

    duplicate = client.post(
        "/staff",
        headers=ADMIN,
        json={**payload, "name": "Different Name"},
    )
    assert duplicate.status_code == 409


def test_staff_api_key_is_stored_as_hash(client):
    response = client.post(
        "/staff",
        headers=ADMIN,
        json={"staff_code": "S002", "name": "Secure Staff"},
    )
    assert response.status_code == 201, response.text
    api_key = response.json()["api_key"]

    with SessionLocal() as db:
        staff = db.scalar(select(Staff).where(Staff.staff_code == "S002"))

        assert staff is not None
        assert staff.api_key_hash == hash_key(api_key)
        assert staff.api_key_hash != api_key
        assert len(staff.api_key_hash) == 64
