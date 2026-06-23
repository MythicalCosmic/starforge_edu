from django.utils.text import slugify
from rest_framework import serializers

from apps.schedule.models import Lesson, LessonType, RecurrenceRule, Term, TimeSlot


class LessonTypeSerializer(serializers.ModelSerializer):
    # Slug is auto-derived from the name when omitted, so managers just type a label.
    slug = serializers.SlugField(required=False)

    class Meta:
        model = LessonType
        fields = ("id", "name", "slug", "color", "is_active")

    def validate(self, attrs):
        if not attrs.get("slug") and attrs.get("name"):
            attrs["slug"] = slugify(attrs["name"])[:64]
        return attrs


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ("id", "name", "academic_year", "start_date", "end_date", "is_current")


class TimeSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeSlot
        fields = ("id", "branch", "name", "start_time", "end_time", "order")


class RecurrenceRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecurrenceRule
        fields = (
            "id",
            "term",
            "cohort",
            "teacher",
            "room",
            "lesson_type",
            "title",
            "rrule",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
        )
        read_only_fields = ("created_at",)


class RecurrenceRuleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecurrenceRule
        fields = (
            "term",
            "cohort",
            "teacher",
            "room",
            "lesson_type",
            "title",
            "rrule",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "is_active",
        )


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = (
            "id",
            "rule",
            "term",
            "cohort",
            "teacher",
            "room",
            "lesson_type",
            "title",
            "starts_at",
            "ends_at",
            "status",
            "detached_from_rule",
            "cancel_reason",
        )
        read_only_fields = fields


class CancelLessonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class MoveLessonSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class BulkRescheduleSerializer(serializers.Serializer):
    shift_minutes = serializers.IntegerField()
