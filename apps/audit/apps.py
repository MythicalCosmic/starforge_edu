from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    label = "audit"
    verbose_name = "Audit"

    def ready(self) -> None:
        # Wire the TD-9 post_save/post_delete receivers. Models are resolved via
        # apps.get_model with try/except LookupError so a sibling lane's not-yet
        # -migrated model never crashes startup (D3-D-2).
        from apps.audit.receivers import connect_audit_receivers

        connect_audit_receivers()
