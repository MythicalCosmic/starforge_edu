from rest_framework import serializers

from .models import AcademicItem


class AcademicItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
