"""Audit write helpers."""

from __future__ import annotations

from typing import Any

from django.db import models

from .context import get_actor
from .models import AuditLog


def audit_log(
    *,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    changes: dict[str, Any] | None = None,
    actor: Any | None = None,
) -> AuditLog:
    """Record one audit row, defaulting actor/ip/ua from the request context."""

    ctx = get_actor()
    if actor is None:
        actor = ctx.user
    return AuditLog.objects.create(
        actor_id=getattr(actor, "pk", None),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        changes=changes or {},
        ip=ctx.ip,
        user_agent=ctx.user_agent[:512],
    )


def log_instance(instance: models.Model, action: str) -> AuditLog:
    label = f"{instance._meta.app_label}.{instance._meta.object_name}"
    return audit_log(action=action, resource_type=label, resource_id=str(instance.pk))
