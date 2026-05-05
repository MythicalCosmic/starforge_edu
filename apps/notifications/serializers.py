from rest_framework import serializers

from .models import NotificationItem


class NotificationItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
