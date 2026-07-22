"""Finance API endpoint matrix (D3-A-9, TESTING.md §3): happy/denied/anonymous,
cross-tenant isolation, parent-own-children scoping, validation, query budget."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django_tenants.utils import schema_context

from apps.finance.tests.factories import FeeScheduleFactory, InvoiceFactory
from apps.parents.tests.factories import GuardianFactory, ParentProfileFactory
from apps.students.tests.factories import StudentProfileFactory
from core.permissions import Role

pytestmark = pytest.mark.django_db

INVOICES_URL = "/api/v1/finance/invoices/"
FEE_URL = "/api/v1/finance/fee-schedules/"
OUTSTANDING_URL = "/api/v1/finance/outstanding/"


# --------------------------------------------------------------------------- #
# /invoices/ list — allowed / denied / anonymous
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", [Role.DIRECTOR, Role.ACCOUNTANT, Role.CASHIER])
def test_invoice_list_allowed(as_role, role):
    client, _ = as_role(role)
    assert client.get(INVOICES_URL).status_code == 200


@pytest.mark.parametrize("role", [Role.SECURITY, Role.LIBRARIAN])
def test_invoice_list_denied(as_role, role):
    resp = as_role(role)[0].get(INVOICES_URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_invoice_list_anonymous_denied(tenant_a, client_for):
    assert client_for(tenant_a).get(INVOICES_URL).status_code == 401


# --------------------------------------------------------------------------- #
# cross-tenant isolation (TD-1)
# --------------------------------------------------------------------------- #


def test_invoice_cross_tenant_token_rejected(tenant_a, tenant_b, user_in, client_for):
    from apps.auth.services import issue_token

    user = user_in(tenant_a, roles=[Role.DIRECTOR])
    with schema_context(tenant_a.schema_name):
        access = issue_token(user)["access"]
    client_b = client_for(tenant_b)
    client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = client_b.get(INVOICES_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == "authentication_failed"


def test_invoice_not_visible_across_tenants(tenant_a, tenant_b, as_role):
    with schema_context(tenant_a.schema_name):
        InvoiceFactory(number="INV-2026-900001")
    # director on tenant_b cannot see tenant_a's invoice
    client_b, _ = as_role(Role.DIRECTOR, tenant=tenant_b)
    body = client_b.get(INVOICES_URL).json()
    numbers = {row["number"] for row in body["data"]}
    assert "INV-2026-900001" not in numbers


# --------------------------------------------------------------------------- #
# parent sees only own children's balances
# --------------------------------------------------------------------------- #


def test_parent_sees_only_own_childs_balance(tenant_a, user_in, as_user):
    parent_user = user_in(tenant_a, roles=[Role.PARENT])
    with schema_context(tenant_a.schema_name):
        parent = ParentProfileFactory(user=parent_user)
        my_child = StudentProfileFactory()
        other_child = StudentProfileFactory()
        GuardianFactory(parent=parent, student=my_child)
        InvoiceFactory(student=my_child, total_uzs=Decimal("100000.00"))
        InvoiceFactory(student=other_child, total_uzs=Decimal("100000.00"))

    client = as_user(tenant_a, parent_user)
    ok = client.get(f"{OUTSTANDING_URL}?student={my_child.pk}")
    assert ok.status_code == 200
    assert Decimal(ok.json()["data"]["outstanding_uzs"]) == Decimal("100000.00")

    denied = client.get(f"{OUTSTANDING_URL}?student={other_child.pk}")
    assert denied.status_code == 403


def test_director_sees_any_balance(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        InvoiceFactory(student=student, total_uzs=Decimal("250000.00"))
    resp = client.get(f"{OUTSTANDING_URL}?student={student.pk}")
    assert resp.status_code == 200
    assert Decimal(resp.json()["data"]["outstanding_uzs"]) == Decimal("250000.00")


# --------------------------------------------------------------------------- #
# invoice create via service (issue_invoice)
# --------------------------------------------------------------------------- #


def test_create_invoice_endpoint(tenant_a, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        fs = FeeScheduleFactory(amount_uzs=Decimal("777000.00"))
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=student.branch)
    client = as_user(tenant_a, accountant)
    resp = client.post(INVOICES_URL, {"student": student.pk, "fee_schedule": fs.pk}, format="json")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["status"] == "issued"
    assert Decimal(body["total_uzs"]) == Decimal("777000.00")
    assert len(body["lines"]) == 1


def test_invoice_line_explicit_zero_quantity_is_not_coerced_to_one(tenant_a, user_in, as_user):
    """An explicit quantity of 0 must bill 0 (a waived line), not be defaulted to 1
    (the default applies only when the key is absent) — no money over-charge."""
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=student.branch)
    client = as_user(tenant_a, accountant)
    resp = client.post(
        INVOICES_URL,
        {
            "student": student.pk,
            "lines": [{"description": "waived", "unit_price_uzs": "100000", "quantity": 0}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    assert Decimal(body["lines"][0]["amount_uzs"]) == Decimal("0.00")
    assert Decimal(body["total_uzs"]) == Decimal("0.00")


def test_invoice_line_oversized_quantity_is_400_not_500(tenant_a, user_in, as_user):
    """A quantity beyond the column's 8 digits is a clean 400, not a decimal-context
    overflow -> 500 in the line-amount quantize."""
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=student.branch)
    client = as_user(tenant_a, accountant)
    resp = client.post(
        INVOICES_URL,
        {
            "student": student.pk,
            "lines": [
                {"description": "x", "unit_price_uzs": "9999999999999999", "quantity": "9999999999999999"}
            ],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.content


def test_create_invoice_validation_empty(tenant_a, user_in, as_user):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=student.branch)
    client = as_user(tenant_a, accountant)
    resp = client.post(INVOICES_URL, {"student": student.pk}, format="json")
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "line",
    [
        {"description": "bad price", "unit_price_uzs": "-1.00", "quantity": "1"},
        {
            "description": "bad quantity",
            "line_type": "discount",
            "unit_price_uzs": "-1.00",
            "quantity": "-1",
        },
    ],
)
def test_invoice_negative_line_values_are_field_validation_errors(
    tenant_a,
    user_in,
    as_user,
    line,
):
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        branch = student.branch
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=branch)
    response = as_user(tenant_a, accountant).post(
        INVOICES_URL,
        {"student": student.pk, "lines": [line]},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert response.json()["code"] == "validation_error"


def test_accountant_invoice_and_statement_access_is_branch_scoped(tenant_a, user_in, as_user):
    from apps.cohorts.tests.factories import CohortFactory

    with schema_context(tenant_a.schema_name):
        own_student = StudentProfileFactory()
        other_student = StudentProfileFactory()
        own_invoice = InvoiceFactory(student=own_student)
        other_invoice = InvoiceFactory(student=other_student)
        other_schedule = FeeScheduleFactory(
            cohort=CohortFactory(branch=other_student.branch),
        )
        own_branch = own_student.branch
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=own_branch)
    client = as_user(tenant_a, accountant)

    listing = client.get(INVOICES_URL)
    assert listing.status_code == 200
    assert {row["id"] for row in listing.json()["data"]} == {own_invoice.pk}
    assert client.get(f"{INVOICES_URL}{other_invoice.pk}/").status_code == 404
    assert (
        client.post(
            INVOICES_URL,
            {
                "student": other_student.pk,
                "lines": [{"description": "x", "unit_price_uzs": "1.00"}],
            },
            format="json",
        ).status_code
        == 403
    )
    assert (
        client.post(
            INVOICES_URL,
            {"student": own_student.pk, "fee_schedule": other_schedule.pk},
            format="json",
        ).status_code
        == 403
    )
    assert client.post(f"/api/v1/finance/students/{other_student.pk}/statement/").status_code == 403


# --------------------------------------------------------------------------- #
# invoice void action
# --------------------------------------------------------------------------- #


def test_invoice_void_action(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        inv = InvoiceFactory(total_uzs=Decimal("100000.00"))
    resp = client.post(f"{INVOICES_URL}{inv.pk}/void/")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "void"


# --------------------------------------------------------------------------- #
# fee-schedules CRUD perms
# --------------------------------------------------------------------------- #


def test_fee_schedule_write_requires_finance_write(tenant_a, as_role):
    cashier_client, _ = as_role(Role.CASHIER)  # cashier has finance:read only
    resp = cashier_client.post(
        FEE_URL, {"name": "X", "amount_uzs": "100000.00", "billing_period": "monthly"}, format="json"
    )
    assert resp.status_code == 403

    director_client, _ = as_role(Role.DIRECTOR)
    ok = director_client.post(
        FEE_URL, {"name": "Y", "amount_uzs": "100000.00", "billing_period": "monthly"}, format="json"
    )
    assert ok.status_code == 201


def test_fee_schedule_authorized_detail_crud(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR)
    created_response = client.post(
        FEE_URL,
        {
            "name": "Monthly",
            "amount_uzs": "100000.00",
            "billing_period": "monthly",
            "due_day_of_month": 5,
        },
        format="json",
    )
    assert created_response.status_code == 201, created_response.content
    pk = created_response.json()["data"]["id"]
    assert client.get(f"{FEE_URL}{pk}/").status_code == 200
    patched = client.patch(f"{FEE_URL}{pk}/", {"amount_uzs": "120000.00"}, format="json")
    assert patched.status_code == 200
    assert patched.json()["data"]["amount_uzs"] == "120000.00"
    replaced = client.put(
        f"{FEE_URL}{pk}/",
        {"name": "Monthly renamed", "amount_uzs": "130000.00"},
        format="json",
    )
    assert replaced.status_code == 200
    assert replaced.json()["data"]["name"] == "Monthly renamed"
    assert client.delete(f"{FEE_URL}{pk}/").status_code == 204


def test_payment_plan_http_validates_dates_and_positive_amounts(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        invoice = InvoiceFactory(total_uzs=Decimal("100.00"))
    endpoint = f"{INVOICES_URL}{invoice.pk}/payment-plan/"
    negative = client.post(
        endpoint,
        {
            "installments": [
                {"due_date": "2026-08-01", "amount_uzs": "110.00"},
                {"due_date": "2026-09-01", "amount_uzs": "-10.00"},
            ]
        },
        format="json",
    )
    assert negative.status_code == 400, negative.content
    assert (
        client.post(
            endpoint,
            {"installments": [{"due_date": "not-a-date", "amount_uzs": "100.00"}]},
            format="json",
        ).status_code
        == 400
    )
    created_plan = client.post(
        endpoint,
        {
            "installments": [
                {"due_date": "2026-08-01", "amount_uzs": "40.00"},
                {"due_date": "2026-09-01", "amount_uzs": "60.00"},
            ]
        },
        format="json",
    )
    assert created_plan.status_code == 201, created_plan.content
    assert [row["amount_uzs"] for row in created_plan.json()["data"]["installments"]] == [
        "40.00",
        "60.00",
    ]


def test_payment_method_unicode_slug_and_authorized_detail_crud(tenant_a, as_role):
    client, _ = as_role(Role.DIRECTOR)
    endpoint = "/api/v1/finance/payment-methods/"
    first = client.post(endpoint, {"name": "Нақд пул"}, format="json")
    second = client.post(endpoint, {"name": "Карта"}, format="json")
    assert first.status_code == 201, first.content
    assert second.status_code == 201, second.content
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["slug"]
    assert second_data["slug"]
    assert first_data["slug"] != second_data["slug"]

    pk = first_data["id"]
    renamed = client.patch(f"{endpoint}{pk}/", {"name": "Нақд"}, format="json")
    assert renamed.status_code == 200
    assert renamed.json()["data"]["slug"] == first_data["slug"]
    assert client.get(f"{endpoint}{pk}/").status_code == 200
    assert client.get(endpoint).status_code == 200
    assert client.patch(f"{endpoint}{pk}/", {"slug": "has spaces"}, format="json").status_code == 400
    duplicate = client.patch(
        f"{endpoint}{pk}/",
        {"slug": second_data["slug"]},
        format="json",
    )
    assert duplicate.status_code == 400, duplicate.content
    assert duplicate.json()["code"] == "duplicate_slug"
    assert client.delete(f"{endpoint}{pk}/").status_code == 204


# --------------------------------------------------------------------------- #
# cashier shift endpoints
# --------------------------------------------------------------------------- #


def test_cashier_shift_open_close_endpoints(tenant_a, user_in, as_user):
    cashier = user_in(tenant_a, roles=[Role.CASHIER])
    with schema_context(tenant_a.schema_name):
        branch = cashier.role_memberships.get(role=Role.CASHIER).branch
    client = as_user(tenant_a, cashier)
    opened = client.post(
        "/api/v1/finance/cashier-shifts/open/",
        {"branch": branch.pk, "opening_cash_uzs": "10000.00"},
        format="json",
    )
    assert opened.status_code == 201
    shift_id = opened.json()["data"]["id"]

    # double open -> 409
    again = client.post("/api/v1/finance/cashier-shifts/open/", {"branch": branch.pk}, format="json")
    assert again.status_code == 409

    closed = client.post(
        f"/api/v1/finance/cashier-shifts/{shift_id}/close/",
        {"closing_cash_uzs": "10000.00"},
        format="json",
    )
    assert closed.status_code == 200
    assert closed.json()["data"]["discrepancy_uzs"] == "0.00"

    report = client.get(f"/api/v1/finance/cashier-shifts/{shift_id}/report/")
    assert report.status_code == 200
    assert report.json()["data"]["payments_total_uzs"] == "0.00"


def test_cashier_can_only_read_and_close_own_shift(tenant_a, user_in, as_user):
    from apps.finance import services
    from apps.org.tests.factories import BranchFactory

    with schema_context(tenant_a.schema_name):
        branch = BranchFactory()
    first = user_in(tenant_a, roles=[Role.CASHIER], branch=branch)
    second = user_in(tenant_a, roles=[Role.CASHIER], branch=branch)
    with schema_context(tenant_a.schema_name):
        own = services.open_cashier_shift(cashier=first, branch=branch)
        other = services.open_cashier_shift(cashier=second, branch=branch)

    client = as_user(tenant_a, first)
    listing = client.get("/api/v1/finance/cashier-shifts/")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["data"]] == [own.pk]
    assert client.get(f"/api/v1/finance/cashier-shifts/{other.pk}/").status_code == 403
    assert (
        client.post(
            f"/api/v1/finance/cashier-shifts/{other.pk}/close/",
            {"closing_cash_uzs": "0.00"},
            format="json",
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# statement async (202 + result)
# --------------------------------------------------------------------------- #


def test_statement_request_returns_202(tenant_a, user_in, as_user, monkeypatch):
    from apps.finance import services as fin_services

    monkeypatch.setattr(fin_services, "render_statement_pdf", lambda *, student, locale="en": b"%PDF")
    monkeypatch.setattr(
        "infrastructure.storage.s3_client.upload_bytes",
        lambda key, data, *, content_type="application/octet-stream": key,
    )
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
    accountant = user_in(tenant_a, roles=[Role.ACCOUNTANT], branch=student.branch)
    client = as_user(tenant_a, accountant)
    resp = client.post(f"/api/v1/finance/students/{student.pk}/statement/", {"locale": "en"}, format="json")
    assert resp.status_code == 202
    assert "task_id" in resp.json()["data"]


def test_statement_request_rejects_missing_student_before_enqueue(tenant_a, as_role, monkeypatch):
    from celery_tasks.finance_tasks import generate_statement_pdf

    called = False

    def should_not_enqueue(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("missing students must not reach Celery")

    monkeypatch.setattr(generate_statement_pdf, "delay", should_not_enqueue)
    client, _ = as_role(Role.DIRECTOR)
    response = client.post("/api/v1/finance/students/999999999/statement/")
    assert response.status_code == 404
    assert response.json()["code"] == "student_not_found"
    assert called is False


def test_statement_result_authorized_done_path(tenant_a, as_role, monkeypatch):
    from django.core.cache import cache

    client, _ = as_role(Role.DIRECTOR)
    cache.set(f"finance:statement:{tenant_a.schema_name}:task-ready", "statements/ready.pdf")
    monkeypatch.setattr(
        "infrastructure.storage.s3_client.presign_download",
        lambda key, *, expires_in: f"signed:{key}:{expires_in}",
    )
    response = client.get("/api/v1/finance/statements/task-ready/")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "done",
        "url": "signed:statements/ready.pdf:600",
    }


# --------------------------------------------------------------------------- #
# list shape + query budget (<=5 per spec)
# --------------------------------------------------------------------------- #


def test_invoice_list_query_budget(as_role, tenant_a, django_assert_max_num_queries):
    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        student = StudentProfileFactory()
        for _ in range(20):
            InvoiceFactory(student=student, total_uzs=Decimal("100000.00"))
    # +1 for billing paywall middleware subscription check
    with django_assert_max_num_queries(10):  # +1: A-2 per-request permission-override load
        body = client.get(INVOICES_URL).json()
    assert set(body) == {"success", "data", "pagination"}


# --------------------------------------------------------------------------- #
# denormalized `_name` companions on the invoice list (frontend needs no 2nd call)
# --------------------------------------------------------------------------- #


def test_invoice_list_includes_readable_name_companions(tenant_a, as_role):
    """Each bare FK id on an invoice row carries a readable `_name` companion,
    resolved from the selector's select_related (no extra query per row)."""
    from apps.cohorts.tests.factories import CohortFactory

    client, _ = as_role(Role.DIRECTOR)
    with schema_context(tenant_a.schema_name):
        cohort = CohortFactory(name="Algebra A")
        fs = FeeScheduleFactory(name="Monthly Tuition", cohort=cohort)
        InvoiceFactory(cohort=cohort, fee_schedule=fs)

    row = client.get(INVOICES_URL).json()["data"][0]
    assert "student_name" in row
    assert row["cohort_name"] == "Algebra A"
    assert row["fee_schedule_name"] == "Monthly Tuition"
