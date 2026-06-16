from __future__ import annotations

from django.contrib import admin

from apps.payments.models import FiscalReceipt, Payment, PaymentAttempt, ProviderConfig, WebhookEvent


@admin.register(ProviderConfig)
class ProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("provider", "is_active", "updated_at")
    list_filter = ("provider", "is_active")
    # Credentials are encrypted (TD-11) — never list/search them in admin.
    exclude = ("click_secret_key", "payme_key", "payme_test_key", "uzum_api_key")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "amount_uzs",
        "status",
        "allocation_status",
        "provider_txn_id",
        "paid_at",
    )
    list_filter = ("provider", "status", "allocation_status")
    search_fields = ("provider_txn_id", "account_ref", "idempotency_key")
    readonly_fields = ("idempotency_key", "provider_txn_id", "metadata", "created_at", "updated_at")


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "attempt_no", "error_code", "created_at")
    list_filter = ("error_code",)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "event_id", "status", "signature_valid", "created_at")
    list_filter = ("provider", "status", "signature_valid")
    search_fields = ("event_id",)
    readonly_fields = ("provider", "event_id", "payload", "remote_ip", "created_at", "processed_at")


@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "status", "fiscal_sign", "attempts", "confirmed_at")
    list_filter = ("status",)
    search_fields = ("fiscal_sign",)
