from rest_framework import serializers

from .models import Cohort, CohortMembership, CohortTeacher


class CohortSerializer(serializers.ModelSerializer):
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cohort
        fields = (
            "id",
            "branch",
            "department",
            "primary_teacher",
            "name",
            "level",
            "capacity",
            "start_date",
            "end_date",
            "is_archived",
            "student_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class CohortMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = CohortMembership
        fields = ("id", "cohort", "student", "start_date", "end_date", "is_active", "created_at")
        read_only_fields = ("created_at",)


class CohortTeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = CohortTeacher
        fields = ("id", "cohort", "teacher", "created_at")
        read_only_fields = ("created_at",)
