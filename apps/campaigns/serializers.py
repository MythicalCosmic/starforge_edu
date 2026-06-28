from __future__ import annotations

from rest_framework import serializers

from apps.campaigns.models import Campaign, CampaignRecipient, DoNotContact
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
    message = serializers.CharField()
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    # Audience filter: {status?, cohort?}. The branch is the campaign's own branch.
    segment = serializers.JSONField(required=False, default=dict)
