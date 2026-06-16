from __future__ import annotations

from rest_framework import serializers

from apps.academics.models import Exam, ExamResult, Grade, Subject, Transcript
from apps.schedule.models import Term
from apps.students.models import StudentProfile


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ("id", "name", "code", "department", "description", "is_active")


class ExamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = (
            "id",
            "subject",
            "cohort",
            "term",
            "type",
            "title",
            "exam_date",
            "max_score",
            "weight",
            "is_published",
            "published_at",
        )
        read_only_fields = ("is_published", "published_at")


class ExamResultSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)

    class Meta:
        model = ExamResult
        fields = ("id", "exam", "student", "student_name", "score", "note", "graded_by", "graded_at")
        read_only_fields = fields


class ResultEntrySerializer(serializers.Serializer):
    """One row of the bulk-results payload."""

    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    score = serializers.DecimalField(max_digits=6, decimal_places=2)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CsvImportSerializer(serializers.Serializer):
    file = serializers.FileField()


class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = Grade
        fields = (
            "id",
            "student",
            "student_name",
            "subject",
            "subject_name",
            "term",
            "value_raw",
            "value_display",
            "components",
            "is_published",
            "published_at",
            "computed_at",
        )
        read_only_fields = fields


class RecomputeSerializer(serializers.Serializer):
    cohort = serializers.IntegerField()
    subject = serializers.IntegerField()
    term = serializers.IntegerField()
    publish = serializers.BooleanField(required=False, default=False)


class TranscriptCreateSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    term = serializers.PrimaryKeyRelatedField(queryset=Term.objects.all(), required=False, allow_null=True)


class TranscriptSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Transcript
        fields = ("id", "student", "term", "status", "download_url", "error", "generated_at", "created_at")
        read_only_fields = fields

    def get_download_url(self, obj) -> str | None:
        from apps.academics.services import presign_transcript

        return presign_transcript(obj)
