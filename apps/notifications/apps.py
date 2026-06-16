from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        # Connect every Day-1/2/3 source-signal receiver (D3-C-4). Import here so
        # the signal handlers register exactly once at app load.
        from . import receivers  # noqa: F401
