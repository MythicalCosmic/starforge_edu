from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.meetings import services
from apps.meetings.models import StaffMeeting
from apps.meetings.serializers import (
    RespondMeetingSerializer,
    ScheduleMeetingSerializer,
    StaffMeetingSerializer,
)
from core.exceptions import PermissionException
from core.permissions import Role, get_role_memberships, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class StaffMeetingViewSet(TenantSafeModelViewSet):
    """Staff meetings (F3-5). A manager (meeting:write) schedules a meeting + invites
    staff; invitees read and RSVP to their own without a separate read permission. Read
    scoping: a manager sees their branch's meetings, anyone else sees only the ones they
    were invited to."""

    serializer_class = StaffMeetingSerializer
    resource = "meeting"
    # Only scheduling/cancelling is permission-gated; reading + RSVP are open to any
    # authenticated user and row-scoped by get_queryset (so invitees need no extra perm).
    required_perms = {"create": "meeting:write", "cancel": "meeting:write"}
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "branch")
    ordering_fields = ("starts_at",)

    _SELF_ACTIONS = {"list", "retrieve", "respond", "upcoming"}

    def get_permissions(self):
        if getattr(self, "action", None) in self._SELF_ACTIONS:
            return [IsAuthenticated()]
        return super().get_permissions()

    def _branch_ids(self) -> set[int]:
        return {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}

    def get_queryset(self):
        qs = StaffMeeting.objects.select_related("branch", "created_by", "cancelled_by").prefetch_related(
            "attendees"
        )
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        # request.user is User|AnonymousUser; the spanning lookup needs the User.
        if has_permission_code(roles, "meeting:write"):
            # A manager sees their branch's meetings UNIONED with any they were personally
            # invited to (cross-branch / centre-wide) — else they'd see an invite in
            # /upcoming/ but 404 trying to open or RSVP it.
            return qs.filter(Q(branch_id__in=self._branch_ids()) | Q(attendees__user=user)).distinct()
        return qs.filter(attendees__user=user).distinct()  # type: ignore[misc]  # invitees see only their own

    def _assert_branch_in_scope(self, branch) -> None:
        user = self.request.user
        if user.is_superuser or Role.DIRECTOR in get_user_roles(self.request):
            return
        if branch is None:
            raise PermissionException(_("Choose a branch for the meeting."), code="branch_required")
        if branch.id not in self._branch_ids():
            raise PermissionException(
                _("You can only schedule a meeting for your own branch."), code="branch_out_of_scope"
            )

    @extend_schema(
        request=ScheduleMeetingSerializer, responses={201: StaffMeetingSerializer}, tags=["meeting"]
    )
    def create(self, request, *args, **kwargs):
        ser = ScheduleMeetingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self._assert_branch_in_scope(ser.validated_data.get("branch"))
        meeting = services.schedule_meeting(
            title=ser.validated_data["title"],
            agenda=ser.validated_data["agenda"],
            starts_at=ser.validated_data["starts_at"],
            ends_at=ser.validated_data["ends_at"],
            location=ser.validated_data["location"],
            attendees=ser.validated_data["attendees"],
            created_by=request.user,
            branch=ser.validated_data.get("branch"),
        )
        return Response(StaffMeetingSerializer(meeting).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: StaffMeetingSerializer}, tags=["meeting"])
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        meeting = services.cancel_meeting(meeting_id=self.get_object().pk, actor=request.user)
        return Response(StaffMeetingSerializer(meeting).data)

    @extend_schema(
        request=RespondMeetingSerializer, responses={200: StaffMeetingSerializer}, tags=["meeting"]
    )
    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        ser = RespondMeetingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.respond_to_meeting(
            meeting_id=self.get_object().pk, user=request.user, response=ser.validated_data["response"]
        )
        return Response(StaffMeetingSerializer(self.get_object()).data)

    @extend_schema(responses={200: StaffMeetingSerializer(many=True)}, tags=["meeting"])
    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        qs = (
            StaffMeeting.objects.filter(
                attendees__user=request.user,
                status=StaffMeeting.Status.SCHEDULED,
                starts_at__gte=timezone.now(),
            )
            .select_related("branch", "created_by")
            .prefetch_related("attendees")
            .order_by("starts_at")
            .distinct()
        )
        return Response(StaffMeetingSerializer(qs, many=True).data)
