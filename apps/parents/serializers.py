from rest_framework import serializers

from .models import Guardian, ParentProfile


class ParentProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = ParentProfile
        fields = ("id", "user", "full_name", "occupation", "workplace", "notes", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def get_full_name(self, obj: ParentProfile) -> str:
        return obj.user.get_full_name()


class GuardianSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guardian
        fields = (
            "id",
            "parent",
            "student",
            "relationship",
            "is_primary",
            "can_pickup",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")
