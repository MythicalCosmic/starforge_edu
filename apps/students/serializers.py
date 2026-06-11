from rest_framework import serializers

from apps.org.models import Branch
from apps.students.models import EnrollmentEvent, StudentProfile


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
    user = StudentUserSerializer(read_only=True)

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
            "medical_notes",
            "emergency_contacts",
            "user",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StudentCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
    status = serializers.ChoiceField(
        choices=StudentProfile.Status.choices, required=False, default=StudentProfile.Status.LEAD
    )
    academic_level = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    medical_notes = serializers.CharField(required=False, allow_blank=True, default="")
    emergency_contacts = serializers.JSONField(required=False)

    def validate(self, attrs):
        if not attrs.get("phone") and not attrs.get("email"):
            raise serializers.ValidationError({"phone": "Provide a phone or an email."})
        return attrs


class StudentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = ("branch", "current_cohort", "academic_level", "medical_notes", "emergency_contacts")


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=StudentProfile.Status.choices)
    reason_code = serializers.ChoiceField(
        choices=EnrollmentEvent.ReasonCode.choices, required=False, allow_blank=True, default=""
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class EnrollmentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrollmentEvent
        fields = ("id", "from_status", "to_status", "reason_code", "note", "created_at")
        read_only_fields = fields


class StudentImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
