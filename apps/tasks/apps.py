from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    label = "staff_tasks"  # avoid the generic "tasks" label colliding with Celery modules
    verbose_name = "Tasks & role hierarchy"
