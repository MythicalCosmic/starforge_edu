from __future__ import annotations

from rest_framework import serializers

from apps.achievements.models import Achievement, AchievementGrant
from apps.cohorts.models import Cohort
from apps.students.models import StudentProfile


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = (
            "id",
            "name",
            "description",
            "emoji",
            "scope",
            "cohort",
            "branch",
            "status",
            "created_by",
            "decided_by",
            "decided_at",
            "created_at",
        )
        read_only_fields = fields


class AchievementCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    emoji = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")
    scope = serializers.ChoiceField(choices=Achievement.Scope.choices)
    # branch is derived from the cohort (group) or center-wide (global) — never client-set.
    cohort = serializers.PrimaryKeyRelatedField(
        queryset=Cohort.objects.all(), required=False, allow_null=True
    )


class GrantSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AchievementGrantSerializer(serializers.ModelSerializer):
    achievement_detail = AchievementSerializer(source="achievement", read_only=True)

    class Meta:
        model = AchievementGrant
        fields = ("id", "achievement", "achievement_detail", "student", "granted_by", "note", "granted_at")
        read_only_fields = fields
