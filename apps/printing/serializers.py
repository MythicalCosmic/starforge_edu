from rest_framework import serializers

from .models import PrintingItem


class PrintingItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintingItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
