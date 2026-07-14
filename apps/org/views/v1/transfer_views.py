"""Branch-transfer endpoints — read-only audit list (D1-LF-6)."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.org.interfaces.services import IBranchTransferService
from apps.org.models import BranchTransfer
from apps.org.presenters import transfer_to_dict
from core.api_auth import check_perm, require_auth
from core.container import container
from core.exceptions import NotFoundException
from core.http import int_field, read_json, trimmed_str_field
from core.listing import apply_filters, paginate
from core.permissions import get_user_roles
from core.responses import created, error, paginated, success
from core.scoping import is_unscoped, permission_membership_branch_ids

_RESOURCE = "org"
_FILTERS = ("user", "from_branch", "to_branch")
_ORDERING = ("created_at",)


def _service() -> IBranchTransferService:
    return container.resolve(IBranchTransferService)  # type: ignore[type-abstract]


def _query(request: HttpRequest) -> QuerySet[BranchTransfer]:
    """Transfers touching a branch covered by this exact org:read grant.

    Branches themselves are tenant-wide directory data, but transfer rows are an
    audit trail about a person.  A role in Branch A must not receive unrelated
    Branch B -> C personnel movements merely because it can list branch names.
    """
    queryset = _service().list()
    if is_unscoped(request):
        return queryset
    allowed = permission_membership_branch_ids(
        roles=get_user_roles(request),
        permission=f"{_RESOURCE}:read",
    )
    return queryset.filter(Q(from_branch_id__in=allowed) | Q(to_branch_id__in=allowed))


@csrf_exempt
@require_auth
def transfers_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        check_perm(request, f"{_RESOURCE}:read")
        qs = apply_filters(
            request,
            _query(request),
            filter_fields=_FILTERS,
            ordering_fields=_ORDERING,
            default_ordering="-created_at",
        )
        items, total, page, size = paginate(request, qs)
        return paginated([transfer_to_dict(t) for t in items], total=total, page=page, page_size=size)
    if request.method == "POST":
        permission = f"{_RESOURCE}:write"
        check_perm(request, permission)
        body = read_json(request)
        student_id = int_field(body, "student", required=True)
        to_branch_id = int_field(body, "to_branch", required=True)
        reason = trimmed_str_field(body, "reason", max_length=64)
        roles = get_user_roles(request)
        allowed_branch_ids = (
            None
            if is_unscoped(request)
            else permission_membership_branch_ids(roles=roles, permission=permission)
        )
        transfer = _service().transfer_student(
            student_id=student_id,  # type: ignore[arg-type]  # required parser guarantees int
            to_branch_id=to_branch_id,  # type: ignore[arg-type]
            reason=reason,
            actor=request.user,
            allowed_branch_ids=allowed_branch_ids,
        )
        return created(transfer_to_dict(transfer))
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def transfer_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    transfer = _query(request).filter(pk=pk).first()
    if transfer is None:
        raise NotFoundException(code="not_found")
    return success(transfer_to_dict(transfer))
