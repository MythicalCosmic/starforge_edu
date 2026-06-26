from __future__ import annotations

from rest_framework import serializers

from apps.rewards.models import RewardGrant, RewardType
from apps.users.models import User
from core.permissions import Role

# Rewards go to STAFF (never students/parents).
_STAFF_ROLES = tuple(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))


class RewardTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RewardType
        fields = (
            "id",
            "name",
            "is_cash",
            "default_amount_uzs",
            "description",
            "is_active",
            "created_by",
            "created_at",
        )
        read_only_fields = ("id", "created_by", "created_at")


class GrantRewardSerializer(serializers.Serializer):
    reward_type = serializers.PrimaryKeyRelatedField(queryset=RewardType.objects.all())
    recipient = serializers.PrimaryKeyRelatedField(
        # A staff member with an active membership in this center.
        queryset=User.objects.filter(
            is_active=True,
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=_STAFF_ROLES,
        ).distinct()
    )
    amount_uzs = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RewardGrantSerializer(serializers.ModelSerializer):
    reward_type_detail = RewardTypeSerializer(source="reward_type", read_only=True)
    approval_status = serializers.SerializerMethodField()

    class Meta:
        model = RewardGrant
        fields = (
            "id",
            "reward_type",
            "reward_type_detail",
            "recipient",
            "amount_uzs",
            "reason",
            "granted_by",
            "approval_request",
            "approval_status",
            "granted_at",
        )
        read_only_fields = fields

    def get_approval_status(self, obj) -> str | None:
        return obj.approval_request.status if obj.approval_request_id else None
