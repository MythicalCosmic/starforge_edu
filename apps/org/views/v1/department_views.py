"""Department endpoints — branch-scoped CRUD (object_scope='branch')."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.org.dto.org_dto import DepartmentCreateDTO
from apps.org.interfaces.services import IDepartmentService
from apps.org.presenters import department_to_dict
from apps.org.views.v1._shared import require_present, require_slug
from core.api_auth import check_perm, require_auth
from core.container import container
from core.exceptions import NotFoundException
from core.http import bool_field, decimal_field, int_field, read_json, str_field, trimmed_str_field
from core.listing import apply_filters, paginate
from core.responses import created, error, no_content, paginated, success
from core.scoping import assert_permission_membership_scope, scope_to_permission_memberships

_RESOURCE = "org"
_FILTERS = ("branch", "is_active")
_SEARCH = ("name", "slug")
_ORDERING = ("name", "created_at")


def _service() -> IDepartmentService:
    return container.resolve(IDepartmentService)  # type: ignore[type-abstract]


@csrf_exempt
@require_auth
def departments_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        check_perm(request, f"{_RESOURCE}:read")
        qs = scope_to_permission_memberships(
            request,
            _service().list(),
            permission=f"{_RESOURCE}:read",
            branch_field="branch_id",
        )
        qs = apply_filters(
            request,
            qs,
            filter_fields=_FILTERS,
            search_fields=_SEARCH,
            ordering_fields=_ORDERING,
            default_ordering="name",
        )
        items, total, page, size = paginate(request, qs)
        return paginated([department_to_dict(d) for d in items], total=total, page=page, page_size=size)
    if request.method == "POST":
        check_perm(request, f"{_RESOURCE}:write")
        body = read_json(request)
        branch_id = int_field(body, "branch", required=True)
        assert_permission_membership_scope(
            request,
            permission=f"{_RESOURCE}:write",
            branch_id=branch_id,
            enforce_department=False,
        )
        name, slug = str_field(body, "name"), str_field(body, "slug")
        require_present({"name": name, "slug": slug})
        require_slug("slug", slug)
        dto = DepartmentCreateDTO(
            branch_id=branch_id,  # type: ignore[arg-type]
            name=name,
            slug=slug,
            description=str_field(body, "description"),
            is_active=bool_field(body, "is_active", default=True),
            head_id=int_field(body, "head"),
            budget=decimal_field(body, "budget", max_digits=14),
        )
        return created(department_to_dict(_service().create(dto)))
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def department_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    read = request.method in ("GET", "HEAD")
    check_perm(request, f"{_RESOURCE}:read" if read else f"{_RESOURCE}:write")
    dept = _service().get(pk)
    if dept is None:
        raise NotFoundException(code="not_found")
    permission = f"{_RESOURCE}:read" if read else f"{_RESOURCE}:write"
    assert_permission_membership_scope(
        request,
        permission=permission,
        branch_id=dept.branch_id,
        enforce_department=False,
    )
    if read:
        return success(department_to_dict(dept))
    if request.method in ("PUT", "PATCH"):
        changes = _changes(read_json(request))
        if "branch" in changes:  # reassignment must land in a branch the caller can reach
            assert_permission_membership_scope(
                request,
                permission=f"{_RESOURCE}:write",
                branch_id=changes["branch"],
                enforce_department=False,
            )
        return success(department_to_dict(_service().update(dept, changes)))
    if request.method == "DELETE":
        _service().delete(dept)
        return no_content()
    return error("Method not allowed.", code="method_not_allowed", status=405)


def _changes(body: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if "branch" in body:
        changes["branch"] = int_field(body, "branch", required=True)
    if "name" in body:
        changes["name"] = trimmed_str_field(body, "name", required=True, max_length=200)
        require_present({"name": changes["name"]})
    if "slug" in body:
        changes["slug"] = trimmed_str_field(body, "slug", required=True, max_length=100)
        require_present({"slug": changes["slug"]})
        require_slug("slug", changes["slug"])
    if "description" in body:
        changes["description"] = trimmed_str_field(body, "description")
    if "is_active" in body:
        changes["is_active"] = bool_field(body, "is_active", default=True)
    if "head" in body:
        changes["head"] = int_field(body, "head")
    if "budget" in body:
        changes["budget"] = decimal_field(body, "budget", max_digits=14)
    return changes
