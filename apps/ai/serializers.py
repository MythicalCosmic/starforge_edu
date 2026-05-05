from rest_framework import serializers

from .models import AiItem


class AiItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
