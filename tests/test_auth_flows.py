"""OTP + JWT lifecycle flows (TASKS §26, D1-LE-7)."""

import pytest
from django_tenants.utils import schema_context

pytestmark = pytest.mark.django_db

REQUEST_URL = "/api/v1/auth/otp/request/"
VERIFY_URL = "/api/v1/auth/otp/verify/"
REFRESH_URL = "/api/v1/auth/refresh/"


def _code_from(sms_text: str) -> str:
    return sms_text.split("code: ")[1].split(".")[0].strip()


def test_otp_request_and_verify_happy_path(tenant_a, client_for, user_in, sms_outbox):
    user = user_in(tenant_a, roles=["teacher"])  # pre-created (open_registration off)
    phone = user.phone
    client = client_for(tenant_a)

    resp = client.post(REQUEST_URL, {"identifier": phone}, format="json")
    assert resp.status_code == 202
    assert len(sms_outbox) == 1

    code = _code_from(sms_outbox[0]["text"])
    resp = client.post(VERIFY_URL, {"identifier": phone, "code": code}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body
    assert "refresh" in body


def test_otp_verify_unknown_identifier_rejected(tenant_a, client_for, sms_outbox):
    """open_registration is off by default — unknown identifiers cannot self-register."""
    client = client_for(tenant_a)
    phone = "+998905550001"
    client.post(REQUEST_URL, {"identifier": phone}, format="json")
    code = _code_from(sms_outbox[0]["text"])
    resp = client.post(VERIFY_URL, {"identifier": phone, "code": code}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "user_not_found"


def test_otp_wrong_code_rejected(tenant_a, client_for, user_in, sms_outbox):
    user = user_in(tenant_a, roles=["teacher"])
    client = client_for(tenant_a)
    client.post(REQUEST_URL, {"identifier": user.phone}, format="json")
    resp = client.post(VERIFY_URL, {"identifier": user.phone, "code": "000000"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_refresh_rotation_and_reuse_detection(tenant_a, client_for, user_in):
    from apps.auth.services import issue_token_pair

    user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        pair = issue_token_pair(user)
    client = client_for(tenant_a)

    rotated = client.post(REFRESH_URL, {"refresh": pair["refresh"]}, format="json")
    assert rotated.status_code == 200
    assert rotated.json()["refresh"] != pair["refresh"]

    replay = client.post(REFRESH_URL, {"refresh": pair["refresh"]}, format="json")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"
