from rest_framework import serializers

from apps.parents.models import Guardian, ParentProfile, PickupAuthorization
from apps.students.models import StudentProfile
from apps.users.serializers import UserBriefSerializer


class ParentReadSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = ParentProfile
        fields = ("id", "user", "workplace", "notes", "created_at")
        read_only_fields = ("created_at",)


class ParentCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    workplace = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("phone") and not attrs.get("email"):
            raise serializers.ValidationError({"phone": "Provide a phone or an email."})
        return attrs


class ParentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParentProfile
        fields = ("workplace", "notes")


class GuardianReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guardian
        fields = ("id", "parent", "student", "relationship", "is_primary", "custody_notes")
        read_only_fields = ("id",)


class GuardianWriteSerializer(serializers.Serializer):
    # `parent` shadows DRF's internal Field.parent attribute — harmless at
    # runtime (it lives in self.fields), but mypy needs the override silenced.
    parent = serializers.PrimaryKeyRelatedField(queryset=ParentProfile.objects.all())  # type: ignore[assignment]
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    relationship = serializers.ChoiceField(choices=Guardian.Relationship.choices)
    is_primary = serializers.BooleanField(required=False, default=False)
    custody_notes = serializers.CharField(required=False, allow_blank=True, default="")


class PickupAuthorizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupAuthorization
        fields = ("id", "student", "full_name", "phone", "relationship", "is_active", "created_at")
        read_only_fields = ("created_at",)
