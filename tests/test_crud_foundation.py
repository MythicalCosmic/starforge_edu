"""Reusable CRUD foundation for the layered (off-DRF) views: require_perm (authz
parity with RolePermission/DenyWriteForReadOnlyToken), branch scoping, and the
filter/search/order/paginate list helpers."""

from __future__ import annotations

import pytest
from django.test import RequestFactory
from django_tenants.utils import schema_context

from core.exceptions import PermissionException
from core.listing import apply_filters, paginate
from core.scoping import assert_in_branch_scope, branch_ids, scope_to_branches

pytestmark = pytest.mark.django_db
_RF = RequestFactory()


def _get(user, **params):
    request = _RF.get("/x/", params)
    request.user = user
    return request


# --- listing helpers -------------------------------------------------------
def test_listing_filter_search_order_paginate(tenant_a):
    from apps.org.models import Branch

    with schema_context(tenant_a.schema_name):
        Branch.objects.create(name="ZZAlpha", slug="bz-alpha", is_active=True)
        Branch.objects.create(name="ZZBeta", slug="bz-beta", is_active=True)
        Branch.objects.create(name="ZZGamma", slug="bz-gamma", is_active=False)
        mine = Branch.objects.filter(slug__startswith="bz-")  # ignore any seeded branches

        qs = apply_filters(
            _RF.get("/", {"is_active": "true", "search": "et", "ordering": "name"}),
            mine,
            filter_fields=("is_active",),
            search_fields=("name",),
            ordering_fields=("name",),
        )
        assert [b.name for b in qs] == ["ZZBeta"]  # active + name~"et"

        items, total, page, size = paginate(
            _RF.get("/", {"page": "1", "page_size": "2"}), mine.order_by("name")
        )
        assert total == 3
        assert [b.name for b in items] == ["ZZAlpha", "ZZBeta"]  # first page of 2
        assert (page, size) == (1, 2)


# --- branch scoping --------------------------------------------------------
def test_branch_scoping_filters_and_guards(tenant_a, user_in):
    from apps.org.tests.factories import BranchFactory
    from apps.teachers.tests.factories import TeacherProfileFactory

    with schema_context(tenant_a.schema_name):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        mine = TeacherProfileFactory(branch=branch_a)
        theirs = TeacherProfileFactory(branch=branch_b)
    # A registrar scoped to branch_a (non-director, non-superuser).
    user = user_in(tenant_a, roles=["registrar"], branch=branch_a)

    with schema_context(tenant_a.schema_name):
        from apps.teachers.models import TeacherProfile

        request = _get(user)
        assert branch_ids(request) == {branch_a.id}
        scoped = scope_to_branches(request, TeacherProfile.objects.all())
        assert set(scoped.values_list("id", flat=True)) == {mine.id}  # branch_b hidden

        assert_in_branch_scope(_get(user), mine)  # in scope -> ok
        with pytest.raises(PermissionException) as exc:
            assert_in_branch_scope(_get(user), theirs)  # other branch -> 403
        assert exc.value.code == "out_of_scope"


# --- require_perm authz parity ---------------------------------------------
def test_require_perm_grants_denies_and_blocks_readonly_writes(tenant_a, user_in):
    from core.api_auth import require_perm

    @require_perm("teachers:read")
    def _view(request):
        return "ok"

    with schema_context(tenant_a.schema_name):
        # HEAD_OF_DEPT holds teachers:read; a CASHIER does not.
        hod = user_in(tenant_a, roles=["head_of_dept"])
        cashier = user_in(tenant_a, roles=["cashier"])

        assert _view(_get(hod)) == "ok"  # granted
        with pytest.raises(PermissionException):
            _view(_get(cashier))  # missing perm -> 403

        # A write under a read-only impersonation session is blocked outright.
        @require_perm("teachers:write")
        def _write_view(request):
            return "ok"

        req = _RF.post("/x/")
        req.user = hod
        req.is_read_only_token = True
        with pytest.raises(PermissionException) as exc:
            _write_view(req)
        assert exc.value.code == "read_only_token"
