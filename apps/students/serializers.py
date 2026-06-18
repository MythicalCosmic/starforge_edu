from rest_framework import serializers

from apps.org.models import Branch
from apps.students.models import EnrollmentEvent, StudentProfile
from core.permissions import Role, get_user_roles

# Roles allowed to read decrypted medical_notes (health data, TD-11 / DoD #4).
MEDICAL_NOTES_ROLES = {Role.DIRECTOR, Role.REGISTRAR}


def _active_branches():
    """Archived branches are not assignable (D1-LF-7 soft delete)."""
    return Branch.objects.filter(archived_at__isnull=True)


class StudentUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    phone = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    middle_name = serializers.CharField(read_only=True)
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    birthdate = serializers.DateField(read_only=True)
    gender = serializers.CharField(read_only=True)


class StudentReadSerializer(serializers.ModelSerializer):
    """List/action payload. Deliberately excludes `medical_notes` — health data
    is only served on retrieve, role-gated via StudentDetailSerializer."""

    user = StudentUserSerializer(read_only=True)
    is_blocked = serializers.BooleanField(read_only=True)

    class Meta:
        model = StudentProfile
        fields = (
            "id",
            "student_id",
            "status",
            "branch",
            "current_cohort",
            "enrollment_date",
            "academic_level",
            "location",
            "previous_school",
            "is_blocked",
            "blocked_at",
            "block_reason",
            "emergency_contacts",
            "user",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StudentDetailSerializer(StudentReadSerializer):
    """Retrieve payload: adds `medical_notes`, decrypted only for
    MEDICAL_NOTES_ROLES (fail-closed when no request in context)."""

    medical_notes = serializers.SerializerMethodField()

    class Meta(StudentReadSerializer.Meta):
        fields = (*StudentReadSerializer.Meta.fields, "medical_notes")  # type: ignore[assignment]
        read_only_fields = fields  # type: ignore[assignment]

    def get_medical_notes(self, obj: StudentProfile) -> str | None:
        request = self.context.get("request")
        if request is None:
            return None
        if request.user.is_superuser or (get_user_roles(request) & MEDICAL_NOTES_ROLES):
            return obj.medical_notes
        return None


class StudentCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(queryset=_active_branches())
    status = serializers.ChoiceField(
        choices=StudentProfile.Status.choices, required=False, default=StudentProfile.Status.LEAD
    )
    academic_level = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    location = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    previous_school = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    medical_notes = serializers.CharField(required=False, allow_blank=True, default="")
    emergency_contacts = serializers.JSONField(required=False)

    def validate(self, attrs):
        if not attrs.get("phone") and not attrs.get("email"):
            raise serializers.ValidationError({"phone": "Provide a phone or an email."})
        return attrs


class StudentUpdateSerializer(serializers.ModelSerializer):
    """Direct profile edits only. `current_cohort` is deliberately absent —
    cohort changes must go through POST /cohorts/{id}/enroll or /move-student
    so CohortMembership history, signals, and capacity checks stay intact.
    `branch` is also absent: branch changes wait for the D2 transfer service
    (apps.org.services.record_transfer) so a BranchTransfer row is recorded."""

    class Meta:
        model = StudentProfile
        fields = ("academic_level", "location", "previous_school", "medical_notes", "emergency_contacts")


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=StudentProfile.Status.choices)
    reason_code = serializers.ChoiceField(
        choices=EnrollmentEvent.ReasonCode.choices, required=False, allow_blank=True, default=""
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class BlockSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class EnrollmentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrollmentEvent
        fields = ("id", "from_status", "to_status", "reason_code", "note", "created_at")
        read_only_fields = fields


class StudentImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    branch = serializers.PrimaryKeyRelatedField(queryset=_active_branches())


class BirthdayQuerySerializer(serializers.Serializer):
    """Query params for /students/birthdays/ — bounds `days` (worker DoS guard)
    and type-checks branch/cohort so garbage lands as 400, not 500."""

    days = serializers.IntegerField(required=False, default=7, min_value=0, max_value=366)
    branch = serializers.IntegerField(required=False)
    cohort = serializers.IntegerField(required=False)
