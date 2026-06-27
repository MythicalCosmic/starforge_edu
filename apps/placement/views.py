from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.org.models import Branch
from apps.placement import selectors, services
from apps.placement.models import GroupProposal, PlacementAttempt, PlacementTest
from apps.placement.serializers import (
    AssignAttemptSerializer,
    GroupProposalSerializer,
    LeadAttemptSerializer,
    PlacementAttemptSerializer,
    PlacementQuestionSerializer,
    PlacementTestCreateSerializer,
    PlacementTestSerializer,
    PlacementTestUpdateSerializer,
    ProposeGroupSerializer,
    RejectSerializer,
    SubmitAttemptSerializer,
)
from apps.students.selectors import student_profile_for
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


class PlacementAttemptViewSet(TenantSafeModelViewSet):
    """Sitting + auto-grading (F1-5 / F1-6). Staff (placement:write) assign an
    APPROVED test to a lead; the lead (or a proctor) submits answers and the
    objective questions are graded instantly, setting the lead's academic_level.
    A lead sees only their own attempts — and never the answer key."""

    serializer_class = PlacementAttemptSerializer
    resource = "placement"
    http_method_names = ["get", "post", "head", "options"]  # no DELETE on graded artifacts
    # assigning + reading group suggestions are staff actions; reading/submitting an
    # attempt are self-actions (IsAuthenticated, row-scoped) — see get_permissions.
    required_perms = {"create": "placement:write", "suggestions": "placement:write"}
    filterset_fields = ("status", "test", "student")

    # Reading + submitting are open to any authenticated user and row-scoped below
    # (a lead reaches only their own attempts; staff only their branch's).
    _SELF_ACTIONS = {"list", "retrieve", "submit"}

    def get_permissions(self):
        if getattr(self, "action", None) in self._SELF_ACTIONS:
            return [IsAuthenticated()]
        return super().get_permissions()

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _actor_is_staff(self) -> bool:
        user = self.request.user
        roles = get_user_roles(self.request)
        return user.is_superuser or Role.DIRECTOR in roles or has_permission_code(roles, "placement:write")

    def get_serializer_class(self):
        # A test-taker (lead) gets an is_correct-free view so the answer key can't
        # be reconstructed by inference; staff/proctors see the full grading.
        return PlacementAttemptSerializer if self._actor_is_staff() else LeadAttemptSerializer

    def get_queryset(self):
        qs = PlacementAttempt.objects.select_related("test", "student", "student__user").prefetch_related(
            "answers", "test__questions"
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        if has_permission_code(roles, "placement:write"):
            # Staff: attempts they assigned or on a test in their branch.
            return qs.filter(Q(assigned_by=user) | Q(test__branch_id__in=self._branch_ids())).distinct()
        # The lead: only their own attempts (the answer key is still never serialized).
        profile = student_profile_for(user)
        if profile is not None:
            return qs.filter(student=profile)
        return qs.none()

    def _assert_in_scope(self, test: PlacementTest, student) -> None:
        if self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request):
            return
        my_branches = self._branch_ids()
        if test.branch_id is not None and test.branch_id not in my_branches:
            raise PermissionException(
                _("You can only assign a test from your own branch."), code="cross_branch"
            )
        if student.branch_id not in my_branches:
            raise PermissionException(
                _("You can only assign to a student in your own branch."), code="cross_branch"
            )

    @extend_schema(
        request=AssignAttemptSerializer, responses={201: PlacementAttemptSerializer}, tags=["placement"]
    )
    def create(self, request, *args, **kwargs):
        ser = AssignAttemptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        test = ser.validated_data["test"]
        student = ser.validated_data["student"]
        self._assert_in_scope(test, student)
        attempt = services.assign_test(test=test, student=student, assigned_by=request.user)
        return Response(self.get_serializer(attempt).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=SubmitAttemptSerializer, responses={200: PlacementAttemptSerializer}, tags=["placement"]
    )
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        # get_object is row-scoped: a lead resolves only their own attempt, a staff
        # proctor only their branch's — so reaching it here IS the authorization.
        attempt = self.get_object()
        ser = SubmitAttemptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        attempt = services.submit_attempt(attempt=attempt, answers=ser.validated_data["answers"])
        return Response(self.get_serializer(attempt).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="[{cohort_id, name, level, level_match, seats_available, start_date}]"
            )
        },
        tags=["placement"],
    )
    @action(detail=True, methods=["get"])
    def suggestions(self, request, pk=None):
        """F1-7: cohorts in the lead's branch they could join, ranked by level fit
        and seats. Staff-only — it's reception's placing tool, not the lead's."""
        attempt = self.get_object()
        return Response(selectors.suggest_cohorts(student=attempt.student))


class GroupProposalViewSet(TenantSafeModelViewSet):
    """Group placement (F1-8). Reception (placement:write) proposes a cohort for a
    placed lead; a manager (placement:approve) accepts (→ the lead is enrolled) or
    rejects. When the centre's require_group_acceptance toggle is off, the proposal
    auto-accepts and enrolls on creation (reception assigns directly)."""

    serializer_class = GroupProposalSerializer
    resource = "placement"
    http_method_names = ["get", "post", "head", "options"]  # no DELETE on a decided record
    required_perms = {
        **default_perms("placement"),
        "accept": "placement:approve",
        "reject": "placement:approve",
    }
    filterset_fields = ("status", "student", "cohort")

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def _is_director(self) -> bool:
        return self.request.user.is_superuser or Role.DIRECTOR in get_user_roles(self.request)

    def get_queryset(self):
        qs = GroupProposal.objects.select_related(
            "student", "cohort", "proposed_by", "decided_by"
        )
        if self._is_director():
            return qs
        # Staff see proposals they made or for a cohort in their branch.
        return qs.filter(
            Q(proposed_by=self.request.user) | Q(cohort__branch_id__in=self._branch_ids())
        ).distinct()

    def _assert_in_scope(self, cohort) -> None:
        if self._is_director():
            return
        if cohort.branch_id not in self._branch_ids():
            raise PermissionException(
                _("You can only place students into your own branch's groups."), code="cross_branch"
            )

    @extend_schema(
        request=ProposeGroupSerializer, responses={201: GroupProposalSerializer}, tags=["placement"]
    )
    def create(self, request, *args, **kwargs):
        ser = ProposeGroupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cohort = ser.validated_data["cohort"]
        self._assert_in_scope(cohort)
        proposal = services.propose_group(
            student=ser.validated_data["student"], cohort=cohort, proposed_by=request.user
        )
        return Response(GroupProposalSerializer(proposal).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: GroupProposalSerializer}, tags=["placement"])
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        proposal = services.accept_proposal(proposal=self.get_object(), manager=request.user)
        return Response(GroupProposalSerializer(proposal).data)

    @extend_schema(request=RejectSerializer, responses={200: GroupProposalSerializer}, tags=["placement"])
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        proposal = services.reject_proposal(
            proposal=self.get_object(), manager=request.user, reason=ser.validated_data["reason"]
        )
        return Response(GroupProposalSerializer(proposal).data)
