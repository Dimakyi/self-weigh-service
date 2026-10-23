from conftest import KIOSK


def test_passenger_verification_requires_kiosk_key(client):
    response = client.post(
        "/passenger/verify",
        json={
            "passenger_name": "Test Passenger",
            "boarding_pass_name": "Test Passenger",
            "flight_number": "SA123",
            "boarding_pass_flight": "SA123",
        },
    )
    assert response.status_code == 401


def test_passenger_verification_accepts_matching_simulated_details(client):
    response = client.post(
        "/passenger/verify",
        headers=KIOSK,
        json={
            "passenger_name": "Test Passenger",
            "boarding_pass_name": "Test Passenger",
            "flight_number": "SA123",
            "boarding_pass_flight": "SA123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["mode"] == "SIMULATION"
    assert "official identity verification" in body["message"].lower()


def test_passenger_verification_rejects_name_mismatch(client):
    response = client.post(
        "/passenger/verify",
        headers=KIOSK,
        json={
            "passenger_name": "Test Passenger",
            "boarding_pass_name": "Different Passenger",
            "flight_number": "SA123",
            "boarding_pass_flight": "SA123",
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is False


def test_passenger_verification_rejects_flight_mismatch(client):
    response = client.post(
        "/passenger/verify",
        headers=KIOSK,
        json={
            "passenger_name": "Test Passenger",
            "boarding_pass_name": "Test Passenger",
            "flight_number": "SA123",
            "boarding_pass_flight": "FA456",
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is False


def test_passenger_verification_rejects_blank_details(client):
    response = client.post(
        "/passenger/verify",
        headers=KIOSK,
        json={
            "passenger_name": " ",
            "boarding_pass_name": "Test Passenger",
            "flight_number": "SA123",
            "boarding_pass_flight": "SA123",
        },
    )

    assert response.status_code == 422
