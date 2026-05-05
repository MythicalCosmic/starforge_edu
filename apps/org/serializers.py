from rest_framework import serializers

from .models import Branch, Department


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "branch", "name", "slug", "description", "is_active", "created_at")
        read_only_fields = ("created_at",)


class BranchSerializer(serializers.ModelSerializer):
    departments = DepartmentSerializer(many=True, read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id",
            "name",
            "slug",
            "address",
            "phone",
            "timezone",
            "is_active",
            "departments",
            "created_at",
        )
        read_only_fields = ("created_at",)
