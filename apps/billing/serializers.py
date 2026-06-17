"""Billing serializers (PUBLIC schema, platform-staff facing). Read/write split;
no `fields = "__all__"`."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.billing.models import Plan, Subscription, UsageSnapshot


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "id",
            "code",
            "name",
            "max_students",
            "max_branches",
            "ai_tokens_month",
            "storage_gb",
            "price_uzs",
            "is_active",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "id",
            "center",
            "center_name",
            "plan",
            "status",
            "current_period_start",
            "current_period_end",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class SubscriptionUpdateSerializer(serializers.Serializer):
    """PATCH body: change plan and/or set status (active|suspended)."""

    plan_code = serializers.SlugField(required=False)
    status = serializers.ChoiceField(
        choices=[Subscription.Status.ACTIVE, Subscription.Status.SUSPENDED], required=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(_("Provide plan_code and/or status."))
        return attrs


class UsageSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageSnapshot
        fields = (
            "id",
            "center",
            "date",
            "students_count",
            "storage_bytes",
            "ai_tokens_used",
            "created_at",
        )


class CheckoutSerializer(serializers.Serializer):
    center = serializers.IntegerField()
    provider = serializers.ChoiceField(choices=["click", "payme", "uzum"], required=False, default="payme")
