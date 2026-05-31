from rest_framework import serializers

from .models import StudentProfile


class StudentProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentProfile
        fields = (
            "id",
            "user",
            "full_name",
            "branch",
            "student_id",
            "status",
            "enrollment_date",
            "academic_level",
            "medical_notes",
            "emergency_contacts",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("student_id", "created_at", "updated_at")

    def get_full_name(self, obj: StudentProfile) -> str:
        return obj.user.get_full_name()
