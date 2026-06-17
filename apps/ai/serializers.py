"""AI serializers — read/write split, no ``fields="__all__"`` (DoD #4).

The redaction map, raw output text, and error detail are never exposed in the
request-log read serializer: the log is an accounting surface, not a PII window.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.ai.models import AIRequest, TenantAIBudget


class AIRequestReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIRequest
        fields = (
            "id",
            "feature",
            "status",
            "input_tokens",
            "output_tokens",
            "cost_microusd",
            "created_at",
            "finished_at",
        )
        read_only_fields = fields


class BudgetReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantAIBudget
        fields = (
            "daily_token_limit",
            "monthly_token_limit",
            "tokens_used_today",
            "tokens_used_month",
            "is_enabled",
        )
        read_only_fields = ("tokens_used_today", "tokens_used_month")


class BudgetWriteSerializer(serializers.Serializer):
    daily_token_limit = serializers.IntegerField(min_value=0, required=False)
    monthly_token_limit = serializers.IntegerField(min_value=0, required=False)
    is_enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(_("At least one field is required."))
        return attrs


class ExamGenerationRequestSerializer(serializers.Serializer):
    subject_id = serializers.IntegerField(min_value=1)
    exam_type = serializers.CharField(max_length=32)
    question_count = serializers.IntegerField(min_value=1, max_value=200)
    difficulty = serializers.ChoiceField(choices=("easy", "medium", "hard"))


class ExamGenerationResponseSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()


class UsageReportRowSerializer(serializers.Serializer):
    feature = serializers.CharField()
    requests = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cost_microusd = serializers.IntegerField()
