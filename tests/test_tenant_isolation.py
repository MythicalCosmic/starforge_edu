"""THE tenant-isolation test (TASKS §26 item 1).

The load-bearing invariant: a JWT minted in tenant A must 401 `tenant_mismatch`
on tenant B's host (TD-1). Written before TD-1 landed, now green.
"""

import pytest
from django_tenants.utils import schema_context

pytestmark = pytest.mark.django_db

URL = "/api/v1/users/me/"


def test_cross_tenant_token_rejected(tenant_a, tenant_b, user_in, client_for):
    from apps.auth.services import issue_token_pair

    user = user_in(tenant_a, roles=["director"])
    with schema_context(tenant_a.schema_name):
        access = issue_token_pair(user)["access"]

    client_b = client_for(tenant_b)
    client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = client_b.get(URL)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "tenant_mismatch"


def test_token_valid_on_own_tenant(tenant_a, user_in, as_user):
    user = user_in(tenant_a, roles=["director"])
    resp = as_user(tenant_a, user).get(URL)
    assert resp.status_code == 200
    assert resp.json()["id"] == user.id


def test_anonymous_rejected(tenant_a, client_for):
    assert client_for(tenant_a).get(URL).status_code == 401
