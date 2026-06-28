from __future__ import annotations

from django.db import IntegrityError
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.campaigns import services
from apps.campaigns.models import Campaign, CampaignRecipient, DoNotContact, MessageTemplate
from apps.campaigns.serializers import (
    CampaignRecipientSerializer,
    CampaignSerializer,
    CreateCampaignSerializer,
    CreateTemplateSerializer,
    DoNotContactSerializer,
    MessageTemplateSerializer,
    UpdateTemplateSerializer,
)
from core.exceptions import ConflictException, PermissionException
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


class DoNotContactViewSet(TenantSafeModelViewSet):
    """The SMS do-not-contact list (campaign consent). A phone here is suppressed from
    every campaign — added when a family asks to stop being texted. Reading + managing
    it is a campaign action (campaign:read / campaign:write); deletion is how a family
    is re-subscribed if they opt back in."""

    serializer_class = DoNotContactSerializer
    resource = "campaign"
    required_perms = {
        "list": "campaign:read",
        "retrieve": "campaign:read",
        "create": "campaign:write",
        "destroy": "campaign:write",
    }
    http_method_names = ["get", "post", "delete", "head", "options"]
    queryset = DoNotContact.objects.select_related("created_by").all()
    filterset_fields = ("phone",)
    ordering_fields = ("created_at",)
    search_fields = ("phone",)

    @extend_schema(request=DoNotContactSerializer, responses={201: DoNotContactSerializer}, tags=["campaign"])
    def create(self, request, *args, **kwargs):
        ser = DoNotContactSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            entry = DoNotContact.objects.create(
                phone=ser.validated_data["phone"],
                reason=ser.validated_data.get("reason", ""),
                created_by=request.user,
            )
        except IntegrityError:
            # the unique(phone) constraint — already opted out is a clean 409, not a 500
            raise ConflictException(
                _("That phone is already on the do-not-contact list."), code="already_opted_out"
            ) from None
        return Response(DoNotContactSerializer(entry).data, status=status.HTTP_201_CREATED)


class MessageTemplateViewSet(TenantSafeModelViewSet):
    """Reusable, AI-draftable message templates (F10-2). Staff (campaign:write) create a
    template + purpose, optionally have the AI draft the body (generate), edit it, and
    reuse it when composing a campaign. campaign:read to list/read."""

    serializer_class = MessageTemplateSerializer
    resource = "campaign"
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_perms = {
        "list": "campaign:read",
        "retrieve": "campaign:read",
        "create": "campaign:write",
        "partial_update": "campaign:write",
        "generate": "campaign:write",
    }
    queryset = MessageTemplate.objects.select_related("created_by").all()
    filterset_fields = ("category", "is_active")
    search_fields = ("name", "category")
    ordering_fields = ("created_at", "name")

    @extend_schema(request=CreateTemplateSerializer, responses={201: MessageTemplateSerializer}, tags=["campaign"])
    def create(self, request, *args, **kwargs):
        ser = CreateTemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tpl = services.create_template(
            name=ser.validated_data["name"],
            category=ser.validated_data.get("category", ""),
            purpose=ser.validated_data.get("purpose", ""),
            created_by=request.user,
        )
        return Response(MessageTemplateSerializer(tpl).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=UpdateTemplateSerializer, responses={200: MessageTemplateSerializer}, tags=["campaign"])
    def partial_update(self, request, *args, **kwargs):
        tpl = self.get_object()
        ser = UpdateTemplateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        tpl = services.update_template(template_id=tpl.pk, fields=ser.validated_data)
        return Response(MessageTemplateSerializer(tpl).data)

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="{request_id, status} — poll /ai/requests/{id}/")},
        tags=["campaign"],
    )
    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        """F10-2: have the AI draft this template's body from its purpose (async). The
        AI drafts it once (the request is idempotent on the template); the staff edits
        the result before using it."""
        ai_request = services.request_template_generation(
            template=self.get_object(), requested_by=request.user
        )
        return Response(
            {"request_id": ai_request.pk, "status": ai_request.status}, status=status.HTTP_202_ACCEPTED
        )
