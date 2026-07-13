from __future__ import annotations

from django.conf import settings


def test_cors_wraps_pre_tenant_rate_limit_responses():
    middleware = list(settings.MIDDLEWARE)
    assert middleware.index("corsheaders.middleware.CorsMiddleware") < middleware.index(
        "core.middleware.ApiRateLimitMiddleware"
    )


def test_staging_forces_every_external_provider_to_mock():
    source = (settings.BASE_DIR / "config" / "settings" / "staging.py").read_text(encoding="utf-8")
    for name in (
        "ESKIZ_USE_MOCK",
        "ANTHROPIC_USE_MOCK",
        "CLICK_USE_MOCK",
        "PAYME_USE_MOCK",
        "UZUM_USE_MOCK",
        "SOLIQ_USE_MOCK",
        "FCM_USE_MOCK",
        "PLATFORM_PAYMENTS_USE_MOCK",
    ):
        assert f"{name} = True" in source
