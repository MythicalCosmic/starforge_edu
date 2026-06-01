from rest_framework import serializers

from apps.cohorts.models import Cohort
from apps.org.models import Room
from apps.teachers.models import TeacherProfile

from .models import Holiday, Lesson
from .services import describe_conflicts, find_conflicts


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ("id", "branch", "date", "name")


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = (
            "id",
            "cohort",
            "branch",
            "room",
            "teacher",
            "start",
            "end",
            "status",
            "series_id",
            "note",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("branch", "series_id", "created_at", "updated_at")

    def validate(self, attrs):
        inst = self.instance

        def field(name):
            return attrs.get(name, getattr(inst, name, None))

        start, end = field("start"), field("end")
        room, teacher, cohort = field("room"), field("teacher"), field("cohort")
        status = attrs.get("status", getattr(inst, "status", Lesson.Status.SCHEDULED))

        if start and end and end <= start:
            raise serializers.ValidationError({"end": "Must be after start."})

        # Cancelled lessons free their slot, so they never conflict.
        if status != Lesson.Status.CANCELLED and start and end:
            conflicts = find_conflicts(
                start=start,
                end=end,
                room=room,
                teacher=teacher,
                cohort=cohort,
                exclude_id=getattr(inst, "pk", None),
            )
            if conflicts.exists():
                raise serializers.ValidationError(
                    {"conflict": describe_conflicts(conflicts, room=room, teacher=teacher, cohort=cohort)}
                )
        return attrs


class RecurringLessonSerializer(serializers.Serializer):
    """Input for POST /schedule/lessons/recurring/."""

    cohort = serializers.PrimaryKeyRelatedField(queryset=Cohort.objects.all())
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.all(), required=False, allow_null=True
    )
    teacher = serializers.PrimaryKeyRelatedField(
        queryset=TeacherProfile.objects.all(), required=False, allow_null=True
    )
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), allow_empty=False
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    skip_holidays = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "Must be after start_time."})
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError({"end_date": "Must not be before start_date."})
        return attrs
