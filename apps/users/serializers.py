from rest_framework import serializers

from .models import Device, RoleMembership, User


class UserBriefSerializer(serializers.ModelSerializer):
    """Compact read view of a person, embedded by profile serializers."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "email",
            "first_name",
            "last_name",
            "middle_name",
            "full_name",
            "birthdate",
            "gender",
        )
        read_only_fields = fields

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name()


class RoleMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleMembership
        fields = ("id", "role", "branch", "department", "granted_at")


class UserSerializer(serializers.ModelSerializer):
    role_memberships = RoleMembershipSerializer(many=True, read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "email",
            "first_name",
            "last_name",
            "middle_name",
            "full_name",
            "birthdate",
            "gender",
            "preferred_language",
            "is_active",
            "is_staff",
            "date_joined",
            "last_seen_at",
            "role_memberships",
        )
        read_only_fields = ("is_staff", "date_joined", "last_seen_at", "role_memberships")

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name()


class DeviceSerializer(serializers.ModelSerializer):
    """Read serializer — never exposes the raw `push_token`."""

    class Meta:
        model = Device
        fields = ("id", "device_id", "platform", "user_agent", "last_seen_at", "created_at")
        read_only_fields = fields


class DeviceRegisterSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    platform = serializers.ChoiceField(choices=Device.PLATFORM_CHOICES)
    push_token = serializers.CharField(required=False, allow_blank=True, default="")
