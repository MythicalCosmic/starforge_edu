from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.services import register_device
from core.permissions import DenyWriteForReadOnlyToken, RolePermission
from core.utils import user_agent

from .models import Device, User
from .serializers import DeviceRegisterSerializer, DeviceSerializer, UserSerializer


class UserViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.prefetch_related("role_memberships").all()
    serializer_class = UserSerializer
    resource = "users"  # list/retrieve -> users:read (TD-5)

    def get_permissions(self):
        # `me` is self-scoped: any authenticated user hydrates their own profile,
        # regardless of role. Directory list/retrieve require `users:read`.
        # DenyWriteForReadOnlyToken blocks the PATCH `me` write under a read-only
        # impersonation token (this viewset isn't a TenantSafe base, D4-LE-4).
        if getattr(self, "action", None) == "me":
            return [IsAuthenticated(), DenyWriteForReadOnlyToken()]
        return [RolePermission(), DenyWriteForReadOnlyToken()]

    @extend_schema(
        summary="Current user + role memberships (GET) or update own profile (PATCH)",
        description=(
            "GET hydrates the caller's own profile. PATCH updates self-service "
            "fields only — notably ``preferred_language`` (drives the localized "
            "notification template variant, D4-LF-3). Read-only fields "
            "(username/roles/is_staff) are ignored by the serializer."
        ),
        request=UserSerializer,
        responses=UserSerializer,
        tags=["users"],
    )
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        if request.method == "PATCH":
            # Self-scoped write: always the caller's own row, partial update so a
            # client can send just {"preferred_language": "ru"}. Read-only fields
            # (username/is_staff/roles) are declared read_only on the serializer.
            serializer = self.get_serializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(self.get_serializer(request.user).data)


class DeviceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Self-scoped device registry (push tokens). No role code: the queryset is
    filtered to ``request.user`` and every action requires only authentication
    (D1-LC-9)."""

    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated, DenyWriteForReadOnlyToken]

    def get_queryset(self):
        # IsAuthenticated guarantees a concrete user here.
        return Device.objects.filter(user=self.request.user, revoked_at__isnull=True)  # type: ignore[misc]

    @extend_schema(
        summary="Register or update the current device + push token",
        request=DeviceRegisterSerializer,
        responses={201: DeviceSerializer},
        tags=["users"],
    )
    def create(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = register_device(
            user=request.user,
            user_agent=user_agent(request),
            **serializer.validated_data,
        )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Revoke a device (soft delete)",
        responses={204: OpenApiResponse(description="Device revoked.")},
        tags=["users"],
    )
    def destroy(self, request, pk=None):
        device = get_object_or_404(self.get_queryset(), pk=pk)
        device.revoked_at = timezone.now()
        device.save(update_fields=["revoked_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
