"""Append-only audit log.

Rows are written by signals on sensitive models (see apps.audit.signals) and by
explicit audit_log() calls for non-model events (login, OTP, etc.). Nothing in
the app updates or deletes AuditLog rows — it is an immutable trail. Retention
trimming happens out-of-band via a scheduled task (TASKS §22).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        OTHER = "other", "Other"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    resource_type = models.CharField(max_length=120)  # "students.StudentProfile"
    resource_id = models.CharField(max_length=64, blank=True)
    changes = models.JSONField(default=dict, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("resource_type", "resource_id")),
            models.Index(fields=("actor", "created_at")),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.action} {self.resource_type}#{self.resource_id} by {self.actor_id}"
