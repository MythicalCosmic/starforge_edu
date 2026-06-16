from rest_framework import serializers

from apps.schedule.models import Lesson, RecurrenceRule, Term, TimeSlot


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
