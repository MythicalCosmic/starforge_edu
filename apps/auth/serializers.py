from __future__ import annotations

from rest_framework import serializers

from apps.users.models import Device


class OTPRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)


class OTPVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)
    code = serializers.CharField(min_length=4, max_length=12)
    # Optional device binding (D1-LC-9): a stable client UUID + its platform.
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    platform = serializers.ChoiceField(
        choices=Device.PLATFORM_CHOICES, required=False, allow_blank=True, default=""
    )


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()
