from rest_framework import serializers

from apps.cohorts.models import Cohort, CohortMembership, CohortTeacher
from apps.students.models import StudentProfile


class CohortTeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = CohortTeacher
        fields = ("id", "teacher", "role")
        read_only_fields = ("id",)


class CohortReadSerializer(serializers.ModelSerializer):
    co_teachers = CohortTeacherSerializer(many=True, read_only=True)

    class Meta:
        model = Cohort
        fields = (
            "id",
            "name",
            "branch",
            "department",
            "level",
            "start_date",
            "end_date",
            "capacity",
            "primary_teacher",
            "default_room",
            "is_archived",
            "co_teachers",
            "created_at",
        )
        read_only_fields = ("created_at",)


class CohortWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cohort
        fields = (
            "name",
            "branch",
            "department",
            "level",
            "start_date",
            "end_date",
            "capacity",
            "primary_teacher",
            "default_room",
            "is_archived",
        )

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and start > end:
            raise serializers.ValidationError({"end_date": "Must be on or after start_date."})
        return attrs


class CohortMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = CohortMembership
        fields = ("id", "cohort", "student", "start_date", "end_date", "moved_reason")
        read_only_fields = fields


class EnrollSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    start_date = serializers.DateField(required=False, allow_null=True)


class MoveStudentSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    reason = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
