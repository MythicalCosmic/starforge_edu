"""Auth flow tests: OTP request/verify, throttling, lockout, JWT lifecycle.

Runs inside a real tenant schema via django-tenants' TenantTestCase, so these
exercise the same code path a request on a tenant subdomain would hit.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework import status

from apps.auth import services
from apps.users.models import OTP, User

PHONE = "+998901234567"
EMAIL = "learner@example.com"
FIXED_CODE = "123456"


class AuthFlowTest(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Test Center"
        tenant.slug = "test"

    def setUp(self):
        self.client = TenantClient(self.tenant)
        cache.clear()  # throttle counters live in the cache

    def _post(self, path, payload):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json")

    # -- happy path ---------------------------------------------------------

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_otp_request_then_verify_returns_token_pair(self, _gen):
        r = self._post("/api/v1/auth/otp/request/", {"identifier": PHONE})
        assert r.status_code == status.HTTP_202_ACCEPTED, r.content
        assert OTP.objects.filter(identifier=PHONE, consumed_at__isnull=True).exists()

        r2 = self._post("/api/v1/auth/otp/verify/", {"identifier": PHONE, "code": FIXED_CODE})
        assert r2.status_code == status.HTTP_200_OK, r2.content
        body = r2.json()
        assert body["access"] and body["refresh"]
        assert User.objects.filter(phone=PHONE).exists()
        # OTP is single-use.
        assert OTP.objects.get(identifier=PHONE).consumed_at is not None

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_login_with_email_identifier(self, _gen):
        self._post("/api/v1/auth/otp/request/", {"identifier": EMAIL})
        r = self._post("/api/v1/auth/otp/verify/", {"identifier": EMAIL, "code": FIXED_CODE})
        assert r.status_code == status.HTTP_200_OK, r.content
        assert User.objects.filter(email=EMAIL).exists()

    # -- abuse resistance ---------------------------------------------------

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_otp_phone_throttle_blocks_fourth_request_in_a_minute(self, _gen):
        for _ in range(3):
            assert self._post("/api/v1/auth/otp/request/", {"identifier": PHONE}).status_code == 202
        r = self._post("/api/v1/auth/otp/request/", {"identifier": PHONE})
        assert r.status_code == status.HTTP_429_TOO_MANY_REQUESTS, r.content

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_wrong_code_attempt_limit_locks_the_otp(self, _gen):
        """OTP_MAX_ATTEMPTS wrong tries exhaust the code at the service layer.

        NB: this invariant is tested against ``services.verify_otp`` directly,
        not the HTTP endpoint, because OTPPhoneThrottle (3/min) trips before the
        5-attempt limit is reachable over HTTP. See test_verify_throttle below.
        """
        from core.exceptions import ThrottledException, ValidationException

        services.send_otp(identifier=PHONE)
        for _ in range(settings.OTP_MAX_ATTEMPTS):
            with self.assertRaises(ValidationException):
                services.verify_otp(identifier=PHONE, code="000000")
        # The OTP is now spent — even the correct code is rejected.
        with self.assertRaises((ThrottledException, ValidationException)):
            services.verify_otp(identifier=PHONE, code=FIXED_CODE)

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_verify_endpoint_is_throttled(self, _gen):
        """The verify endpoint blocks the 4th attempt/min (OTPPhoneThrottle=3)."""
        self._post("/api/v1/auth/otp/request/", {"identifier": PHONE})
        statuses = [
            self._post("/api/v1/auth/otp/verify/", {"identifier": PHONE, "code": "000000"}).status_code
            for _ in range(4)
        ]
        assert statuses[-1] == status.HTTP_429_TOO_MANY_REQUESTS, statuses

    def test_verify_without_request_fails(self):
        r = self._post("/api/v1/auth/otp/verify/", {"identifier": PHONE, "code": FIXED_CODE})
        assert r.status_code == status.HTTP_400_BAD_REQUEST, r.content

    # -- JWT lifecycle ------------------------------------------------------

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_refresh_rotates_and_blacklists_old_token(self, _gen):
        self._post("/api/v1/auth/otp/request/", {"identifier": PHONE})
        pair = self._post("/api/v1/auth/otp/verify/", {"identifier": PHONE, "code": FIXED_CODE}).json()

        first_refresh = pair["refresh"]
        rotated = self._post("/api/v1/auth/refresh/", {"refresh": first_refresh})
        assert rotated.status_code == status.HTTP_200_OK, rotated.content
        assert rotated.json()["refresh"] != first_refresh  # ROTATE_REFRESH_TOKENS

        # The old refresh is blacklisted after rotation.
        reused = self._post("/api/v1/auth/refresh/", {"refresh": first_refresh})
        assert reused.status_code == status.HTTP_401_UNAUTHORIZED, reused.content

    @patch("apps.auth.services.generate_otp", return_value=FIXED_CODE)
    def test_logout_blacklists_refresh(self, _gen):
        self._post("/api/v1/auth/otp/request/", {"identifier": PHONE})
        pair = self._post("/api/v1/auth/otp/verify/", {"identifier": PHONE, "code": FIXED_CODE}).json()
        out = self._post("/api/v1/auth/logout/", {"refresh": pair["refresh"]})
        assert out.status_code == status.HTTP_200_OK, out.content
        after = self._post("/api/v1/auth/refresh/", {"refresh": pair["refresh"]})
        assert after.status_code == status.HTTP_401_UNAUTHORIZED, after.content
