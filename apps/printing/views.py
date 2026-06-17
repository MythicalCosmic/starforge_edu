"""Printing views (D4-LD-3/7).

Two surfaces:
- **Staff** (JWT, ``printing:read``/``printing:write``): manage jobs, printers,
  agents through ``TenantSafeModelViewSet``.
- **Agent** (``BranchAgentAuthentication`` + ``IsBranchAgent``, no JWT): claim a
  job and report status. These are ``APIView``s — no User, no role matrix — but
  they still assert a tenant context (host-resolved schema).
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.printing import selectors, services
from apps.printing.authentication import BranchAgentAuthentication, IsBranchAgent
from apps.printing.serializers import (
    AgentClaimResponseSerializer,
    AgentStatusUpdateSerializer,
    BranchAgentCreatedSerializer,
    BranchAgentCreateSerializer,
    BranchAgentReadSerializer,
    PrinterReadSerializer,
    PrinterWriteSerializer,
    PrintJobCreateSerializer,
    PrintJobReadSerializer,
)
from core.permissions import default_perms
from core.viewsets import TenantSafeModelViewSet, assert_tenant_context
from infrastructure.storage.s3_client import presign_download


# --------------------------------------------------------------------------- #
# Staff: PrintJob
# --------------------------------------------------------------------------- #
class PrintJobViewSet(TenantSafeModelViewSet):
    resource = "printing"
    required_perms = default_perms("printing")
    object_scope = "branch"
    serializer_class = PrintJobReadSerializer
    filterset_fields = ("status", "source", "branch")
    ordering_fields = ("created_at",)
    ordering = ("-created_at",)
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return selectors.print_jobs()

    @extend_schema(
        summary="Create a print job (staff path; service applies quota)",
        request=PrintJobCreateSerializer,
        responses={
            201: PrintJobReadSerializer,
            403: OpenApiResponse(description="forbidden envelope"),
            422: OpenApiResponse(description="print_quota_exceeded envelope"),
        },
        tags=["printing"],
        examples=[
            OpenApiExample(
                "Print a report",
                value={
                    "source": "report",
                    "source_id": 12,
                    "payload_s3_key": "demo/reports/12.pdf",
                    "branch": 1,
                    "pages": 3,
                    "copies": 1,
                },
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        ser = PrintJobCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Branch-scope the create like every other write path (mirror perform_create).
        self._assert_create_branch(data["branch"])
        job = services.enqueue_print(
            source=data["source"],
            source_id=data["source_id"],
            payload_s3_key=data["payload_s3_key"],
            branch_id=data["branch"],
            requested_by=request.user,
            pages=data["pages"],
            copies=data["copies"],
            color=data["color"],
            duplex=data["duplex"],
            cohort_id=data["cohort"],
        )
        return Response(PrintJobReadSerializer(job).data, status=status.HTTP_201_CREATED)

    def _assert_create_branch(self, branch_id: int) -> None:
        from core.exceptions import PermissionException
        from core.permissions import Role, get_role_memberships

        user = self.request.user
        if getattr(user, "is_superuser", False):
            return
        memberships = get_role_memberships(self.request)
        if any(m.role == Role.DIRECTOR for m in memberships):
            return
        if branch_id not in {m.branch_id for m in memberships}:
            raise PermissionException(code="out_of_scope")


# --------------------------------------------------------------------------- #
# Staff: Printer
# --------------------------------------------------------------------------- #
class PrinterViewSet(TenantSafeModelViewSet):
    resource = "printing"
    required_perms = default_perms("printing")
    object_scope = "branch"
    filterset_fields = ("branch", "is_active")
    ordering_fields = ("name",)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return selectors.printers()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return PrinterWriteSerializer
        return PrinterReadSerializer

    @extend_schema(summary="List printers", responses={200: PrinterReadSerializer}, tags=["printing"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


# --------------------------------------------------------------------------- #
# Staff: BranchAgent (register => token shown once)
# --------------------------------------------------------------------------- #
class BranchAgentViewSet(TenantSafeModelViewSet):
    resource = "printing"
    required_perms = {**default_perms("printing"), "revoke": "printing:write"}
    object_scope = "branch"
    serializer_class = BranchAgentReadSerializer
    filterset_fields = ("branch",)
    ordering_fields = ("name",)
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return selectors.agents()

    @extend_schema(
        summary="Register a branch agent (returns the raw token once)",
        request=BranchAgentCreateSerializer,
        responses={201: BranchAgentCreatedSerializer, 403: OpenApiResponse(description="forbidden")},
        tags=["printing"],
        examples=[OpenApiExample("Register", value={"branch": 1, "name": "Front desk agent"})],
    )
    def create(self, request, *args, **kwargs):
        ser = BranchAgentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        branch_id = ser.validated_data["branch"]
        self._assert_create_branch(branch_id)
        agent, raw_token = services.register_agent(
            branch_id=branch_id, name=ser.validated_data["name"], created_by=request.user
        )
        payload = BranchAgentCreatedSerializer(agent).data
        payload["token"] = raw_token
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Revoke a branch agent token", responses={200: BranchAgentReadSerializer}, tags=["printing"]
    )
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        agent = self.get_object()
        agent = services.revoke_agent(agent_id=agent.pk)
        return Response(BranchAgentReadSerializer(agent).data)

    def _assert_create_branch(self, branch_id: int) -> None:
        from core.exceptions import PermissionException
        from core.permissions import Role, get_role_memberships

        user = self.request.user
        if getattr(user, "is_superuser", False):
            return
        memberships = get_role_memberships(self.request)
        if any(m.role == Role.DIRECTOR for m in memberships):
            return
        if branch_id not in {m.branch_id for m in memberships}:
            raise PermissionException(code="out_of_scope")


# --------------------------------------------------------------------------- #
# Agent endpoints (no JWT, no role matrix — BranchAgent token only)
# --------------------------------------------------------------------------- #
class AgentClaimView(APIView):
    """POST /printing/agent/claim/ — atomically claim the oldest queued job."""

    authentication_classes = [BranchAgentAuthentication]
    permission_classes = [IsBranchAgent]

    @extend_schema(
        summary="Agent claims the oldest queued job for its branch",
        request=None,
        responses={
            200: AgentClaimResponseSerializer,
            204: OpenApiResponse(description="queue empty"),
            401: OpenApiResponse(description="agent_token_invalid envelope"),
        },
        tags=["printing"],
    )
    def post(self, request):
        assert_tenant_context()
        agent = request.auth
        job = services.claim_job(agent=agent)
        if job is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        download_url = presign_download(job.payload_s3_key)
        return Response(
            {"job": PrintJobReadSerializer(job).data, "download_url": download_url},
            status=status.HTTP_200_OK,
        )


class AgentJobStatusView(APIView):
    """POST /printing/agent/jobs/<id>/status/ — report a transition."""

    authentication_classes = [BranchAgentAuthentication]
    permission_classes = [IsBranchAgent]

    @extend_schema(
        summary="Agent reports a print job status transition",
        request=AgentStatusUpdateSerializer,
        responses={
            200: PrintJobReadSerializer,
            401: OpenApiResponse(description="agent_token_invalid envelope"),
            404: OpenApiResponse(description="cross-branch / unknown job"),
            409: OpenApiResponse(description="invalid_transition envelope"),
        },
        tags=["printing"],
    )
    def post(self, request, job_id: int):
        assert_tenant_context()
        agent = request.auth
        ser = AgentStatusUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        job = services.update_job_status(
            agent=agent,
            job_id=job_id,
            status=ser.validated_data["status"],
            error=ser.validated_data["error"],
            pages_printed=ser.validated_data["pages_printed"],
        )
        return Response(PrintJobReadSerializer(job).data, status=status.HTTP_200_OK)
