"""F17-1 — staff rewards: reward types + grants, with cash rewards routed through
the A-1 Approvals + Ledger engine (approve → disburse → ledger)."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

TYPES = "/api/v1/rewards/types/"
GRANTS = "/api/v1/rewards/grants/"
APPROVALS = "/api/v1/approvals/requests/"


def _rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body


def test_cash_reward_routes_through_a1_to_the_ledger(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    hod_client, _h = as_role(Role.HEAD_OF_DEPT)
    teacher_client, teacher = as_role(Role.TEACHER)
    cashier, _c = as_role(Role.CASHIER)
    with schema_context(tenant_a.schema_name):
        from apps.finance.models import PaymentMethod

        method_id = PaymentMethod.objects.create(name="Cash", slug="cash").id

    rt = director.post(
        TYPES,
        {"name": "Performance bonus", "is_cash": True, "default_amount_uzs": "500000.00"},
        format="json",
    )
    assert rt.status_code == 201, rt.content

    # HOD grants it (so the A-1 requester != the director who will approve — maker-checker)
    granted = hod_client.post(
        GRANTS,
        {"reward_type": rt.json()["id"], "recipient": teacher.id, "reason": "Great results"},
        format="json",
    )
    assert granted.status_code == 201, granted.content
    body = granted.json()
    assert body["amount_uzs"] == "500000.00"  # defaulted from the type
    assert body["approval_request"] is not None
    assert body["approval_status"] == "pending"
    req_id = body["approval_request"]

    # the recipient sees the reward on their wall
    assert any(r["id"] == body["id"] for r in _rows(teacher_client.get(f"{GRANTS}mine/").json()))

    # the money flows through A-1: approve -> disburse -> immutable ledger row
    assert director.post(f"{APPROVALS}{req_id}/approve/", {}, format="json").status_code == 200
    dis = cashier.post(f"{APPROVALS}{req_id}/disburse/", {"payment_method": method_id}, format="json")
    assert dis.status_code == 200
    assert dis.json()["status"] == "disbursed"
    entries = cashier.get("/api/v1/approvals/ledger/").json()["results"]
    reward_entry = next(e for e in entries if e["entry_type"] == "reward")
    assert reward_entry["amount_uzs"] == "500000.00"
    # the ledger payee is the RECIPIENT (not the HOD who granted/requested it)
    assert reward_entry["party_label"] == (teacher.get_full_name() or teacher.username)


def test_non_cash_reward_recorded_without_approval(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    _tc, teacher = as_role(Role.TEACHER)
    rt = director.post(TYPES, {"name": "Extra day off", "is_cash": False}, format="json").json()["id"]
    grant = director.post(GRANTS, {"reward_type": rt, "recipient": teacher.id}, format="json")
    assert grant.status_code == 201
    assert grant.json()["approval_request"] is None  # nothing to disburse
    assert grant.json()["amount_uzs"] is None


def test_cash_reward_requires_an_amount(tenant_a, as_role):
    hod_client, _h = as_role(Role.HEAD_OF_DEPT)
    _tc, teacher = as_role(Role.TEACHER)
    rt = hod_client.post(TYPES, {"name": "Bonus", "is_cash": True}, format="json").json()["id"]  # no default
    grant = hod_client.post(GRANTS, {"reward_type": rt, "recipient": teacher.id}, format="json")  # no amount
    assert grant.status_code == 400
    assert grant.json()["error"]["code"] == "amount_required"


def test_recipient_sees_only_their_own_rewards(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    _ac, alice = as_role(Role.TEACHER)
    bob_client, _b = as_role(Role.TEACHER)
    rt = director.post(TYPES, {"name": "Certificate", "is_cash": False}, format="json").json()["id"]
    director.post(GRANTS, {"reward_type": rt, "recipient": alice.id}, format="json")

    # bob (a teacher, rewards:read) sees none of alice's rewards, and can't list all
    assert _rows(bob_client.get(f"{GRANTS}mine/").json()) == []
    assert bob_client.get(GRANTS).status_code == 403  # listing all grants is rewards:write


def test_staff_cannot_define_types_or_grant(tenant_a, as_role):
    teacher_client, _t = as_role(Role.TEACHER)  # rewards:read only
    assert teacher_client.post(TYPES, {"name": "x", "is_cash": False}, format="json").status_code == 403
    assert teacher_client.post(GRANTS, {"reward_type": 1, "recipient": 1}, format="json").status_code == 403


def test_cannot_reward_a_non_staff_user(tenant_a, user_in, as_role):
    director, _ = as_role(Role.DIRECTOR)
    student_user = user_in(tenant_a, roles=[Role.STUDENT])
    rt = director.post(TYPES, {"name": "x", "is_cash": False}, format="json").json()["id"]
    # a student is not a valid reward recipient
    grant = director.post(GRANTS, {"reward_type": rt, "recipient": student_user.id}, format="json")
    assert grant.status_code == 400


# --------------------------------------------------------------------------- #
# review hardening
# --------------------------------------------------------------------------- #
def test_cannot_self_grant_a_reward(tenant_a, as_role):
    hod_client, hod = as_role(Role.HEAD_OF_DEPT)
    rt = hod_client.post(TYPES, {"name": "Day off", "is_cash": False}, format="json").json()["id"]
    r = hod_client.post(GRANTS, {"reward_type": rt, "recipient": hod.id}, format="json")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "self_grant"


def test_reward_type_cannot_be_deleted(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    rt = director.post(TYPES, {"name": "Permanent", "is_cash": False}, format="json").json()["id"]
    # no DELETE — types are retired via is_active, never removed (PROTECT + audit history)
    assert director.delete(f"{TYPES}{rt}/").status_code == 405


def test_inactive_reward_type_cannot_be_granted(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    _tc, teacher = as_role(Role.TEACHER)
    rt = director.post(TYPES, {"name": "Retired", "is_cash": False}, format="json").json()["id"]
    assert director.patch(f"{TYPES}{rt}/", {"is_active": False}, format="json").status_code == 200
    r = director.post(GRANTS, {"reward_type": rt, "recipient": teacher.id}, format="json")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "reward_type_inactive"


def test_cash_reward_zero_amount_rejected(tenant_a, as_role):
    hod_client, _h = as_role(Role.HEAD_OF_DEPT)
    _tc, teacher = as_role(Role.TEACHER)
    rt = hod_client.post(TYPES, {"name": "Z", "is_cash": True}, format="json").json()["id"]
    r = hod_client.post(
        GRANTS, {"reward_type": rt, "recipient": teacher.id, "amount_uzs": "0"}, format="json"
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "amount_required"


def test_non_manager_cannot_retrieve_anothers_grant(tenant_a, as_role):
    director, _ = as_role(Role.DIRECTOR)
    _ac, alice = as_role(Role.TEACHER)
    bob_client, _b = as_role(Role.TEACHER)
    rt = director.post(TYPES, {"name": "Cert", "is_cash": False}, format="json").json()["id"]
    gid = director.post(GRANTS, {"reward_type": rt, "recipient": alice.id}, format="json").json()["id"]
    # bob (a teacher) can't fetch alice's reward by id — it's not in his scope
    assert bob_client.get(f"{GRANTS}{gid}/").status_code == 404
