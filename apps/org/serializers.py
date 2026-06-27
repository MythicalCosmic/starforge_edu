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
from .services import validate_department_head, validate_student_id_pattern


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

    def validate_head(self, user):
        # Raises core ValidationException (400 head_not_teacher envelope) on
        # both create and update — D1-LF-4's only write surface.
        validate_department_head(user)
        return user


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

    # TD-13 JSON shape guards: Day-2 consumers (upload checks, OTP channel
    # selection) rely on these shapes — malformed values must 400 at write time.
    allowed_file_types = serializers.ListField(child=serializers.SlugField(), required=False)
    otp_channel_prefs = serializers.DictField(child=serializers.BooleanField(), required=False)
    # F8-1: the placement question types the center allows (empty = no restriction).
    placement_allowed_question_types = serializers.ListField(
        child=serializers.CharField(), required=False
    )

    def validate_placement_allowed_question_types(self, value):
        # Lazy import: org is a low-level app and must not import placement at module
        # load (placement depends on org) — validate against the type values here.
        from apps.placement.models import PlacementQuestion

        valid = set(PlacementQuestion.QuestionType.values)
        unknown = [t for t in value if t not in valid]
        if unknown:
            raise serializers.ValidationError(
                "Unknown question type(s): {}.".format(", ".join(map(str, unknown)))
            )
        deduped = []
        for t in value:  # preserve order, drop duplicates
            if t not in deduped:
                deduped.append(t)
        return deduped

    class Meta:
        model = CenterSettings
        fields = (
            "open_registration",
            "require_group_acceptance",  # F1-8: group-placement maker-checker toggle
            "grading_scheme",
            "honor_roll_min",
            "academic_warning_max",
            "late_threshold_minutes",
            "attendance_correction_window_hours",
            "auto_absent_after_minutes",
            "assignment_grace_minutes",
            "assignment_max_resubmits",
            "max_upload_mb",
            "storage_quota_gb",
            "allowed_file_types",
            "currency_primary",
            "currency_secondary",
            "fx_source",
            "fx_rate_usd_manual",
            "sibling_discount_percent",
            "payment_reminder_interval_days",
            "quiet_hours_start",
            "quiet_hours_end",
            "otp_channel_prefs",
            "otp_cooldown_seconds",
            "student_id_pattern",
            "center_code",
            "ai_exam_generation_enabled",
            "placement_allowed_question_types",  # F8-1
            "updated_at",
        )
        read_only_fields = ("updated_at",)

    def validate_otp_channel_prefs(self, prefs: dict) -> dict:
        unknown = set(prefs) - {"sms", "email"}
        if unknown:
            raise serializers.ValidationError(f"Unknown OTP channels: {sorted(unknown)}.")
        return prefs

    def validate(self, attrs):
        # Cross-field: the rendered pattern length depends on center_code, so
        # validate the (pattern, code) pair as it will exist after this write.
        pattern = attrs.get("student_id_pattern", getattr(self.instance, "student_id_pattern", None))
        if pattern is not None:
            code = attrs.get("center_code", getattr(self.instance, "center_code", "") or "")
            validate_student_id_pattern(pattern, center_code=code)
        return attrs
