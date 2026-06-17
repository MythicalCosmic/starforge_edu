"""Platform control-center API (D4-LE, TD-10) — PUBLIC schema, staff-only.

These views run on the public schema (mounted in config/urls_public.py under
/api/v1/platform/). They are PLAIN DRF viewsets/APIViews with
`permission_classes = [IsAdminUser]` — NOT `TenantSafeModelViewSet`, whose
`initial()` raises TenantContextMissing on the public schema. Platform staff
exist as public-schema users per TD-3; a TENANT-minted JWT 401s here because
its user_id row does not exist in the public users table.

The resolve endpoint (TD-19) is the single AllowAny exception (anon-throttled).
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.billing import selectors as billing_selectors
from core.exceptions import ValidationException

from . import services
from .models import Center
from .serializers import (
    CenterCreateSerializer,
    CenterSerializer,
    CenterUpdateSerializer,
    DomainCreateSerializer,
    DomainSerializer,
    ExtendTrialSerializer,
    ImpersonateSerializer,
    ImpersonationTokenSerializer,
    ResolveSerializer,
    SuspendSerializer,
    UsageResponseSerializer,
)


class CenterViewSet(viewsets.ModelViewSet):
    """Full Center lifecycle (D4-LE-1/2/4). Platform-staff only (TD-3).

    Mounted at /api/v1/platform/centers/. Creation delegates to
    `services.provision_center` (which builds the schema + seeds CenterSettings);
    lifecycle transitions (suspend/activate/extend-trial) are dedicated actions
    so each one is audited via a PlatformEvent. DELETE is intentionally absent —
    centers are archived (a management command), never hard-deleted via the API.
    """

    queryset = Center.objects.prefetch_related("domains").all()
    serializer_class = CenterSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ("is_active", "on_trial")
    search_fields = ("name", "slug", "schema_name", "contact_email")
    ordering_fields = ("name", "created_at")
    # No raw DELETE: archival is an explicit operation, not a CRUD destroy.
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(
        summary="Provision a new Center (creates its schema + settings)",
        request=CenterCreateSerializer,
        responses={
            201: CenterSerializer,
            400: OpenApiResponse(description="slug_taken / validation envelope"),
        },
        tags=["platform"],
        examples=[
            OpenApiExample(
                "New center",
                value={"name": "Demo Academy", "slug": "demo2", "primary_domain": "demo2.starforge.uz"},
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        ser = CenterCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        center = services.provision_center(**ser.validated_data)
        services.record_platform_event(
            actor=request.user,
            center=center,
            event=services.PlatformEvent.Event.CENTER_CREATED,
            payload={"slug": center.slug},
        )
        return Response(CenterSerializer(center).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update a Center's contact metadata",
        request=CenterUpdateSerializer,
        responses={200: CenterSerializer},
        tags=["platform"],
    )
    def partial_update(self, request, *args, **kwargs):
        center = self.get_object()
        ser = CenterUpdateSerializer(instance=center, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(CenterSerializer(center).data)

    @extend_schema(
        summary="Suspend a Center (→ tenant API 503/402 paywall)",
        request=SuspendSerializer,
        responses={200: CenterSerializer},
        tags=["platform"],
    )
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        ser = SuspendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        center = services.suspend_center(
            self.get_object(), actor=request.user, reason=ser.validated_data["reason"]
        )
        return Response(CenterSerializer(center).data)

    @extend_schema(
        summary="Re-activate a suspended Center (→ tenant API 200)",
        request=None,
        responses={200: CenterSerializer},
        tags=["platform"],
    )
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        center = services.activate_center(self.get_object(), actor=request.user)
        return Response(CenterSerializer(center).data)

    @extend_schema(
        summary="Extend a Center's trial by N days",
        request=ExtendTrialSerializer,
        responses={200: CenterSerializer},
        tags=["platform"],
        examples=[OpenApiExample("Extend 14 days", value={"days": 14})],
    )
    @action(detail=True, methods=["post"], url_path="extend-trial")
    def extend_trial(self, request, pk=None):
        ser = ExtendTrialSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        center = services.extend_trial(self.get_object(), days=ser.validated_data["days"], actor=request.user)
        return Response(CenterSerializer(center).data)

    @extend_schema(
        summary="Per-center usage time series (snapshots + live DAU today)",
        parameters=[OpenApiParameter("days", int, description="Look-back window (default 30, max 365).")],
        responses={200: UsageResponseSerializer},
        tags=["platform"],
    )
    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        center = self.get_object()
        days = self._parse_days(request.query_params.get("days"))
        payload = billing_selectors.usage_series(center=center, days=days)
        return Response(UsageResponseSerializer(payload).data)

    @staticmethod
    def _parse_days(raw) -> int:
        if not raw:
            return 30
        try:
            days = int(raw)
        except (TypeError, ValueError):
            raise ValidationException("`days` must be an integer.", code="validation_error") from None
        if days < 1 or days > 365:
            raise ValidationException("`days` must be between 1 and 365.", code="validation_error")
        return days

    @extend_schema(
        summary="Mint a 10-minute read-only impersonation token (no refresh)",
        request=ImpersonateSerializer,
        responses={
            200: ImpersonationTokenSerializer,
            404: OpenApiResponse(description="user_not_found envelope"),
        },
        tags=["platform"],
        examples=[OpenApiExample("Impersonate user 7", value={"user_id": 7})],
    )
    @action(detail=True, methods=["post"])
    def impersonate(self, request, pk=None):
        ser = ImpersonateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        center = self.get_object()
        result = services.mint_impersonation_token(
            center=center, user_id=ser.validated_data["user_id"], impersonator=request.user
        )
        return Response(ImpersonationTokenSerializer(result).data)

    @extend_schema(
        summary="List or add a Center's domains",
        request=DomainCreateSerializer,
        responses={200: DomainSerializer(many=True), 201: DomainSerializer},
        tags=["platform"],
    )
    @action(detail=True, methods=["get", "post"], url_path="domains")
    def domains(self, request, pk=None):
        center = self.get_object()
        if request.method == "POST":
            serializer = DomainCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            domain = services.add_domain(
                center,
                domain=serializer.validated_data["domain"],
                is_primary=serializer.validated_data["is_primary"],
            )
            return Response(DomainSerializer(domain).data, status=status.HTTP_201_CREATED)
        return Response(DomainSerializer(center.domains.all(), many=True).data)

    @extend_schema(
        summary="Make one of a Center's domains primary",
        request=None,
        responses=DomainSerializer,
        tags=["platform"],
    )
    @action(
        detail=True,
        methods=["post"],
        # \d+ so non-numeric ids 404 at routing instead of ValueError → 500.
        url_path=r"domains/(?P<domain_id>\d+)/set-primary",
    )
    def set_primary(self, request, pk=None, domain_id=None):
        center = self.get_object()
        domain = services.set_primary_domain(center, int(domain_id))
        return Response(DomainSerializer(domain).data)


class ResolveView(APIView):
    """TD-19: GET /api/v1/platform/resolve/?slug=demo — AllowAny, anon-throttled.

    Returns the public bootstrap payload a frontend needs to point itself at the
    right tenant. Unknown / inactive / archived slug → 404 envelope.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [AnonRateThrottle]

    @extend_schema(
        summary="Resolve a center slug to its public bootstrap config (TD-19)",
        parameters=[OpenApiParameter("slug", str, required=True, description="Center slug, e.g. `demo`.")],
        responses={
            200: ResolveSerializer,
            404: OpenApiResponse(description="center_not_found envelope"),
        },
        tags=["platform"],
    )
    def get(self, request):
        slug = (request.query_params.get("slug") or "").strip()
        if not slug:
            raise ValidationException("Query param `slug` is required.", code="validation_error")
        payload = services.resolve_tenant(slug=slug)
        return Response(ResolveSerializer(payload).data)
