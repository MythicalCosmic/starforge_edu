from __future__ import annotations

from rest_framework import serializers

from apps.cards.models import Card, CardType
from apps.students.models import StudentProfile


class CardTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CardType
        fields = ("id", "name", "is_active", "created_by", "created_at")
        read_only_fields = ("id", "created_by", "created_at")


class CardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = (
            "id",
            "student",
            "card_type",
            "code",
            "is_active",
            "issued_by",
            "issued_at",
            "revoked_at",
            "revoke_reason",
        )
        read_only_fields = fields


class IssueCardSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    card_type = serializers.PrimaryKeyRelatedField(queryset=CardType.objects.filter(is_active=True))


class RevokeCardSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class ScanSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
