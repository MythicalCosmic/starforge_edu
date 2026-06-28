from __future__ import annotations

from rest_framework import serializers

from apps.compliance.models import Penalty, Rule
from apps.org.models import Branch
from apps.students.models import StudentProfile
from apps.users.models import User


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = (
            "id",
            "title",
            "body",
            "version",
            "applies_to_roles",
            "is_active",
            "created_at",
            "updated_at",
        )
        # version is service-managed (auto-bumps on body change).
        read_only_fields = ("id", "version", "created_at", "updated_at")


class PenaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = Penalty
        fields = (
            "id",
            "rule",
            "student",
            "staff",
            "points",
            "reason",
            "branch",
            "status",
            "issued_by",
            "issued_at",
            "waived_by",
            "waived_at",
            "waive_reason",
            "escalated",
        )
        read_only_fields = fields


class IssuePenaltySerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    points = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=255)
    rule = serializers.PrimaryKeyRelatedField(
        queryset=Rule.objects.filter(is_active=True), required=False, allow_null=True
    )


class IssueStaffPenaltySerializer(serializers.Serializer):
    staff = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True))
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(archived_at__isnull=True))
    points = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=255)
    rule = serializers.PrimaryKeyRelatedField(
        queryset=Rule.objects.filter(is_active=True), required=False, allow_null=True
    )


class WaivePenaltySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
