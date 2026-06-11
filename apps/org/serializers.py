from django.apps import apps as django_apps
from rest_framework import serializers

from .models import (
    Branch,
    BranchHoliday,
    BranchTransfer,
    BranchWorkingHours,
    CenterSettings,
    Department,
    Room,
)


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = (
            "id",
            "branch",
            "name",
            "slug",
            "description",
            "is_active",
            "head",
            "budget",
            "created_at",
        )
        read_only_fields = ("created_at",)


class WorkingHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchWorkingHours
        fields = ("id", "weekday", "opens_at", "closes_at", "is_closed")
        read_only_fields = ("id",)


class WorkingHoursWriteSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    opens_at = serializers.TimeField()
    closes_at = serializers.TimeField()
    is_closed = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("is_closed") and attrs["opens_at"] >= attrs["closes_at"]:
            raise serializers.ValidationError({"closes_at": "Must be after opens_at."})
        return attrs


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchHoliday
        fields = ("id", "date", "name", "is_working_day_override")
        read_only_fields = ("id",)


class HolidayWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField(max_length=200)
    is_working_day_override = serializers.BooleanField(default=False)


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = (
            "id",
            "branch",
            "name",
            "capacity",
            "equipment",
            "is_active",
            "notes",
            "created_at",
        )
        read_only_fields = ("created_at",)


class BranchTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchTransfer
        fields = ("id", "user", "from_branch", "to_branch", "reason", "actor", "created_at")
        read_only_fields = fields


class BranchSerializer(serializers.ModelSerializer):
    departments = DepartmentSerializer(many=True, read_only=True)
    working_hours = WorkingHoursSerializer(many=True, read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id",
            "name",
            "slug",
            "address",
            "phone",
            "timezone",
            "is_active",
            "max_students",
            "max_teachers",
            "archived_at",
            "departments",
            "working_hours",
            "created_at",
        )
        read_only_fields = ("archived_at", "created_at")


class BranchDetailSerializer(BranchSerializer):
    """Adds capacity_status — detail-only to keep the list query budget flat."""

    capacity_status = serializers.SerializerMethodField()

    class Meta(BranchSerializer.Meta):
        fields = (*BranchSerializer.Meta.fields, "capacity_status")  # type: ignore[assignment]

    def get_capacity_status(self, obj: Branch) -> dict:
        try:
            StudentProfile = django_apps.get_model("students", "StudentProfile")
        except LookupError:
            current = 0
        else:
            current = (
                StudentProfile.objects.filter(branch=obj)
                .exclude(status__in=("graduated", "withdrawn"))
                .count()
            )
        return {
            "current_students": current,
            "max_students": obj.max_students,
            "over": obj.max_students is not None and current > obj.max_students,
        }


class CenterSettingsSerializer(serializers.ModelSerializer):
    """Explicit fields (TD-13 — never `__all__`); every knob is editable by a
    director, internal timestamps are read-only."""

    class Meta:
        model = CenterSettings
        fields = (
            "open_registration",
            "grading_scheme",
            "late_threshold_minutes",
            "attendance_correction_window_hours",
            "assignment_grace_minutes",
            "max_upload_mb",
            "allowed_file_types",
            "currency_primary",
            "currency_secondary",
            "fx_source",
            "quiet_hours_start",
            "quiet_hours_end",
            "otp_channel_prefs",
            "otp_cooldown_seconds",
            "student_id_pattern",
            "center_code",
            "updated_at",
        )
        read_only_fields = ("updated_at",)
