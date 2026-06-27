from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.academics.models import Subject
from apps.org.models import Branch
from apps.placement.models import (
    PlacementAnswer,
    PlacementAttempt,
    PlacementQuestion,
    PlacementTest,
)
from apps.students.models import StudentProfile


class PlacementQuestionSerializer(serializers.ModelSerializer):
    """Also the add-question input (id/order read-only). Carries the answer key —
    staff-only, since only placement staff resolve a test in this iteration."""

    class Meta:
        model = PlacementQuestion
        fields = ("id", "prompt", "question_type", "options", "correct_answer", "points", "order")
        read_only_fields = ("id", "order")


class PlacementTestSerializer(serializers.ModelSerializer):
    questions = PlacementQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = PlacementTest
        fields = (
            "id",
            "title",
            "description",
            "status",
            "subject",
            "branch",
            "created_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "reject_reason",
            "created_at",
            "questions",
        )
        read_only_fields = (
            "id",
            "status",
            "branch",
            "created_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "reject_reason",
            "created_at",
            "questions",
        )


class PlacementTestCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), required=False, allow_null=True
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )


class PlacementTestUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), required=False, allow_null=True
    )


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError(_("Give a reason so the builder can fix it."))
        return value


class AttemptQuestionSerializer(serializers.ModelSerializer):
    """The questions a lead sees while sitting a test — deliberately WITHOUT
    correct_answer, so the answer key never leaves the server to a test-taker."""

    class Meta:
        model = PlacementQuestion
        fields = ("id", "prompt", "question_type", "options", "points", "order")
        read_only_fields = fields


class PlacementAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlacementAnswer
        fields = ("question", "response", "is_correct", "awarded_points")
        read_only_fields = fields


class PlacementAttemptSerializer(serializers.ModelSerializer):
    # source spans to the test's ordered questions; key-free (AttemptQuestionSerializer).
    questions = AttemptQuestionSerializer(source="test.questions", many=True, read_only=True)
    answers = PlacementAnswerSerializer(many=True, read_only=True)
    test_title = serializers.CharField(source="test.title", read_only=True)

    class Meta:
        model = PlacementAttempt
        fields = (
            "id",
            "test",
            "test_title",
            "student",
            "status",
            "score",
            "max_score",
            "level",
            "submitted_at",
            "created_at",
            "questions",
            "answers",
        )
        read_only_fields = fields


class LeadAnswerSerializer(serializers.ModelSerializer):
    """A test-taker sees their own responses but NOT per-question correctness:
    `response` + `is_correct` together reconstruct the answer key by inference
    (true_false / binary choice fully), which a lead could pass to other leads
    sitting the same reusable test. Leads get only {question, response}."""

    class Meta:
        model = PlacementAnswer
        fields = ("question", "response")
        read_only_fields = fields


class LeadAttemptSerializer(PlacementAttemptSerializer):
    # Narrower nested serializer (drops is_correct/awarded_points) for test-takers.
    answers = LeadAnswerSerializer(many=True, read_only=True)  # type: ignore[assignment]


class AssignAttemptSerializer(serializers.Serializer):
    test = serializers.PrimaryKeyRelatedField(queryset=PlacementTest.objects.all())
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())


class SubmitAttemptSerializer(serializers.Serializer):
    answers = serializers.JSONField()

    def validate_answers(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(
                _("answers must be a list of {question, response} objects.")
            )
        for item in value:
            if not isinstance(item, dict) or "question" not in item:
                raise serializers.ValidationError(_("each answer needs a 'question' id."))
        return value
