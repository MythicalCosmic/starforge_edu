from rest_framework import serializers

from .models import FinanceItem


class FinanceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
