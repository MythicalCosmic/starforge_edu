from rest_framework import serializers

from .models import ReportItem


class ReportItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
