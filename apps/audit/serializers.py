from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id",
            "actor",
            "action",
            "resource_type",
            "resource_id",
            "changes",
            "ip",
            "user_agent",
            "created_at",
        )
        read_only_fields = fields
