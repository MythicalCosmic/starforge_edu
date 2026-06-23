"""A-1 money feature — the `discount` KIND of the Approvals engine.

A discount needs sign-off (anti-fraud DNA: no silently-applied price cuts). It is
a decision-only request: approving it materializes a standing finance.Discount for
the student, which billing then auto-applies as a negative invoice line. The
approval row is the permanent paper trail (who asked, who approved, why)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django_tenants.utils import schema_context

from apps.students.tests.factories import StudentProfileFactory
from core.permissions import Role

pytestmark = pytest.mark.django_db

REQ = "/api/v1/approvals/requests/"


def _student_id(tenant) -> int:
    with schema_context(tenant.schema_name):
        return StudentProfileFactory.create().id


def test_approving_discount_request_materializes_discount(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    director, director_user = as_role(Role.DIRECTOR)
    sid = _student_id(tenant_a)

    r = teacher.post(
        REQ,
        {
            "kind": "discount",
            "title": "Scholarship for top student",
            "amount_uzs": "999.00",  # ignored: a discount never disburses
            "payload": {"student_id": sid, "discount_type": "scholarship", "percent": "20"},
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    body = r.json()
    rid = body["id"]
    assert body["amount_uzs"] is None  # decision-only — amount dropped
    assert body["payload"]["percent"] == "20"  # normalized + stored as string

    ap = director.post(f"{REQ}{rid}/approve/", {"note": "earned it"}, format="json")
    assert ap.status_code == 200, ap.content
    assert ap.json()["status"] == "approved"
    discount_id = ap.json()["payload"]["discount_id"]
    assert discount_id  # audit link stamped back

    with schema_context(tenant_a.schema_name):
        from apps.finance.models import Discount

        d = Discount.objects.get(pk=discount_id)
        assert d.student_id == sid
        assert d.percent == Decimal("20")
        assert d.fixed_amount_uzs is None
        assert d.discount_type == "scholarship"
        assert d.approved_by_id == director_user.id
        assert d.is_active is True


def test_discount_request_fixed_amount(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    director, _ = as_role(Role.DIRECTOR)
    sid = _student_id(tenant_a)

    rid = teacher.post(
        REQ,
        {
            "kind": "discount",
            "title": "Hardship",
            "payload": {"student_id": sid, "fixed_amount_uzs": "150000"},
        },
        format="json",
    ).json()["id"]
    director.post(f"{REQ}{rid}/approve/", {}, format="json")

    with schema_context(tenant_a.schema_name):
        from apps.finance.models import Discount

        d = Discount.objects.get(student_id=sid)
        assert d.fixed_amount_uzs == Decimal("150000")
        assert d.percent is None
        assert d.discount_type == "manual"  # defaulted


def test_discount_request_requires_valid_student(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    r = teacher.post(
        REQ,
        {"kind": "discount", "title": "x", "payload": {"percent": "10"}},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "discount_student_required"


def test_discount_request_amount_is_xor(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    sid = _student_id(tenant_a)
    # both set -> rejected
    both = teacher.post(
        REQ,
        {
            "kind": "discount",
            "title": "x",
            "payload": {"student_id": sid, "percent": "10", "fixed_amount_uzs": "1000"},
        },
        format="json",
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "discount_amount_xor"
    # neither set -> also rejected
    neither = teacher.post(
        REQ, {"kind": "discount", "title": "x", "payload": {"student_id": sid}}, format="json"
    )
    assert neither.status_code == 400
    assert neither.json()["error"]["code"] == "discount_amount_xor"


def test_discount_percent_out_of_range(tenant_a, as_role):
    teacher, _ = as_role(Role.TEACHER)
    sid = _student_id(tenant_a)
    r = teacher.post(
        REQ,
        {"kind": "discount", "title": "x", "payload": {"student_id": sid, "percent": "150"}},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "discount_percent_range"
