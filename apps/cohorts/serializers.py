from rest_framework import serializers

from .models import CohortItem


class CohortItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CohortItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
