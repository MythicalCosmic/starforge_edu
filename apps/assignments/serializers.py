from rest_framework import serializers

from .models import AssignmentItem


class AssignmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssignmentItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
