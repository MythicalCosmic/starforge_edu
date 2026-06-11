"""Auth lifecycle flows: username+password login, password change/reset (OTP),
JWT rotation, tenant binding (TASKS §26; owner auth pivot 2026-06-11)."""

import re

import pytest
from django.conf import settings
from django.core.cache import cache
from django_tenants.utils import schema_context

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/v1/auth/login/"
CHANGE_URL = "/api/v1/auth/password/change/"
RESET_REQUEST_URL = "/api/v1/auth/password/reset/request/"
RESET_CONFIRM_URL = "/api/v1/auth/password/reset/confirm/"
REFRESH_URL = "/api/v1/auth/refresh/"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all/"
ME_URL = "/api/v1/users/me/"

PASSWORD = "Quasar-Lantern-42"
NEW_PASSWORD = "Nebula-Compass-77"


def _code_from(sms_text: str) -> str:
    match = re.search(rf"\b(\d{{{settings.OTP_LENGTH}}})\b", sms_text)
    assert match, f"no {settings.OTP_LENGTH}-digit code in: {sms_text!r}"
    return match.group(1)


def _password_user(tenant, user_in, *, roles=("teacher",), password=PASSWORD):
    user = user_in(tenant, roles=list(roles))
    with schema_context(tenant.schema_name):
        user.set_password(password)
        user.save(update_fields=["password"])
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_happy_path_registers_device(tenant_a, client_for, user_in):
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)

    resp = client.post(
        LOGIN_URL,
        {"username": user.username, "password": PASSWORD, "device_id": "dev-1", "platform": "android"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body
    assert "refresh" in body

    with schema_context(tenant_a.schema_name):
        assert user.devices.filter(device_id="dev-1", platform="android").exists()

    authed = client_for(tenant_a)
    authed.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    me = authed.get(ME_URL)
    assert me.status_code == 200
    assert me.json()["username"] == user.username


def test_login_wrong_password_401(tenant_a, client_for, user_in):
    user = _password_user(tenant_a, user_in)
    resp = client_for(tenant_a).post(
        LOGIN_URL, {"username": user.username, "password": "wrong-wrong-1"}, format="json"
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_login_unknown_username_same_error(tenant_a, client_for):
    resp = client_for(tenant_a).post(
        LOGIN_URL, {"username": "ghost-user", "password": "whatever-123"}, format="json"
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_login_inactive_user_same_error(tenant_a, client_for, user_in):
    user = _password_user(tenant_a, user_in)
    with schema_context(tenant_a.schema_name):
        user.is_active = False
        user.save(update_fields=["is_active"])
    resp = client_for(tenant_a).post(
        LOGIN_URL, {"username": user.username, "password": PASSWORD}, format="json"
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_login_per_username_throttle_429(tenant_a, client_for, user_in):
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)
    for _ in range(5):  # login_user rate: 5/min
        assert (
            client.post(LOGIN_URL, {"username": user.username, "password": "bad-pass-123"}, format="json")
        ).status_code == 401
    resp = client.post(LOGIN_URL, {"username": user.username, "password": "bad-pass-123"}, format="json")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "throttled"


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


def test_password_change_wrong_old_400(tenant_a, user_in, as_user):
    user = _password_user(tenant_a, user_in)
    client = as_user(tenant_a, user)
    resp = client.post(
        CHANGE_URL, {"old_password": "not-the-one-1", "new_password": NEW_PASSWORD}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "wrong_password"


def test_password_change_ends_other_sessions(tenant_a, client_for, user_in, as_user):
    from apps.auth.services import issue_token_pair

    user = _password_user(tenant_a, user_in)
    with schema_context(tenant_a.schema_name):
        old_pair = issue_token_pair(user)
    client = as_user(tenant_a, user)

    resp = client.post(CHANGE_URL, {"old_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json")
    assert resp.status_code == 200
    new_pair = resp.json()

    # Old access dies (tv bumped), old refresh dies (blacklisted)...
    stale = client_for(tenant_a)
    stale.credentials(HTTP_AUTHORIZATION=f"Bearer {old_pair['access']}")
    assert stale.get(ME_URL).status_code == 401
    assert (
        client_for(tenant_a).post(REFRESH_URL, {"refresh": old_pair["refresh"]}, format="json")
    ).status_code == 401

    # ...the returned pair works, and so does the new password.
    fresh = client_for(tenant_a)
    fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {new_pair['access']}")
    assert fresh.get(ME_URL).status_code == 200
    assert (
        client_for(tenant_a).post(
            LOGIN_URL, {"username": user.username, "password": NEW_PASSWORD}, format="json"
        )
    ).status_code == 200


# ---------------------------------------------------------------------------
# Password reset (OTP repurposed — request/confirm)
# ---------------------------------------------------------------------------


def test_password_reset_flow(tenant_a, client_for, user_in, sms_outbox):
    assert settings.ESKIZ_USE_MOCK is True  # never bill real SMS from tests
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)

    resp = client.post(RESET_REQUEST_URL, {"identifier": user.phone}, format="json")
    assert resp.status_code == 202
    assert len(sms_outbox) == 1

    code = _code_from(sms_outbox[0]["text"])
    resp = client.post(
        RESET_CONFIRM_URL,
        {"identifier": user.phone, "code": code, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 204

    assert (
        client.post(LOGIN_URL, {"username": user.username, "password": NEW_PASSWORD}, format="json")
    ).status_code == 200
    assert (
        client.post(LOGIN_URL, {"username": user.username, "password": PASSWORD}, format="json")
    ).status_code == 401


def test_password_reset_unknown_identifier_silent_202(tenant_a, client_for, sms_outbox):
    """Anti-enumeration: unknown identifiers get the same 202 and no SMS."""
    resp = client_for(tenant_a).post(RESET_REQUEST_URL, {"identifier": "+998905550001"}, format="json")
    assert resp.status_code == 202
    assert len(sms_outbox) == 0


def test_password_reset_wrong_code_400(tenant_a, client_for, user_in, sms_outbox):
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)
    client.post(RESET_REQUEST_URL, {"identifier": user.phone}, format="json")
    resp = client.post(
        RESET_CONFIRM_URL,
        {"identifier": user.phone, "code": "000000", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_password_reset_wrong_code_5x_invalidates(tenant_a, client_for, user_in, sms_outbox):
    """After OTP_MAX_ATTEMPTS wrong codes even the CORRECT code is rejected
    (the attempt cap bites — D1-LC regression for the committed increment)."""
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)
    client.post(RESET_REQUEST_URL, {"identifier": user.phone}, format="json")
    code = _code_from(sms_outbox[0]["text"])

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        resp = client.post(
            RESET_CONFIRM_URL,
            {"identifier": user.phone, "code": "000000", "new_password": NEW_PASSWORD},
            format="json",
        )
        assert resp.status_code == 400
    resp = client.post(
        RESET_CONFIRM_URL,
        {"identifier": user.phone, "code": code, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "throttled"


def test_reset_request_cooldown_429_with_retry_after(tenant_a, client_for, user_in, sms_outbox):
    user = _password_user(tenant_a, user_in)
    client = client_for(tenant_a)
    assert client.post(RESET_REQUEST_URL, {"identifier": user.phone}, format="json").status_code == 202
    resp = client.post(RESET_REQUEST_URL, {"identifier": user.phone}, format="json")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "throttled"
    assert "Retry-After" in resp.headers
    assert len(sms_outbox) == 1  # the throttled request sent nothing


def test_reset_request_ip_distinct_identifier_cap(tenant_a, client_for):
    """One IP probing many identifiers gets cut off — even for identifiers
    with no account (the cap runs before the existence check)."""
    cap = settings.OTP_IP_DISTINCT_IDENTIFIER_CAP
    client = client_for(tenant_a)
    for i in range(cap):
        resp = client.post(RESET_REQUEST_URL, {"identifier": f"+9989055500{i:02d}"}, format="json")
        assert resp.status_code == 202
    resp = client.post(RESET_REQUEST_URL, {"identifier": "+998905551999"}, format="json")
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Refresh rotation, reuse detection, tenant binding
# ---------------------------------------------------------------------------


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

    # Reuse revokes EVERYTHING — the rotated refresh is dead too (D1-LC-6).
    dead = client.post(REFRESH_URL, {"refresh": rotated.json()["refresh"]}, format="json")
    assert dead.status_code == 401


def test_cross_tenant_refresh_rejected(tenant_a, tenant_b, client_for, user_in):
    """BLOCKER regression: a refresh minted on tenant A presented to tenant B
    must 401 tenant_mismatch — never resolve a pk-colliding user in B."""
    from apps.auth.services import issue_token_pair

    user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        pair = issue_token_pair(user)

    resp = client_for(tenant_b).post(REFRESH_URL, {"refresh": pair["refresh"]}, format="json")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "tenant_mismatch"


def test_token_stale_after_role_change(tenant_a, user_in, as_user):
    user = user_in(tenant_a, roles=["teacher"])
    client = as_user(tenant_a, user)
    assert client.get(ME_URL).status_code == 200

    with schema_context(tenant_a.schema_name):
        from apps.org.tests.factories import BranchFactory
        from apps.users.models import RoleMembership

        RoleMembership.objects.create(user=user, branch=BranchFactory(), role="librarian")

    resp = client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_stale"


def test_logout_all_kills_access_and_refresh(tenant_a, client_for, user_in, as_user):
    from apps.auth.services import issue_token_pair

    user = user_in(tenant_a, roles=["teacher"])
    with schema_context(tenant_a.schema_name):
        pair = issue_token_pair(user)
    client = as_user(tenant_a, user)

    assert client.post(LOGOUT_ALL_URL).status_code == 204

    stale = client_for(tenant_a)
    stale.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")
    resp = stale.get(ME_URL)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_stale"
    assert (
        client_for(tenant_a).post(REFRESH_URL, {"refresh": pair["refresh"]}, format="json")
    ).status_code == 401


def test_throttle_survives_non_string_identifier(tenant_a, client_for):
    """Throttles run before validation — a JSON-int identifier must 400, not 500."""
    resp = client_for(tenant_a).post(RESET_REQUEST_URL, {"identifier": 12345}, format="json")
    assert resp.status_code in (400, 429)


# Keep cache state isolated when running this module alone (conftest clears too).
@pytest.fixture(autouse=True)
def _isolated_throttles():
    cache.clear()
    yield
    cache.clear()
