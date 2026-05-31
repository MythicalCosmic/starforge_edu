"""Auto-audit sensitive models via post_save / post_delete.

We deliberately do NOT audit users.User here: it is saved on every
authenticated request (last_seen_at) and would flood the log. RoleMembership
(permission grants) is the security-critical one and is included.
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from .models import AuditLog
from .services import log_instance

# (app_label, model_name) pairs resolved lazily to avoid import cycles.
SENSITIVE_MODELS = [
    ("users", "RoleMembership"),
    ("students", "StudentProfile"),
    ("parents", "Guardian"),
    ("teachers", "TeacherProfile"),
]


def _on_save(sender, instance, created, **kwargs):
    log_instance(instance, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE)


def _on_delete(sender, instance, **kwargs):
    log_instance(instance, AuditLog.Action.DELETE)


def connect() -> None:
    from django.apps import apps

    for app_label, model_name in SENSITIVE_MODELS:
        model = apps.get_model(app_label, model_name)
        uid = f"audit:{app_label}.{model_name}"
        post_save.connect(_on_save, sender=model, dispatch_uid=f"{uid}:save")
        post_delete.connect(_on_delete, sender=model, dispatch_uid=f"{uid}:delete")
