from rest_framework import serializers

from .models import Device, RoleMembership, User


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
    class Meta:
        model = Device
        fields = ("id", "device_id", "platform", "user_agent", "last_seen_at", "created_at", "revoked_at")
        read_only_fields = ("created_at", "last_seen_at", "revoked_at")
