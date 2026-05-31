from rest_framework import serializers

from .models import TeacherProfile


class TeacherProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = (
            "id",
            "user",
            "full_name",
            "department",
            "hire_date",
            "employment_type",
            "subjects",
            "qualifications",
            "payout_percent",
            "hourly_rate",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_full_name(self, obj: TeacherProfile) -> str:
        return obj.user.get_full_name()
