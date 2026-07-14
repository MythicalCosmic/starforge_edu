"""Role-native staff-account administration API."""

from __future__ import annotations

from typing import Any

from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt

from apps.access.models import AccountType
from apps.org.models import Branch, Department, StaffProfile
from apps.org.presenters import staff_to_dict
from apps.org.services import STAFF_ROLES, create_staff_account, deactivate_staff_account
from apps.users.models import RoleMembership
from core.api_auth import check_perm, require_auth
from core.exceptions import NotFoundException, ValidationException
from core.http import bool_field, int_field, read_json, str_field
from core.listing import apply_filters, paginate
from core.permissions import get_user_roles
from core.responses import created, error, no_content, paginated, success
from core.scoping import (
    assert_permission_membership_scope,
    is_unscoped,
    permission_membership_branch_ids,
)

_SEARCH = ("username", "first_name", "last_name", "phone", "email")
_ORDERING = ("created_at", "last_name", "first_name", "username")


def _query(request: HttpRequest, permission: str):
    qs = StaffProfile.objects.select_related("user").prefetch_related(
        Prefetch(
            "user__role_memberships",
            queryset=RoleMembership.objects.select_related("account_type"),
        )
    )
    if not is_unscoped(request):
        scoped_branch_ids = permission_membership_branch_ids(
            roles=get_user_roles(request), permission=permission
        )
        qs = qs.filter(
            user__role_memberships__branch_id__in=scoped_branch_ids,
            user__role_memberships__revoked_at__isnull=True,
        )
    return qs.distinct()


def _get(request: HttpRequest, pk: int, permission: str) -> StaffProfile:
    staff = _query(request, permission).filter(pk=pk).first()
    if staff is None:
        raise NotFoundException(code="not_found")
    return staff


def _date(body: dict[str, Any], name: str):
    raw = body.get(name)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        parsed = None
    else:
        try:
            parsed = parse_date(raw)
        except ValueError:
            parsed = None
    if parsed is None:
        raise ValidationException(
            "Invalid date.",
            code="validation_error",
            fields={name: ["Enter a valid date (YYYY-MM-DD)."]},
        )
    return parsed


def _gender(body: dict[str, Any]) -> str:
    value = str_field(body, "gender")
    if value and value not in StaffProfile.Gender.values:
        raise ValidationException(
            "Invalid gender.",
            code="validation_error",
            fields={"gender": ["Not a valid choice."]},
        )
    return value


def _branch(branch_id: int | None) -> Branch:
    if branch_id is None:
        raise ValidationException("Invalid branch.", code="invalid_branch", fields={"branch": ["Not found."]})
    branch = Branch.objects.filter(pk=branch_id, archived_at__isnull=True).first()
    if branch is None:
        raise ValidationException("Invalid branch.", code="invalid_branch", fields={"branch": ["Not found."]})
    return branch


def _department(department_id: int | None) -> Department | None:
    if department_id is None:
        return None
    department = Department.objects.filter(pk=department_id).first()
    if department is None:
        raise ValidationException(
            "Invalid department.",
            code="invalid_department",
            fields={"department": ["Not found."]},
        )
    return department


def _staff_account_type(data: dict[str, Any], *, required: bool) -> AccountType | None:
    account_type_id = int_field(data, "account_type")
    if account_type_id is not None:
        account_type = AccountType.objects.filter(
            pk=account_type_id,
            account_kind=AccountType.AccountKind.STAFF,
            is_active=True,
        ).first()
        if account_type is None:
            raise ValidationException(
                "Invalid account type.",
                code="invalid_account_type",
                fields={"account_type": ["Choose an active staff account type."]},
            )
        return account_type

    # Temporary request compatibility for clients that still send the old role
    # field. Responses and the admin surface are AccountType-native.
    role = str_field(data, "role")
    if role:
        account_type = AccountType.objects.filter(
            is_system=True,
            is_active=True,
            account_kind=AccountType.AccountKind.STAFF,
            slug=role,
        ).first()
        if account_type is None:
            raise ValidationException(
                "Invalid account type.",
                code="invalid_account_type",
                fields={"account_type": ["The matching system account type is unavailable."]},
            )
        return account_type
    if required:
        raise ValidationException(
            "Account type is required.",
            code="validation_error",
            fields={"account_type": ["This field is required."]},
        )
    return None


@csrf_exempt
@require_auth
def staff_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method in ("GET", "HEAD"):
        check_perm(request, "users:read")
        qs = apply_filters(
            request,
            _query(request, "users:read"),
            filter_fields=("is_active",),
            search_fields=_SEARCH,
            ordering_fields=_ORDERING,
            default_ordering="last_name",
        )
        account_type_raw = request.GET.get("account_type", "").strip()
        if account_type_raw:
            try:
                account_type_id = int(account_type_raw)
            except ValueError:
                raise ValidationException(
                    "Invalid account type.",
                    code="invalid_query_param",
                    fields={"account_type": ["Must be an integer."]},
                ) from None
            qs = qs.filter(
                user__role_memberships__account_type_id=account_type_id,
                user__role_memberships__revoked_at__isnull=True,
            ).distinct()
        else:
            role = request.GET.get("role", "").strip()
            if role:
                if role not in STAFF_ROLES:
                    raise ValidationException(
                        "Invalid role.", code="validation_error", fields={"role": ["Not a staff role."]}
                    )
                qs = qs.filter(
                    user__role_memberships__account_type__is_system=True,
                    user__role_memberships__account_type__slug=role,
                    user__role_memberships__revoked_at__isnull=True,
                ).distinct()
        items, total, page, size = paginate(request, qs)
        return paginated(
            [staff_to_dict(staff) for staff in items],
            total=total,
            page=page,
            page_size=size,
        )
    if request.method == "POST":
        check_perm(request, "users:write")
        body = read_json(request)
        phone, email = str_field(body, "phone"), str_field(body, "email")
        if not phone and not email:
            raise ValidationException(
                "Provide a phone or an email.",
                code="validation_error",
                fields={"phone": ["Provide a phone or an email."]},
            )
        branch_id = int_field(body, "branch", required=True)
        assert_permission_membership_scope(
            request,
            permission="users:write",
            branch_id=branch_id,
            enforce_department=False,
        )
        staff = create_staff_account(
            branch=_branch(branch_id),
            department=_department(int_field(body, "department")),
            account_type=_staff_account_type(body, required=True),
            username=str_field(body, "username"),
            phone=phone,
            email=email,
            first_name=str_field(body, "first_name"),
            last_name=str_field(body, "last_name"),
            middle_name=str_field(body, "middle_name"),
            birthdate=_date(body, "birthdate"),
            gender=_gender(body),
        )
        staff = _query(request, "users:write").get(pk=staff.pk)
        return created(staff_to_dict(staff))
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def staff_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    read = request.method in ("GET", "HEAD")
    check_perm(request, "users:read" if read else "users:write")
    permission = "users:read" if read else "users:write"
    staff = _get(request, pk, permission)
    if read:
        return success(staff_to_dict(staff))
    if request.method in ("PUT", "PATCH"):
        body = read_json(request)
        changes: dict[str, Any] = {
            field: str_field(body, field)
            for field in ("first_name", "last_name", "middle_name", "phone", "email")
            if field in body
        }
        if "birthdate" in body:
            changes["birthdate"] = _date(body, "birthdate")
        if "gender" in body:
            changes["gender"] = _gender(body)
        if "is_active" in body:
            changes["is_active"] = bool_field(body, "is_active")
        if changes:
            from apps.users.services import update_role_identity

            update_role_identity(staff, changes)
        if any(field in body for field in ("account_type", "role", "branch", "department")):
            membership = (
                staff.user.role_memberships.filter(
                    revoked_at__isnull=True,
                    account_type__account_kind=AccountType.AccountKind.STAFF,
                )
                .select_related("account_type", "branch", "department")
                .order_by("-account_type__is_system", "id")
                .first()
            )
            if membership is None:
                raise ValidationException(
                    "Staff account has no active account type.",
                    code="missing_account_type",
                )
            account_type = _staff_account_type(body, required=False) or membership.account_type
            branch_id = int_field(body, "branch", required=True) if "branch" in body else membership.branch_id
            assert_permission_membership_scope(
                request,
                permission="users:write",
                branch_id=branch_id,
                enforce_department=False,
            )
            branch = _branch(branch_id)
            department = (
                _department(int_field(body, "department")) if "department" in body else membership.department
            )
            if department is not None and department.branch_id != branch.pk:
                raise ValidationException(
                    "Department must belong to the selected branch.",
                    code="department_branch_mismatch",
                )
            from apps.users.services import ensure_role_membership

            ensure_role_membership(
                staff,
                account_type=account_type,
                branch=branch,
                department=department,
            )
        refreshed = _query(request, "users:write").get(pk=staff.pk)
        return success(staff_to_dict(refreshed))
    if request.method == "DELETE":
        deactivate_staff_account(staff)
        return no_content()
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def staff_credentials_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, "users:write")
    staff = _get(request, pk, "users:write")
    from apps.users.services import issue_role_credentials

    return success(
        issue_role_credentials(
            staff,
            actor=request.user,
            resource_type="org.StaffProfile",
        )
    )
