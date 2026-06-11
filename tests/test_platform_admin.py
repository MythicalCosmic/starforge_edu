"""Public-schema platform admin + platform API (D1-LB-1, TD-3).

The platform surface (apex /admin/ and /api/v1/platform/) is served by
PUBLIC_SCHEMA_URLCONF, which django-tenants selects only when the request's
hostname resolves to a tenant whose schema_name is "public". The fixture
below creates that standard public-tenant row for the test client's
"testserver" host (no schema is created — "public" already exists).
"""

import pytest
from django.test import Client
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PASSWORD = "s3cret-Platform!"

# public_tenant fixture lives in the root conftest.py (promoted so any suite
# can hit the platform surface on the "testserver" host).


@pytest.fixture
def platform_admin(public_tenant):
    from apps.users.models import User

    # Public schema is the default connection schema for the test transaction.
    return User.objects.create_superuser(username="padmin", password=PASSWORD)


def test_public_schema_platform_admin_login(platform_admin):
    client = Client()  # host "testserver" → public schema URLConf
    resp = client.post(
        "/admin/login/",
        {"username": "padmin", "password": PASSWORD, "next": "/admin/"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/admin/"
    assert resp.wsgi_request.user.is_authenticated


def test_platform_centers_api_staff_200(platform_admin, tenant_a):
    client = APIClient()
    client.force_authenticate(platform_admin)
    resp = client.get("/api/v1/platform/centers/")
    assert resp.status_code == 200
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) else data
    assert tenant_a.slug in {row["slug"] for row in rows}


def test_platform_centers_api_non_staff_403(public_tenant, tenant_a, user_in):
    user = user_in(tenant_a)  # plain tenant user, is_staff=False
    client = APIClient()
    client.force_authenticate(user)
    assert client.get("/api/v1/platform/centers/").status_code == 403


def test_set_primary_non_numeric_domain_id_404(platform_admin, tenant_a):
    """Routing regression: (?P<domain_id>\\d+) must reject non-numeric ids at
    the resolver (404) instead of int() exploding into a 500."""
    client = APIClient()
    client.force_authenticate(platform_admin)
    resp = client.post(f"/api/v1/platform/centers/{tenant_a.pk}/domains/abc/set-primary/")
    assert resp.status_code == 404
