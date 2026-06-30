"""Teacher endpoints — plain Django views over the layered architecture.

Collection (GET list / POST create) and detail (GET / PUT / PATCH / DELETE) dispatch on
method so the required perm tracks it (teachers:read for reads, teachers:write for
writes). Branch scoping mirrors the old ObjectScopedPermission: lists are scoped, detail/
write asserts the object is in the caller's branches, create asserts the target branch is.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.teachers.dto.teacher_dto import TeacherCreateDTO
from apps.teachers.interfaces.teacher_service import ITeacherService
from apps.teachers.presenters import teacher_to_dict
from core.api_auth import check_perm, require_auth
from core.container import container
from core.exceptions import NotFoundException, ValidationException
from core.http import bool_field, int_field, read_json, str_field
from core.listing import apply_filters, paginate
from core.permissions import get_user_roles
from core.responses import created, error, no_content, paginated, success, validation_error
from core.scoping import assert_branch_id_in_scope, assert_in_branch_scope, scope_to_branches

_RESOURCE = "teachers"
_FILTERS = ("branch", "department", "is_substitute")
_SEARCH = ("user__first_name", "user__last_name", "user__phone")
_ORDERING = ("created_at", "hire_date")
_SCALARS = ("hire_date", "subjects", "qualifications", "salary_type", "rate", "is_substitute")


def _service() -> ITeacherService:
    return container.resolve(ITeacherService)  # type: ignore[type-abstract]


@csrf_exempt
@require_auth
def teachers_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        check_perm(request, f"{_RESOURCE}:read")
        return _list(request)
    if request.method == "POST":
        check_perm(request, f"{_RESOURCE}:write")
        return _create(request)
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def teacher_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    read = request.method in ("GET", "HEAD")
    check_perm(request, f"{_RESOURCE}:read" if read else f"{_RESOURCE}:write")
    teacher = _service().get(pk)
    if teacher is None:
        raise NotFoundException(code="not_found")
    assert_in_branch_scope(request, teacher)  # branch-scoped role can't touch another branch

    if request.method in ("GET", "HEAD"):
        return success(teacher_to_dict(teacher))
    if request.method in ("PUT", "PATCH"):
        updated = _service().update(teacher, _changes(read_json(request)))
        return success(teacher_to_dict(updated))
    if request.method == "DELETE":
        _service().delete(teacher)
        return no_content()
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def teacher_dashboard_view(request: HttpRequest) -> HttpResponse:
    if request.method != "GET":
        return error("Method not allowed.", code="method_not_allowed", status=405)
    return success(_service().dashboard(request.user, get_user_roles(request)))  # type: ignore[arg-type]


# --- helpers ---------------------------------------------------------------
def _list(request: HttpRequest) -> HttpResponse:
    qs = scope_to_branches(request, _service().list())
    qs = apply_filters(
        request,
        qs,
        filter_fields=_FILTERS,
        search_fields=_SEARCH,
        ordering_fields=_ORDERING,
        default_ordering="-created_at",
    )
    items, total, page, size = paginate(request, qs)
    return paginated([teacher_to_dict(t) for t in items], total=total, page=page, page_size=size)


def _create(request: HttpRequest) -> HttpResponse:
    body = read_json(request)
    phone = str_field(body, "phone")
    email = str_field(body, "email")
    if not phone and not email:
        return validation_error({"phone": ["Provide a phone or an email."]})
    branch_id = int_field(body, "branch", required=True)
    assert_branch_id_in_scope(request, branch_id)  # create-scope (no object yet)
    dto = TeacherCreateDTO(
        branch_id=branch_id,  # type: ignore[arg-type]
        department_id=int_field(body, "department"),
        phone=phone,
        email=email,
        first_name=str_field(body, "first_name"),
        last_name=str_field(body, "last_name"),
        middle_name=str_field(body, "middle_name"),
        hire_date=_date(body, "hire_date"),
        subjects=_list_field(body, "subjects"),
        qualifications=str_field(body, "qualifications"),
        salary_type=str_field(body, "salary_type", default="monthly"),
        rate=_decimal(body, "rate"),
        is_substitute=bool_field(body, "is_substitute"),
    )
    return created(teacher_to_dict(_service().create(dto)))


def _changes(body: dict[str, Any]) -> dict[str, Any]:
    """The provided updatable fields only (PATCH-correct: absent vs null differ)."""
    changes: dict[str, Any] = {}
    if "branch" in body:
        changes["branch"] = int_field(body, "branch", required=True)
    if "department" in body:
        changes["department"] = int_field(body, "department")
    if "hire_date" in body:
        changes["hire_date"] = _date(body, "hire_date")
    if "subjects" in body:
        changes["subjects"] = _list_field(body, "subjects")
    if "qualifications" in body:
        changes["qualifications"] = str_field(body, "qualifications")
    if "salary_type" in body:
        changes["salary_type"] = str_field(body, "salary_type", default="monthly")
    if "rate" in body:
        changes["rate"] = _decimal(body, "rate")
    if "is_substitute" in body:
        changes["is_substitute"] = bool_field(body, "is_substitute")
    return changes


def _date(body: dict[str, Any], name: str) -> date | None:
    raw = body.get(name)
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise ValidationException(
            "Invalid date.", code="validation_error", fields={name: ["Must be an ISO date."]}
        ) from None


def _decimal(body: dict[str, Any], name: str) -> Decimal | None:
    raw = body.get(name)
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValidationException(
            "Invalid number.", code="validation_error", fields={name: ["Must be a number."]}
        ) from None


def _list_field(body: dict[str, Any], name: str) -> list:
    raw = body.get(name, [])
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValidationException(
            "Invalid list.", code="validation_error", fields={name: ["Must be a list."]}
        )
    return raw
