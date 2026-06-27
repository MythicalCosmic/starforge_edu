from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.academics.models import Subject
from apps.org.models import Branch
from apps.placement.models import PlacementQuestion, PlacementTest


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
