from __future__ import annotations

from django.db.models import Exists, OuterRef
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.messaging import services
from apps.messaging.models import Thread
from apps.messaging.serializers import (
    MessageSerializer,
    SendMessageSerializer,
    ThreadCreateSerializer,
    ThreadSerializer,
)
from apps.users.models import User
from core.exceptions import PermissionException, ValidationException
from core.permissions import _request_overrides, get_user_roles, has_permission_code
from core.viewsets import TenantSafeModelViewSet


class ThreadViewSet(TenantSafeModelViewSet):
    """In-app messaging (F4-4). You only ever see threads you participate in; opening
    a new thread is messaging:write, reading + posting in your threads is
    messaging:read. Messages are append-only (accountability)."""

    serializer_class = ThreadSerializer
    resource = "messaging"
    required_perms = {
        "list": "messaging:read",
        "retrieve": "messaging:read",
        "create": "messaging:write",
        "messages": "messaging:read",
        "read": "messaging:read",
    }
    http_method_names = ["get", "post", "head", "options"]
    ordering_fields = ("last_message_at", "created_at")

    def get_queryset(self):
        # Strict isolation: a user can only ever resolve threads they're a member of,
        # so every detail action (messages/read) is participant-gated via get_object.
        # request.user is always authenticated here (RolePermission denies anonymous).
        return (
            Thread.objects.filter(participants__user_id=self.request.user.pk)  # type: ignore[misc]
            .distinct()
            .select_related("branch", "created_by")
            .prefetch_related("participants", "messages")
        )

    @extend_schema(request=ThreadCreateSerializer, responses={201: ThreadSerializer}, tags=["messaging"])
    def create(self, request, *args, **kwargs):
        ser = ThreadCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ids = list(dict.fromkeys(ser.validated_data["participant_ids"]))
        # Participants must be active members of THIS center — never a membership-less
        # / cross-tenant user row. Exists() (not a `role_memberships__isnull=True`
        # filter, which a LEFT JOIN would let membership-less users slip through).
        from apps.users.models import RoleMembership

        active_member = RoleMembership.objects.filter(user_id=OuterRef("pk"), revoked_at__isnull=True)
        users = list(User.objects.filter(id__in=ids, is_active=True).filter(Exists(active_member)))
        if len(users) != len(ids):
            raise ValidationException(
                _("One or more participants were not found."), code="unknown_participant"
            )
        thread = services.create_thread(
            creator=request.user,
            participants=users,
            subject=ser.validated_data["subject"],
            first_body=ser.validated_data["first_body"],
            attachments=ser.validated_data["attachments"],
        )
        return Response(
            ThreadSerializer(thread, context={"request": request}).data, status=status.HTTP_201_CREATED
        )

    def _require_messaging_write(self, request) -> None:
        # The dual-method messages action is gated at messaging:read; posting a
        # message additionally requires messaging:write, so a center that revokes
        # write (A-2) actually makes a role read-only.
        if request.user.is_superuser:
            return
        if not has_permission_code(get_user_roles(request), "messaging:write", _request_overrides(request)):
            raise PermissionException(_("You cannot post messages."), code="permission_denied")

    @extend_schema(
        request=SendMessageSerializer,
        responses={200: MessageSerializer(many=True), 201: MessageSerializer},
        tags=["messaging"],
    )
    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(self, request, pk=None):
        thread = self.get_object()
        if request.method == "POST":
            self._require_messaging_write(request)
            ser = SendMessageSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            message = services.post_message(
                thread=thread,
                sender=request.user,
                body=ser.validated_data["body"],
                attachments=ser.validated_data["attachments"],
            )
            return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)
        qs = thread.messages.select_related("sender").all()
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(MessageSerializer(page, many=True).data)
        return Response(MessageSerializer(qs, many=True).data)

    @extend_schema(
        request=None, responses={200: OpenApiResponse(description="marked read")}, tags=["messaging"]
    )
    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, pk=None):
        services.mark_read(thread=self.get_object(), user=request.user)
        return Response({"status": "ok"})
