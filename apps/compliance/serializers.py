from __future__ import annotations

from rest_framework import serializers

from apps.compliance.models import Rule


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = (
            "id",
            "title",
            "body",
            "version",
            "applies_to_roles",
            "is_active",
            "created_at",
            "updated_at",
        )
        # version is service-managed (auto-bumps on body change).
        read_only_fields = ("id", "version", "created_at", "updated_at")
