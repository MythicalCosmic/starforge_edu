"""AI read-side selectors."""

from .models import AiItem


def list_active():
    return AiItem.objects.filter(is_active=True)


def tokens_used_current_month() -> int:
    """AI tokens consumed by the current tenant this calendar month.

    Stub for D3-E billing metering; D4-A replaces the body with the real
    ``TenantAIBudget`` read. Billing's nightly metering imports this lazily and
    tolerates a 0 here until then.
    """
    return 0  # TODO(D4-A): real implementation
