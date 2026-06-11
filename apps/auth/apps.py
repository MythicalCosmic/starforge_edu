from django.apps import AppConfig


class AuthAppConfig(AppConfig):
    """label='auth_app' avoids collision with django.contrib.auth's 'auth' label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth"
    label = "auth_app"
    verbose_name = "Auth (OTP + JWT)"

    def ready(self) -> None:
        from . import receivers  # noqa: F401
