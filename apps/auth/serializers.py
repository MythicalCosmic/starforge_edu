from __future__ import annotations

from rest_framework import serializers


class OTPRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)


class OTPVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)
    code = serializers.CharField(min_length=4, max_length=12)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
