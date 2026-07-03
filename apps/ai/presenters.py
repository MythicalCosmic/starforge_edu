"""AI response presenters (the DRF serializer output shapes)."""

from __future__ import annotations

from apps.ai.models import AIRequest, TenantAIBudget


def ai_request_to_dict(req: AIRequest) -> dict:
    return {
        "id": req.id,
        "feature": req.feature,
        "status": req.status,
        "input_tokens": req.input_tokens,
        "output_tokens": req.output_tokens,
        "cost_microusd": req.cost_microusd,
        "created_at": req.created_at.isoformat(),
        "finished_at": req.finished_at.isoformat() if req.finished_at else None,
    }


def budget_to_dict(budget: TenantAIBudget) -> dict:
    return {
        "daily_token_limit": budget.daily_token_limit,
        "monthly_token_limit": budget.monthly_token_limit,
        "tokens_used_today": budget.tokens_used_today,
        "tokens_used_month": budget.tokens_used_month,
        "is_enabled": budget.is_enabled,
    }
