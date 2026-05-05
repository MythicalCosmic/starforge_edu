from rest_framework import serializers

from .models import ParentItem


class ParentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParentItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
