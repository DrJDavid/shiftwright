"""Public SMS opt-in (/sms.html -> POST /api/sms/optin): works signed out, stores consent, rejects bad input."""
from fastapi.testclient import TestClient

from shiftwright_api.main import SMS_OPTIN_SCOPE

OK = {"name": "Jordan Lee", "employer": "Harbor Grill", "phone": "(512) 555-0123",
      "consent": True, "consent_text": "Text me shift offers... Reply STOP to opt out."}


def test_optin_works_signed_out_and_records_consent(app):
    with TestClient(app) as c:
        r = c.post("/api/sms/optin", json=OK)
        assert r.status_code == 200, r.text
        rec = app.state.db.get(SMS_OPTIN_SCOPE, "sms_optin", "+15125550123")
        assert rec["name"] == "Jordan Lee" and rec["employer"] == "Harbor Grill"
        assert "STOP" in rec["consent_text"] and rec["at"]


def test_optin_requires_the_box_a_name_and_a_us_number(app):
    with TestClient(app) as c:
        assert c.post("/api/sms/optin", json={**OK, "consent": False}).status_code == 422
        assert c.post("/api/sms/optin", json={**OK, "consent": "yes"}).status_code == 422
        assert c.post("/api/sms/optin", json={**OK, "name": " "}).status_code == 422
        assert c.post("/api/sms/optin", json={**OK, "phone": "555-0123"}).status_code == 422
        assert c.post("/api/sms/optin", json={**OK, "phone": "+1 512 555 0123"}).status_code == 200
