from django.apps import AppConfig


class BillingConfig(AppConfig):
    """Platform monetization (TD-8). PUBLIC-schema only — registered in
    SHARED_APPS, never TENANT_APPS. Plans/Subscriptions/UsageSnapshots all
    live in the public schema (one row per Center)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    label = "billing"
    verbose_name = "Billing & Paywall"

    def ready(self) -> None:
        from . import receivers  # noqa: F401
