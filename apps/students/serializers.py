from rest_framework import serializers

from .models import StudentItem


class StudentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentItem
        fields = ("id", "name", "notes", "is_active", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")
