from __future__ import annotations

from rest_framework import serializers

from apps.assignments.models import Assignment, Submission, SubmissionGrade


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = (
            "id",
            "cohort",
            "title",
            "description",
            "due_at",
            "attachments",
            "rubric",
            "max_score",
            "max_resubmits",
            "status",
            "published_at",
            "created_at",
        )
        read_only_fields = ("status", "published_at", "created_at")

    def validate_rubric(self, rubric):
        if not isinstance(rubric, list):
            raise serializers.ValidationError("Rubric must be a list of criteria.")
        for row in rubric:
            if not isinstance(row, dict) or "criterion" not in row or "max_points" not in row:
                raise serializers.ValidationError("Each rubric row needs 'criterion' and 'max_points'.")
            if not isinstance(row["criterion"], str) or not str(row["criterion"]).strip():
                raise serializers.ValidationError("'criterion' must be a non-empty string.")
            if not isinstance(row["max_points"], int) or row["max_points"] < 0:
                raise serializers.ValidationError("'max_points' must be a non-negative integer.")
        return rubric


class SubmissionGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionGrade
        fields = ("submission", "score", "rubric_scores", "feedback", "ai_feedback", "graded_by", "graded_at")
        read_only_fields = fields


class SubmissionSerializer(serializers.ModelSerializer):
    # SerializerMethodField (not a nested field) so a not-yet-graded submission
    # serializes to null without raising RelatedObjectDoesNotExist; relies on the
    # selector's select_related("grade") to avoid an N+1.
    grade = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = (
            "id",
            "assignment",
            "student",
            "text",
            "attachments",
            "submitted_at",
            "is_late",
            "attempt_number",
            "status",
            "grade",
        )
        read_only_fields = fields

    def get_grade(self, obj) -> dict | None:
        try:
            grade = obj.grade
        except SubmissionGrade.DoesNotExist:
            return None
        return SubmissionGradeSerializer(grade).data


class SubmissionCreateSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=True, default="")
    attachment_keys = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class GradeInputSerializer(serializers.Serializer):
    score = serializers.DecimalField(max_digits=6, decimal_places=2)
    rubric_scores = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    feedback = serializers.CharField(required=False, allow_blank=True, default="")


class UploadUrlSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127, required=False, default="application/octet-stream")
    size_bytes = serializers.IntegerField(min_value=1)
