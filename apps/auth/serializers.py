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


class _StrictIdentifierMixin(serializers.Serializer):
    """Reject a non-string `identifier` with 400 instead of letting CharField
    silently coerce a JSON int/float to a string (the throttles already survive
    non-strings; the request itself must still be a 400, not a 202)."""

    def to_internal_value(self, data):
        raw = data.get("identifier") if isinstance(data, dict) else None
        if raw is not None and not isinstance(raw, str):
            raise serializers.ValidationError({"identifier": ["Must be a string."]})
        return super().to_internal_value(data)


class PasswordResetRequestSerializer(_StrictIdentifierMixin, serializers.Serializer):
    identifier = serializers.CharField(max_length=255)  # phone or email on file


class PasswordResetConfirmSerializer(_StrictIdentifierMixin, serializers.Serializer):
    identifier = serializers.CharField(max_length=255)
    code = serializers.CharField(min_length=4, max_length=12)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()
