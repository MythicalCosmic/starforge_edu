from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.campaigns import services
from apps.campaigns.models import Campaign, CampaignRecipient
from apps.campaigns.serializers import (
    CampaignRecipientSerializer,
    CampaignSerializer,
    CreateCampaignSerializer,
)
from core.exceptions import PermissionException
from core.permissions import Role, get_role_memberships, get_user_roles
from core.viewsets import TenantSafeModelViewSet


class CampaignViewSet(TenantSafeModelViewSet):
    """SMS campaigns (F10-1): build a message against a student segment, then send it
    once to every recipient via the Eskiz client. The campaign + its recipients are the
    audit trail of who was contacted and whether it landed."""

    serializer_class = CampaignSerializer
    resource = "campaign"
    required_perms = {
        "list": "campaign:read",
        "retrieve": "campaign:read",
        "create": "campaign:write",
        "send": "campaign:send",
        "recipients": "campaign:read",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ("status", "branch")
    ordering_fields = ("created_at",)

    def _assert_branch_in_scope(self, branch) -> None:
        """A campaign is bound to a branch the caller belongs to — reception at branch A
        can't blast branch B's families. The director may run a centre-wide (no branch)
        or any-branch campaign."""
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return
        if branch is None:
            raise PermissionException(_("Choose a branch for the campaign."), code="branch_required")
        my = {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}
        if branch.id not in my:
            raise PermissionException(
                _("You can only run a campaign for your own branch."), code="branch_out_of_scope"
            )

    def get_queryset(self):
        qs = Campaign.objects.select_related("branch", "created_by", "sent_by")
        user = self.request.user
        roles = get_user_roles(self.request)
        if user.is_superuser or Role.DIRECTOR in roles:
            return qs
        my = {m.branch_id for m in get_role_memberships(self.request) if m.branch_id}
        return qs.filter(branch_id__in=my)

    @extend_schema(request=CreateCampaignSerializer, responses={201: CampaignSerializer}, tags=["campaign"])
    def create(self, request, *args, **kwargs):
        ser = CreateCampaignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        self._assert_branch_in_scope(ser.validated_data.get("branch"))
        campaign = services.create_campaign(
            name=ser.validated_data["name"],
            message=ser.validated_data["message"],
            segment=ser.validated_data.get("segment"),
            created_by=request.user,
            branch=ser.validated_data.get("branch"),
        )
        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: CampaignSerializer}, tags=["campaign"])
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        campaign = services.send_campaign(campaign_id=self.get_object().pk, actor=request.user)
        return Response(CampaignSerializer(campaign).data)

    @extend_schema(responses={200: CampaignRecipientSerializer(many=True)}, tags=["campaign"])
    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        rows = CampaignRecipient.objects.filter(campaign=self.get_object()).select_related("student")
        return Response(CampaignRecipientSerializer(rows, many=True).data)
