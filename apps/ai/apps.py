from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai_app"
    verbose_name = "AI"

    def ready(self) -> None:
        from . import receivers  # noqa: F401  (connect signal receivers)
