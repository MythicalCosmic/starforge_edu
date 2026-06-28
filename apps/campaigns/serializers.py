from __future__ import annotations

from rest_framework import serializers

from apps.campaigns.models import Campaign, CampaignRecipient, DoNotContact, MessageTemplate
from apps.org.models import Branch


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = (
            "id",
            "name",
            "message",
            "segment",
            "branch",
            "status",
            "total",
            "sent_count",
            "failed_count",
            "skipped_count",
            "created_by",
            "sent_by",
            "sent_at",
            "created_at",
        )
        read_only_fields = fields


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignRecipient
        fields = ("id", "student", "phone", "status", "error", "sent_at")
        read_only_fields = fields


class DoNotContactSerializer(serializers.ModelSerializer):
    # Declared explicitly (no auto UniqueValidator) so a duplicate maps to the service's
    # clean 409 already_opted_out instead of a generic 400 field error.
    phone = serializers.CharField(max_length=32)

    class Meta:
        model = DoNotContact
        fields = ("id", "phone", "reason", "created_by", "created_at")
        read_only_fields = ("id", "created_by", "created_at")

    def validate_phone(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("A phone number is required.")
        # Every User.phone is stored E.164 (core.validators.normalize_phone, the single
        # chokepoint). Canonicalize the opt-out the SAME way, or a do-not-contact typed
        # as "998..." / with spaces would never byte-match the E.164 phone and the family
        # would still be texted. normalize_phone raises a clean 400 invalid_phone on junk.
        from core.validators import normalize_phone

        return normalize_phone(value)


class CreateCampaignSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    # The message text — OR a reusable template whose body is used (F10-2). Exactly one.
    message = serializers.CharField(required=False, allow_blank=True)
    template = serializers.PrimaryKeyRelatedField(
        queryset=MessageTemplate.objects.filter(is_active=True), required=False, allow_null=True
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    # Audience filter: {status?, cohort?}. The branch is the campaign's own branch.
    segment = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        message = (attrs.get("message") or "").strip()
        template = attrs.get("template")
        # Exactly one: reject BOTH (else the typed message would be silently dropped in
        # favour of the template body) and reject NEITHER.
        if message and template is not None:
            raise serializers.ValidationError("Provide a message OR a template, not both.")
        if not message and template is None:
            raise serializers.ValidationError("Provide a message or pick a template.")
        # A picked template supplies the text; its body must not be empty.
        if template is not None and not (template.body or "").strip():
            raise serializers.ValidationError("That template has no body yet.")
        attrs["message"] = template.body if template is not None else message
        return attrs


class MessageTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageTemplate
        fields = (
            "id",
            "name",
            "category",
            "purpose",
            "body",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "body", "created_by", "created_at", "updated_at")


class CreateTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    category = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    purpose = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class UpdateTemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    category = serializers.CharField(max_length=40, required=False, allow_blank=True)
    purpose = serializers.CharField(max_length=500, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
