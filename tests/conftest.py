import os
import tempfile

if not os.getenv("DATABASE_URL"):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name}"

os.environ["ADMIN_API_KEY"] = "test-admin"
os.environ["KIOSK_API_KEY"] = "test-kiosk"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = {"X-Admin-Key": "test-admin"}
KIOSK = {"X-Kiosk-Key": "test-kiosk"}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_airline(client):
    def _make(code="SA", **kw):
        r = client.post(
            "/airlines",
            headers=ADMIN,
            json={"iata_code": code, "name": f"{code} Air", **kw},
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _make