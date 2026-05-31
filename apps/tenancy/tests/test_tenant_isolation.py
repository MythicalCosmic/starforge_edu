"""The single most load-bearing invariant in the platform (TASKS.md §26 #1):

    A JWT minted inside tenant A must NOT grant access on tenant B.

Centers are isolated by Postgres schema. Because user primary keys collide
across schemas (every schema starts at id=1), a token that is merely "looked
up by user_id" on the wrong tenant would silently authenticate as a *different*
user there. The token must therefore be bound to its issuing tenant and
rejected everywhere else.
"""

from __future__ import annotations

from django.db import connection
from django.test import TransactionTestCase
from django_tenants.utils import schema_context
from rest_framework.test import APIClient

from apps.auth.services import issue_token_pair
from apps.tenancy.services import provision_center
from apps.users.models import User

PHONE_A = "+998900000001"
PHONE_B = "+998900000002"


class TenantIsolationTest(TransactionTestCase):
    def setUp(self):
        connection.set_schema_to_public()  # type: ignore[attr-defined]
        self.center_a = provision_center(name="Alpha", slug="alpha", primary_domain="alpha.test")
        self.center_b = provision_center(name="Beta", slug="beta", primary_domain="beta.test")
        with schema_context("alpha"):
            self.user_a = User.objects.create(phone=PHONE_A)
        with schema_context("beta"):
            self.user_b = User.objects.create(phone=PHONE_B)

    def tearDown(self):
        connection.set_schema_to_public()  # type: ignore[attr-defined]
        for center in (self.center_a, self.center_b):
            center.delete(force_drop=True)

    def _access_token(self, schema: str, user: User) -> str:
        with schema_context(schema):
            return issue_token_pair(user)["access"]

    def _me(self, client: APIClient, host: str, token: str):
        return client.get(
            "/api/v1/users/me/",
            HTTP_HOST=host,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_token_works_on_its_own_tenant(self):
        token = self._access_token("alpha", self.user_a)
        r = self._me(APIClient(), "alpha.test", token)
        assert r.status_code == 200, r.content
        assert r.json()["phone"] == PHONE_A

    def test_token_from_tenant_a_is_rejected_on_tenant_b(self):
        token_a = self._access_token("alpha", self.user_a)
        r = self._me(APIClient(), "beta.test", token_a)
        # Hard requirement: tenant A's identity must never surface in tenant B.
        if r.status_code == 200:
            assert r.json().get("phone") != PHONE_A, "TENANT A IDENTITY LEAKED INTO TENANT B"
        # And the token must be refused outright on the foreign tenant.
        assert r.status_code == 401, r.content
