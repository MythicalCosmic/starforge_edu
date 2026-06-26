from __future__ import annotations

from rest_framework import serializers

from apps.campaigns.models import Campaign, CampaignRecipient
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


class CreateCampaignSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    message = serializers.CharField()
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    # Audience filter: {status?, cohort?}. The branch is the campaign's own branch.
    segment = serializers.JSONField(required=False, default=dict)
