from __future__ import annotations

from rest_framework import serializers

from apps.covers.models import CoverRequest
from apps.schedule.models import Lesson
from apps.teachers.models import TeacherProfile


class CoverRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoverRequest
        fields = (
            "id",
            "lesson",
            "requester",
            "reason",
            "status",
            "pool",
            "cover_teacher",
            "branch",
            "decided_by",
            "decided_at",
            "created_at",
        )
        read_only_fields = fields


class CreateCoverSerializer(serializers.Serializer):
    lesson = serializers.PrimaryKeyRelatedField(
        queryset=Lesson.objects.filter(status=Lesson.Status.SCHEDULED)
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AssignCoverSerializer(serializers.Serializer):
    cover_teacher = serializers.PrimaryKeyRelatedField(queryset=TeacherProfile.objects.all())
