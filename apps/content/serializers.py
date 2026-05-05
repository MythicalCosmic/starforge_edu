from rest_framework import serializers

from .models import ContentItem


class ContentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
