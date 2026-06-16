from __future__ import annotations

from rest_framework import serializers

from apps.attendance.models import AttendanceRecord
from apps.students.models import StudentProfile


class AttendanceRecordSerializer(serializers.ModelSerializer):
    # Flat denormalized labels resolved from the selector's
    # select_related("student__user", "lesson") — no extra query per row.
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = (
            "id",
            "student",
            "student_name",
            "lesson",
            "lesson_title",
            "status",
            "arrived_at",
            "note",
            "marked_by",
            "marked_at",
            "auto_marked",
            "created_at",
        )
        read_only_fields = fields


class AttendanceMarkEntrySerializer(serializers.Serializer):
    """One row of the `mark` payload. `status` may be overridden to `late` by the
    service when `arrived_at` exceeds the late threshold."""

    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices)
    arrived_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class AttendanceSummarySerializer(serializers.Serializer):
    present = serializers.IntegerField()
    absent = serializers.IntegerField()
    late = serializers.IntegerField()
    excused = serializers.IntegerField()
    percent_present = serializers.FloatField()
