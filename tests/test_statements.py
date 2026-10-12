import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader
from sqlalchemy import update

from conftest import ADMIN, KIOSK
from app import config
from app.db import SessionLocal
from app.main import app, get_now
from app.models import AuditEvent, LedgerEntry

AK = lambda a: {"X-Api-Key": a["api_key"]}  # noqa: E731


def local_now():
    return datetime.now(timezone.utc).astimezone(ZoneInfo(config.TIMEZONE))


@pytest.fixture
def month_closed():
    """Pretend it's 40 days from now so the current month counts as closed."""
    app.dependency_overrides[get_now] = lambda: datetime.now(timezone.utc) + timedelta(days=40)
    yield (local_now().year, local_now().month)
    app.dependency_overrides.pop(get_now, None)


def staff(client, code="S001"):
    return client.post("/staff", headers=ADMIN, json={"staff_code": code, "name": code,
                                                       "waiver_limit_cents": 100_000}).json()


def bag(client, code, kg):
    return client.post("/weigh", headers=KIOSK, json={"airline_code": code, "weight_kg": kg}).json()


def pay(client, tx, method):
    return client.post(f"/transactions/{tx['id']}/pay", headers=KIOSK,
                       json={"method": method, "amount_cents": tx["fee_cents"]})


def waive(client, tx, st, reason="Flight delayed, gate agent approved"):
    return client.post(f"/transactions/{tx['id']}/waive", headers={"X-Staff-Key": st["api_key"]},
                       json={"reason": reason})


def generate(client, airline, ym):
    return client.post(f"/airlines/{airline['id']}/statements/{ym[0]}/{ym[1]}", headers=ADMIN)


def busy_month(client, make_airline):
    sa = make_airline("SA", service_fee_bps=500)
    st = staff(client)
    pay(client, bag(client, "SA", 25.2), "card")        # 45000
    pay(client, bag(client, "SA", 24), "cash")          # 15000
    waive(client, bag(client, "SA", 26), st)            # 45000 waived
    bag(client, "SA", 20)                               # free
    bag(client, "SA", 45)                               # rejected
    client.post(f"/airlines/{sa['id']}/payouts", headers=ADMIN, json={"amount_cents": 10000, "reference": "EFT-9"})
    return sa


def test_statement_totals_and_csv_reconcile(client, make_airline, month_closed):
    sa = busy_month(client, make_airline)
    r = generate(client, sa, month_closed)
    assert r.status_code == 201, r.text
    d = r.json()["statement"]
    assert d["summary"] == {"bags_weighed": 5, "bags_rejected": 1, "bags_over_allowance": 3,
                            "bags_within_allowance": 1, "bags_waived": 1, "fees_waived_cents": 45000}
    st = d["settlement"]
    assert st == {"applicable": True, "opening_balance_cents": 0, "gross_collected_cents": 60000,
                  "service_fees_cents": 3000, "payouts_cents": 10000, "closing_balance_cents": 47000}
    assert d["payments_by_method"] == {"card": {"count": 1, "cents": 45000}, "cash": {"count": 1, "cents": 15000}}
    assert d["waivers"][0]["staff_code"] == "S001" and d["waivers"][0]["waived_cents"] == 45000
    # CSV money rows must add up to closing - opening
    text = client.get(f"/airlines/me/statements/{month_closed[0]}/{month_closed[1]}/csv", headers=AK(sa)).text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert sum(int(x["amount_cents"]) for x in rows) == st["closing_balance_cents"] - st["opening_balance_cents"]
    assert {x["event_type"] for x in rows} == {"PAYMENT", "SERVICE_FEE", "PAYOUT", "WAIVER"}


def test_month_must_be_closed(client, make_airline):
    sa = make_airline("SA")
    now = local_now()
    assert generate(client, sa, (now.year, now.month)).status_code == 400


def test_invalid_month_rejected(client, make_airline):
    sa = make_airline("SA")
    assert generate(client, sa, (2026, 13)).status_code == 422


def test_statements_are_final_one_per_month(client, make_airline, month_closed):
    sa = make_airline("SA")
    assert generate(client, sa, month_closed).status_code == 201
    assert generate(client, sa, month_closed).status_code == 409


def test_generate_needs_admin_key(client, make_airline, month_closed):
    sa = make_airline("SA")
    r = client.post(f"/airlines/{sa['id']}/statements/{month_closed[0]}/{month_closed[1]}", headers=KIOSK)
    assert r.status_code == 401


def test_airline_sees_only_its_own_statements(client, make_airline, month_closed):
    sa, fa = make_airline("SA"), make_airline("FA")
    generate(client, sa, month_closed)
    assert len(client.get("/airlines/me/statements", headers=AK(sa)).json()) == 1
    assert client.get("/airlines/me/statements", headers=AK(fa)).json() == []
    y, m = month_closed
    assert client.get(f"/airlines/me/statements/{y}/{m}", headers=AK(fa)).status_code == 404
    assert client.get(f"/airlines/me/statements/{y}/{m}/pdf", headers=AK(fa)).status_code == 404
    assert client.get(f"/airlines/me/statements/{y}/{m}").status_code == 401


def test_statement_is_a_frozen_snapshot(client, make_airline, month_closed):
    sa = busy_month(client, make_airline)
    first = generate(client, sa, month_closed).json()
    pay(client, bag(client, "SA", 27), "card")          # happens after the statement was issued
    y, m = month_closed
    again = client.get(f"/airlines/me/statements/{y}/{m}", headers=AK(sa)).json()
    assert again == first


def test_statement_is_anchored_in_audit_chain(client, make_airline, month_closed):
    sa = busy_month(client, make_airline)
    h = generate(client, sa, month_closed).json()["content_hash"]
    events = client.get("/airlines/me/audit", headers=AK(sa)).json()
    last = events[-1]
    assert last["event_type"] == "STATEMENT_GENERATED" and h in last["payload"]
    assert client.get("/airlines/me/audit/verify", headers=AK(sa)).json()["valid"] is True


def test_tampered_chain_blocks_statement(client, make_airline, month_closed):
    sa = make_airline("SA")
    bag(client, "SA", 25)
    with SessionLocal() as db:
        db.execute(update(AuditEvent).where(AuditEvent.seq == 1).values(actor="someone"))
        db.commit()
    assert generate(client, sa, month_closed).status_code == 409


def test_pdf_renders_with_key_figures(client, make_airline, month_closed):
    sa = busy_month(client, make_airline)
    generate(client, sa, month_closed)
    y, m = month_closed
    r = client.get(f"/airlines/me/statements/{y}/{m}/pdf", headers=AK(sa))
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert f"SA-{y}-{m:02d}" in text and "470.00" in text and "Closing balance" in text
    assert "S001" in text and "Flight delayed" in text


def test_csv_blocks_formula_injection(client, make_airline, month_closed):
    sa, st = make_airline("SA"), staff(client)
    waive(client, bag(client, "SA", 25), st, reason="=HYPERLINK(\"http://evil\",\"x\")")
    generate(client, sa, month_closed)
    y, m = month_closed
    text = client.get(f"/airlines/me/statements/{y}/{m}/csv", headers=AK(sa)).text
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_airline_direct_statement_has_no_settlement(client, make_airline, month_closed):
    fa, st = make_airline("FA", collector="airline_direct"), staff(client)
    pay(client, bag(client, "FA", 25), "card")
    waive(client, bag(client, "FA", 26), st)
    d = generate(client, fa, month_closed).json()["statement"]
    assert d["settlement"]["applicable"] is False and d["settlement"]["closing_balance_cents"] == 0
    assert d["summary"]["bags_waived"] == 1


def test_opening_balance_carries_from_earlier_months(client, make_airline, month_closed):
    sa = make_airline("SA", service_fee_bps=500)
    pay(client, bag(client, "SA", 25.2), "card")        # +45000 -2250
    old = datetime.now(timezone.utc) - timedelta(days=40)
    with SessionLocal() as db:
        db.execute(update(LedgerEntry).values(created_at=old))
        db.commit()
    d = generate(client, sa, month_closed).json()["statement"]["settlement"]
    assert d["opening_balance_cents"] == 42750 and d["gross_collected_cents"] == 0
    assert d["closing_balance_cents"] == 42750
    prev = old.astimezone(ZoneInfo(config.TIMEZONE))
    p = generate(client, sa, (prev.year, prev.month)).json()["statement"]["settlement"]
    assert p["gross_collected_cents"] == 45000 and p["closing_balance_cents"] == 42750


# ---- cash reconciliation ----
def today():
    return local_now().date().isoformat()


def recon(client, counted, day=None, headers=ADMIN):
    return client.post("/reconciliations", headers=headers,
                       json={"business_date": day or today(), "counted_cents": counted, "counted_by": "Thandi"})


def test_cash_reconciliation_balanced(client, make_airline):
    make_airline("SA"), make_airline("FA", collector="airline_direct"), staff(client)
    pay(client, bag(client, "SA", 24), "cash")                 # 15000
    pay(client, bag(client, "FA", 25), "cash")                 # 30000, airline_direct still has cash in the box
    pay(client, bag(client, "SA", 25), "card")                 # not cash
    waive(client, bag(client, "SA", 26), staff(client, "S002"))  # waived, not cash
    r = recon(client, 45000)
    assert r.status_code == 201
    assert r.json()["expected_cents"] == 45000 and r.json()["balanced"] is True


def test_cash_variance_is_flagged(client, make_airline):
    make_airline("SA")
    pay(client, bag(client, "SA", 24), "cash")
    r = recon(client, 14000).json()
    assert r["variance_cents"] == -1000 and r["balanced"] is False
    flagged = client.get("/reconciliations?only_variances=true", headers=ADMIN).json()
    assert len(flagged) == 1 and flagged[0]["variance_cents"] == -1000


def test_a_day_cannot_be_reconciled_twice(client, make_airline):
    make_airline("SA")
    assert recon(client, 0).status_code == 201
    assert recon(client, 0).status_code == 409


def test_reconciliation_needs_admin_key(client):
    assert recon(client, 0, headers=KIOSK).status_code == 401
    assert client.get("/reconciliations").status_code == 401


def test_other_days_cash_is_excluded(client, make_airline):
    make_airline("SA")
    pay(client, bag(client, "SA", 24), "cash")
    other = (local_now() - timedelta(days=3)).date().isoformat()
    assert recon(client, 0, day=other).json()["expected_cents"] == 0
