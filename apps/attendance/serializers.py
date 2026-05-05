from rest_framework import serializers

from .models import AttendanceItem


class AttendanceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
