"""Audit serializers (D3-D-4). Read-only — there is no write path."""

from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "actor",
            "actor_username",
            "actor_repr",
            "action",
            "resource_type",
            "resource_id",
            "before",
            "after",
            "ip",
            "user_agent",
            "created_at",
        )
        read_only_fields = fields
