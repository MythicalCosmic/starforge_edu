from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.services import register_device
from core.permissions import RolePermission
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
        if getattr(self, "action", None) == "me":
            return [IsAuthenticated()]
        return [RolePermission()]

    @extend_schema(summary="Current user + role memberships", responses=UserSerializer, tags=["users"])
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        return Response(self.get_serializer(request.user).data)


class DeviceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Self-scoped device registry (push tokens). No role code: the queryset is
    filtered to ``request.user`` and every action requires only authentication
    (D1-LC-9)."""

    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated]

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
