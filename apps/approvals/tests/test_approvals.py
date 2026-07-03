"""A-1 — the Approvals + Ledger engine: request -> approve -> disburse -> ledger,
with scoping, decision-only kinds, and permission gating."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from core.permissions import Role

pytestmark = pytest.mark.django_db

REQ = "/api/v1/approvals/requests/"
LEDGER = "/api/v1/approvals/ledger/"


def _payment_method(tenant) -> int:
    with schema_context(tenant.schema_name):
        from apps.finance.models import PaymentMethod

        return PaymentMethod.objects.create(name="Cash", slug="cash").id


def test_request_approve_disburse_writes_ledger(tenant_a, as_role):
    teacher, teacher_user = as_role(Role.TEACHER)
    director, _ = as_role(Role.DIRECTOR)
    cashier, _ = as_role(Role.CASHIER)
    method_id = _payment_method(tenant_a)

    # a loan kind carries a borrower in its payload (F21-1)
    r = teacher.post(
        REQ,
        {
            "kind": "loan",
            "title": "Salary advance",
            "amount_uzs": "500000.00",
            "payload": {"borrower_id": teacher_user.id},
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    rid = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "pending"

    # cannot disburse before approval
    early = cashier.post(f"{REQ}{rid}/disburse/", {"payment_method": method_id}, format="json")
    assert early.status_code == 422

    # a teacher cannot approve (no approvals:approve)
    assert teacher.post(f"{REQ}{rid}/approve/", {}, format="json").status_code == 403

    ap = director.post(f"{REQ}{rid}/approve/", {"note": "ok"}, format="json")
    assert ap.status_code == 200
    assert ap.json()["data"]["status"] == "approved"

    dis = cashier.post(f"{REQ}{rid}/disburse/", {"payment_method": method_id}, format="json")
    assert dis.status_code == 200
    assert dis.json()["data"]["status"] == "disbursed"
    assert dis.json()["data"]["ledger_entry"] is not None

    entries = cashier.get(LEDGER).json()["data"]
    assert any(
        e["entry_type"] == "loan" and e["direction"] == "out" and e["amount_uzs"] == "500000.00"
        for e in entries
    )


def test_requester_sees_own_handler_sees_all(tenant_a, as_role, user_in, as_user):
    teacher, _ = as_role(Role.TEACHER)
    other = as_user(tenant_a, user_in(tenant_a, roles=[Role.TEACHER]))
    teacher.post(REQ, {"kind": "expense", "title": "Mine", "amount_uzs": "100.00"}, format="json")

    assert teacher.get(REQ).json()["pagination"]["total"] == 1  # requester sees own
    assert other.get(REQ).json()["pagination"]["total"] == 0  # another requester sees none of it


def test_create_title_with_nul_byte_is_clean_400_not_db_error(tenant_a, as_role):
    """title must reject NUL like every other string field (psycopg cannot store
    it) — a clean field-scoped 400, never a DB-bind error."""
    teacher, _ = as_role(Role.TEACHER)
    r = teacher.post(REQ, {"kind": "other", "title": "a\x00b", "amount_uzs": "10.00"}, format="json")
    assert r.status_code == 400, r.content
    assert r.json()["code"] == "validation_error"
    assert "title" in r.json()["errors"]


def test_create_accepts_long_description(tenant_a, as_role):
    """description is an unbounded TextField (old serializer had no max_length);
    a long body must still create (201), not 400."""
    teacher, _ = as_role(Role.TEACHER)
    r = teacher.post(
        REQ,
        {"kind": "other", "title": "x", "amount_uzs": "10.00", "description": "d" * 5000},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["data"]["description"] == "d" * 5000


def test_decision_only_request_cannot_disburse(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    director, _ = as_role(Role.DIRECTOR)
    cashier, _ = as_role(Role.CASHIER)
    method_id = _payment_method(tenant_a)

    rid = teacher.post(REQ, {"kind": "other", "title": "Note only"}, format="json").json()["data"]["id"]
    director.post(f"{REQ}{rid}/approve/", {}, format="json")
    # an amount-less request approves fine but has nothing to disburse
    assert (
        cashier.post(f"{REQ}{rid}/disburse/", {"payment_method": method_id}, format="json").status_code == 422
    )


def test_student_cannot_request(tenant_a, as_role):
    student, _ = as_role(Role.STUDENT)
    resp = student.post(REQ, {"kind": "expense", "title": "x", "amount_uzs": "1.00"}, format="json")
    assert resp.status_code == 403


def test_approval_notifies_requester_and_disburser(tenant_a, as_role):
    teacher, teacher_user = as_role(Role.TEACHER)
    director, _ = as_role(Role.DIRECTOR)
    cashier, _ = as_role(Role.CASHIER)

    rid = teacher.post(
        REQ,
        {
            "kind": "loan",
            "title": "Advance",
            "amount_uzs": "100000.00",
            "payload": {"borrower_id": teacher_user.id},
        },
        format="json",
    ).json()["data"]["id"]
    director.post(f"{REQ}{rid}/approve/", {}, format="json")

    teacher_events = {n["event_type"] for n in teacher.get("/api/v1/notifications/").json()["results"]}
    assert "approval.approved" in teacher_events  # requester told the outcome

    cashier_events = {n["event_type"] for n in cashier.get("/api/v1/notifications/").json()["results"]}
    assert "approval.awaiting_disbursement" in cashier_events  # cashier told to ready the money
