from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationTemplate,
)


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only feed item — clients never POST notifications directly."""

    class Meta:
        model = Notification
        fields = (
            "id",
            "event_type",
            "title",
            "body",
            "data",
            "read_at",
            "created_at",
        )
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("event_type", "channel", "enabled")


class PreferenceBulkUpsertSerializer(serializers.Serializer):
    """Body for the bulk preferences PUT: ``{preferences: [{event_type, channel, enabled}]}``."""

    preferences = NotificationPreferenceSerializer(many=True)


class NotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = (
            "id",
            "event_type",
            "channel",
            "locale",
            "subject",
            "body",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class AnnouncementSerializer(serializers.Serializer):
    """Body for POST /notifications/announcements/."""

    cohort = serializers.IntegerField()
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()
