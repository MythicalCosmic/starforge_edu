"""#12 — rule book: role-filtered rules, forced acknowledgment, version re-accept."""

from __future__ import annotations

import pytest

from core.permissions import Role

pytestmark = pytest.mark.django_db

RULES = "/api/v1/rulebook/rules/"


def _ids(rows):
    return {r["id"] for r in rows}


def test_rule_acknowledge_and_version_reaccept(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    teacher, _ = as_role(Role.TEACHER)

    made = director.post(
        RULES, {"title": "No phones in class", "body": "v1 text", "applies_to_roles": ["teacher"]}, format="json"
    )
    assert made.status_code == 201, made.content
    rid = made.json()["id"]

    # teacher sees it as pending / not acknowledged
    mine = teacher.get(f"{RULES}mine/").json()
    assert rid in _ids(mine)
    assert next(r for r in mine if r["id"] == rid)["acknowledged"] is False
    assert rid in _ids(teacher.get(f"{RULES}pending/").json())

    # teacher accepts -> no longer pending
    assert teacher.post(f"{RULES}{rid}/acknowledge/", {}, format="json").status_code == 200
    assert rid not in _ids(teacher.get(f"{RULES}pending/").json())

    # director edits the body -> version bumps -> teacher must re-accept
    director.patch(f"{RULES}{rid}/", {"body": "v2 text (updated)"}, format="json")
    assert rid in _ids(teacher.get(f"{RULES}pending/").json())


def test_rule_role_filter_and_permissions(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    teacher, _ = as_role(Role.TEACHER)
    cashier, _ = as_role(Role.CASHIER)

    rid = director.post(
        RULES, {"title": "Teacher rule", "body": "x", "applies_to_roles": ["teacher"]}, format="json"
    ).json()["id"]

    # cashier is not targeted -> not in their feed, and can't acknowledge it
    assert rid not in _ids(cashier.get(f"{RULES}mine/").json())
    assert cashier.post(f"{RULES}{rid}/acknowledge/", {}, format="json").status_code == 403

    # a teacher can't author rules (no compliance:write)
    assert teacher.post(RULES, {"title": "x", "body": "y"}, format="json").status_code == 403
