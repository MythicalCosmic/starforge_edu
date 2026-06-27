from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.org.models import Branch
from apps.placement import services
from apps.placement.models import PlacementTest
from apps.placement.serializers import (
    PlacementQuestionSerializer,
    PlacementTestCreateSerializer,
    PlacementTestSerializer,
    PlacementTestUpdateSerializer,
    RejectSerializer,
)
from core.exceptions import NotFoundException, PermissionException, ValidationException
from core.permissions import (
    Role,
    default_perms,
    get_role_memberships,
    get_user_roles,
    has_permission_code,
)
from core.viewsets import TenantSafeModelViewSet


class PlacementTestViewSet(TenantSafeModelViewSet):
    """Placement test bank + approval lifecycle (F1-2 / F1-4). Builders
    (placement:write) create a test, add questions while it is DRAFT, and submit
    it for review. A manager (placement:approve) approves or rejects it — but
    never their own (maker-checker). Builders see their own + their branch's
    tests; the director sees the whole centre."""

    serializer_class = PlacementTestSerializer
    resource = "placement"
    required_perms = {
        **default_perms("placement"),
        "add_question": "placement:write",
        "remove_question": "placement:write",
        "submit": "placement:write",
        "approve": "placement:approve",
        "reject": "placement:approve",
    }
    search_fields = ("title",)
    ordering_fields = ("created_at", "title")
    filterset_fields = ("status", "branch", "subject")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def get_queryset(self):
        qs = PlacementTest.objects.select_related("subject", "branch", "created_by", "approved_by").prefetch_related(
            "questions"
        )
        if self._is_director():
            return qs  # the director sees the whole centre
        roles = get_user_roles(self.request)
        if has_permission_code(roles, "placement:write"):
            # A builder manages only their own branches' tests (+ anything they
            # made) — the isolation gate, since every detail action (submit/approve/
            # add-question) resolves through get_object -> this queryset.
            return qs.filter(Q(created_by=self.request.user) | Q(branch_id__in=self._branch_ids()))
        return qs.none()  # placement is staff-only until a lead is assigned an attempt (F1-5)

    def get_serializer_class(self):
        if self.action == "create":
            return PlacementTestCreateSerializer
        if self.action in ("update", "partial_update"):
            return PlacementTestUpdateSerializer
        return PlacementTestSerializer

    @extend_schema(
        request=PlacementTestCreateSerializer, responses={201: PlacementTestSerializer}, tags=["placement"]
    )
    def create(self, request, *args, **kwargs):
        ser = PlacementTestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if not self._is_director():
            # A non-director builds only within their own branch; only the director
            # may create a centre-wide (branch=None) placement test.
            my_branches = self._branch_ids()
            branch = data.get("branch")
            if branch is None:
                if len(my_branches) == 1:
                    data["branch"] = Branch.objects.get(pk=next(iter(my_branches)))
                else:
                    raise ValidationException(_("Choose a branch for this test."), code="branch_required")
            elif branch.id not in my_branches:
                raise PermissionException(
                    _("You can only create tests in your own branch."), code="cross_branch"
                )
        test = services.create_test(created_by=request.user, **data)
        return Response(PlacementTestSerializer(test).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        test = self.get_object()
        ser = PlacementTestUpdateSerializer(data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        test = services.update_test(test=test, **ser.validated_data)
        return Response(PlacementTestSerializer(test).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        # DRAFT-only: a pending/approved test is never hard-deleted unilaterally
        # (it would erase a manager's sign-off + cascade its questions). See
        # services.delete_test — mirrors the draft-only freeze on every other edit.
        services.delete_test(test=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=PlacementQuestionSerializer, responses={201: PlacementQuestionSerializer}, tags=["placement"]
    )
    @action(detail=True, methods=["post"], url_path="questions")
    def add_question(self, request, pk=None):
        test = self.get_object()
        ser = PlacementQuestionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        question = services.add_question(test=test, **ser.validated_data)
        return Response(PlacementQuestionSerializer(question).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None}, tags=["placement"])
    @action(detail=True, methods=["post"], url_path=r"questions/(?P<question_id>\d+)/remove")
    def remove_question(self, request, pk=None, question_id=None):
        test = self.get_object()
        question = test.questions.filter(pk=question_id).first()
        if question is None:
            raise NotFoundException(_("That question is not on this test."), code="question_not_found")
        services.remove_question(question=question)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: PlacementTestSerializer}, tags=["placement"])
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        test = services.submit_for_review(test=self.get_object())
        return Response(PlacementTestSerializer(test).data)

    @extend_schema(request=None, responses={200: PlacementTestSerializer}, tags=["placement"])
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        test = services.approve_test(test=self.get_object(), approver=request.user)
        return Response(PlacementTestSerializer(test).data)

    @extend_schema(request=RejectSerializer, responses={200: PlacementTestSerializer}, tags=["placement"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        test = services.reject_test(
            test=self.get_object(), reviewer=request.user, reason=ser.validated_data["reason"]
        )
        return Response(PlacementTestSerializer(test).data)
