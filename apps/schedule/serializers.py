from rest_framework import serializers

from .models import ScheduleItem


class ScheduleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
