from django.apps import AppConfig


class FormsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.forms"
    label = "forms_app"  # avoid clashing with django.forms in app-label space
    verbose_name = "Forms & surveys"
