from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.org.models import Branch
from apps.tasks import services
from apps.tasks.models import RoleGrade, Task
from apps.tasks.serializers import (
    RoleGradeSerializer,
    TaskAssignSerializer,
    TaskAutoAssignSerializer,
    TaskCreateSerializer,
    TaskSerializer,
    TaskTransitionSerializer,
)
from core.exceptions import PermissionException
from core.permissions import (
    Role,
    default_perms,
    get_role_memberships,
    get_user_roles,
    has_permission_code,
)
from core.viewsets import TenantSafeModelViewSet


class RoleGradeViewSet(TenantSafeModelViewSet):
    """Per-center role hierarchy (F5-1). Reading is open to staff (tasks:read);
    editing the hierarchy is a senior action (tasks:assign_any — director / HOD),
    since it decides who may task whom."""

    serializer_class = RoleGradeSerializer
    resource = "tasks"
    required_perms = {
        "list": "tasks:read",
        "retrieve": "tasks:read",
        "create": "tasks:assign_any",
        "update": "tasks:assign_any",
        "partial_update": "tasks:assign_any",
        "destroy": "tasks:assign_any",
    }
    queryset = RoleGrade.objects.all()
    ordering_fields = ("level", "role")


class TaskViewSet(TenantSafeModelViewSet):
    """Tasks (F5-2/3). Anyone with tasks:write creates + assigns (hierarchy-gated);
    an assignee (tasks:read) sees and transitions their own work. Managers see their
    branch's tasks; everyone sees tasks assigned to them or their department."""

    serializer_class = TaskSerializer
    resource = "tasks"
    required_perms = {
        **default_perms("tasks"),
        "assign": "tasks:write",
        "auto_assign": "tasks:write",
        "transition": "tasks:read",
        "mine": "tasks:read",
    }
    # Managed via create + assign/transition actions; no raw PUT/PATCH/DELETE.
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "priority", "assignee", "department", "branch")
    search_fields = ("title",)
    ordering_fields = ("created_at", "due_at", "priority")

    def _base(self):
        return Task.objects.select_related("assignee", "department", "branch", "created_by")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def _assert_scope(self, *, branch=None, department=None) -> None:
        """A non-director may only place a task in their own branch / a department of
        their branch — otherwise they could plant work in another branch (the same
        intra-tenant leak class as forms)."""
        if self._is_director():
            return
        my = self._branch_ids()
        if branch is not None and branch.id not in my:
            raise PermissionException(_("You can only use your own branch."), code="cross_branch")
        if department is not None and department.branch_id not in my:
            raise PermissionException(
                _("You can only use a department in your own branch."), code="cross_branch_dept"
            )

    def get_queryset(self):
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return self._base()
        memberships = get_role_memberships(self.request)
        my_branches = {m.branch_id for m in memberships if m.branch_id}
        my_depts = {m.department_id for m in memberships if m.department_id}
        scope = Q(assignee=user) | Q(created_by=user)
        if my_depts:
            scope |= Q(department_id__in=my_depts)
        if has_permission_code(roles, "tasks:write") and my_branches:
            scope |= Q(branch_id__in=my_branches)
        return self._base().filter(scope)

    @extend_schema(request=TaskCreateSerializer, responses={201: TaskSerializer}, tags=["tasks"])
    def create(self, request, *args, **kwargs):
        ser = TaskCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if data.get("branch") is None and not request.user.is_superuser:
            my_branches = {m.branch_id for m in get_role_memberships(request) if m.branch_id}
            if len(my_branches) == 1:
                data["branch"] = Branch.objects.get(pk=next(iter(my_branches)))
        self._assert_scope(branch=data.get("branch"), department=data.get("department"))
        task = services.create_task(created_by=request.user, created_by_roles=get_user_roles(request), **data)
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TaskAssignSerializer, responses={200: TaskSerializer}, tags=["tasks"])
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        task = self.get_object()
        ser = TaskAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        kwargs = {k: ser.validated_data[k] for k in ("assignee", "department") if k in ser.validated_data}
        if "department" in kwargs:
            self._assert_scope(department=kwargs["department"])
        task = services.assign_task(
            task=task, actor=request.user, actor_roles=get_user_roles(request), **kwargs
        )
        return Response(TaskSerializer(task).data)

    @extend_schema(request=TaskTransitionSerializer, responses={200: TaskSerializer}, tags=["tasks"])
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        task = self.get_object()
        ser = TaskTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        task = services.transition_task(task=task, to_status=ser.validated_data["status"], actor=request.user)
        return Response(TaskSerializer(task).data)

    @extend_schema(
        request=TaskAutoAssignSerializer,
        responses={200: OpenApiResponse(description="{mode, assigned, freed, assignments}")},
        tags=["tasks"],
    )
    @action(detail=False, methods=["post"], url_path="auto-assign")
    def auto_assign(self, request):
        """F5-4: distribute a department's open tasks across its staff — `fair` balances
        by current load (least-loaded first), `free` leaves them department-claimable."""
        ser = TaskAutoAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        department = ser.validated_data["department"]
        self._assert_scope(department=department)  # only your own branch's department
        result = services.auto_split_tasks(
            task_ids=ser.validated_data["task_ids"],
            department=department,
            actor=request.user,
            actor_roles=get_user_roles(request),
            mode=ser.validated_data["mode"],
        )
        return Response(result)

    @extend_schema(responses={200: TaskSerializer(many=True)}, tags=["tasks"])
    @action(detail=False, methods=["get"])
    def mine(self, request):
        qs = self._base().filter(assignee=request.user)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(TaskSerializer(page, many=True).data)
        return Response(TaskSerializer(qs, many=True).data)
