from __future__ import annotations

from rest_framework import serializers

from apps.users.models import Device


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    # Optional device binding (D1-LC-9): a stable client UUID + its platform.
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    platform = serializers.ChoiceField(
        choices=Device.PLATFORM_CHOICES, required=False, allow_blank=True, default=""
    )


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)  # phone or email on file


class PasswordResetConfirmSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)
    code = serializers.CharField(min_length=4, max_length=12)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()
