from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.cards.models import Card, CardType, Wallet, WalletTransaction
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


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ("id", "kind", "amount_uzs", "balance_after_uzs", "created_by", "note", "created_at")
        read_only_fields = fields


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ("student", "balance_uzs", "updated_at")
        read_only_fields = fields


class WalletAmountSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
