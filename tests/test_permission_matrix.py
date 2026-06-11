"""Parameterized permission matrix (TASKS §3, §26 item 8).

Declarative MATRIX_CASES — Day-2+ lanes append one tuple per case. Drives the
fail-closed (TD-4) per-action (TD-5) permission system against real endpoints.
"""

import pytest

from core.permissions import Role

pytestmark = pytest.mark.django_db

# (role, http_method, url, allowed?) — `allowed=True` expects 200, else 403.
MATRIX_CASES = [
    # users directory (users:read)
    (Role.DIRECTOR, "get", "/api/v1/users/", True),
    (Role.IT, "get", "/api/v1/users/", True),
    (Role.STUDENT, "get", "/api/v1/users/", False),
    # org branches (org:read / org:write)
    (Role.DIRECTOR, "get", "/api/v1/org/branches/", True),
    (Role.IT, "get", "/api/v1/org/branches/", True),
    (Role.TEACHER, "get", "/api/v1/org/branches/", False),
    (Role.TEACHER, "post", "/api/v1/org/branches/", False),
    # org settings singleton (org:read)
    (Role.DIRECTOR, "get", "/api/v1/org/settings/", True),
    (Role.TEACHER, "get", "/api/v1/org/settings/", False),
    # students (students:read)
    (Role.DIRECTOR, "get", "/api/v1/students/", True),
    (Role.REGISTRAR, "get", "/api/v1/students/", True),
    (Role.TEACHER, "get", "/api/v1/students/", True),
    (Role.CASHIER, "get", "/api/v1/students/", False),
    # cohorts (cohorts:read)
    (Role.DIRECTOR, "get", "/api/v1/cohorts/", True),
    (Role.TEACHER, "get", "/api/v1/cohorts/", True),
    (Role.CASHIER, "get", "/api/v1/cohorts/", False),
    # teachers (teachers:read)
    (Role.DIRECTOR, "get", "/api/v1/teachers/", True),
    (Role.REGISTRAR, "get", "/api/v1/teachers/", True),
    (Role.STUDENT, "get", "/api/v1/teachers/", False),
    # parents (parents:read)
    (Role.DIRECTOR, "get", "/api/v1/parents/", True),
    (Role.REGISTRAR, "get", "/api/v1/parents/", True),
    (Role.TEACHER, "get", "/api/v1/parents/", False),
]


@pytest.mark.parametrize(("role", "method", "url", "allowed"), MATRIX_CASES)
def test_permission_matrix(as_role, role, method, url, allowed):
    client, _ = as_role(role)
    resp = getattr(client, method)(url)
    if allowed:
        assert resp.status_code == 200, f"{role} {method} {url} -> {resp.status_code}"
    else:
        assert resp.status_code == 403, f"{role} {method} {url} -> {resp.status_code}"
        assert resp.json()["error"]["code"] == "forbidden"


def test_unmapped_action_is_fail_closed(as_role):
    """A role with no matching matrix entry is denied (TD-4)."""
    client, _ = as_role(Role.SECURITY)
    assert client.get("/api/v1/parents/").status_code == 403
