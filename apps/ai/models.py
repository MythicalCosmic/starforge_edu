"""AI models — v1 scaffold.

Stub models live here only to prove the app loads + migrates. Replace with
real domain models per feature ticket.
"""

from django.db import models


class AiItem(models.Model):
    """Placeholder so the app has at least one migrated model."""

    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ai_app"

    def __str__(self) -> str:  # pragma: no cover
        return self.name
