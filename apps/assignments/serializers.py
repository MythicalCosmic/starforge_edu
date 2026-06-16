from __future__ import annotations

from typing import cast

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.assignments.models import Assignment, Submission, SubmissionGrade
from apps.cohorts.models import Cohort
from core.exceptions import UnprocessableEntity


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Writes are scoped like reads: a non-staff TEACHER may only create/repoint
        # an assignment into a cohort they teach. Otherwise an out-of-scope cohort
        # PK 400s here, closing the scoped-reads/unscoped-writes asymmetry (mirrors
        # ContentUploadUrlSerializer + academics scoped_exams). Director/HoD and
        # superuser keep the default tenant-wide queryset. None context (e.g. schema
        # generation) leaves the default queryset untouched.
        from apps.assignments.selectors import STAFF_ROLES, _cohorts_taught_by
        from core.permissions import Role, get_user_roles

        request = self.context.get("request")
        if request is None or getattr(request, "user", None) is None:
            return
        user = request.user
        if getattr(user, "is_superuser", False):
            return
        roles = get_user_roles(request)
        if roles & STAFF_ROLES:
            return
        cohort_field = cast(serializers.PrimaryKeyRelatedField, self.fields["cohort"])
        if Role.TEACHER in roles:
            cohort_field.queryset = Cohort.objects.filter(id__in=_cohorts_taught_by(user))
        else:
            cohort_field.queryset = Cohort.objects.none()

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

    def validate(self, attrs):
        # Reject a rubric whose Σ max_points exceeds max_score at authoring time
        # (create/update), not silently at grade time — otherwise every grading
        # attempt would fail permanently with rubric_exceeds_max_score. The
        # grade-time check is kept as a defence-in-depth backstop.
        rubric = attrs.get("rubric", getattr(self.instance, "rubric", None)) or []
        max_score = attrs.get("max_score", getattr(self.instance, "max_score", None))
        if max_score is not None and rubric:
            rubric_cap = sum(int(row.get("max_points", 0)) for row in rubric)
            if rubric_cap > max_score:
                # 422 (not 400) — the input is well-formed but the rubric cannot
                # be acted on; mirrors the grade-time rubric_exceeds_max_score
                # code so clients branch uniformly.
                raise UnprocessableEntity(
                    _("The rubric's total points exceed the assignment's max score."),
                    code="rubric_exceeds_max_score",
                    fields={"rubric": [f"Σ max_points {rubric_cap} > max_score {max_score}."]},
                )
        return attrs


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
