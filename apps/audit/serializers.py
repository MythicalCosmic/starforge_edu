from rest_framework import serializers

from .models import AuditItem


class AuditItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
