from django.contrib import admin

from apps.ai.models import AIPrompt, AIRequest, TenantAIBudget


@admin.register(TenantAIBudget)
class TenantAIBudgetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "daily_token_limit",
        "monthly_token_limit",
        "tokens_used_today",
        "tokens_used_month",
        "is_enabled",
        "updated_at",
    )
    list_filter = ("is_enabled",)


@admin.register(AIPrompt)
class AIPromptAdmin(admin.ModelAdmin):
    list_display = ("feature", "version", "is_active", "max_output_tokens", "effort", "token_cost_cap")
    list_filter = ("feature", "is_active")
    search_fields = ("feature",)


@admin.register(AIRequest)
class AIRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "feature",
        "status",
        "input_tokens",
        "output_tokens",
        "cost_microusd",
        "created_at",
    )
    list_filter = ("feature", "status")
    search_fields = ("idempotency_key", "source_app")
    # Redaction map / output text are sensitive — never editable in admin.
    readonly_fields = ("redaction_map", "output_text", "idempotency_key", "celery_task_id")
    date_hierarchy = "created_at"
