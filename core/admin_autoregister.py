"""Auto-register EVERY model in the Django admin.

The per-app ``admin.py`` files register the important models with tailored ModelAdmins; this
sweeps up every remaining model with a safe generic admin, so nothing is ever missing from
``/admin/`` and a newly-added model appears automatically. It runs from
``core.admin_apps.StarforgeAdminConfig.ready()`` AFTER admin autodiscovery, so it never
overrides an explicit registration.

The generic admin is built to never 500 on a large table:
* ``raw_id_fields`` for every FK/O2O — never render a huge related-object dropdown in the form,
* ``list_select_related`` — no N+1 on FK columns shown in the changelist,
* ``show_full_result_count = False`` — skip the expensive full ``COUNT(*)`` on the paginator,
* ``list_display`` limited to concrete, non-binary local fields.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.contrib import admin
from django.db import models

_TEXT_FIELDS = (models.CharField, models.TextField, models.EmailField, models.SlugField)


def _generic_admin(model: type[models.Model]) -> type[admin.ModelAdmin]:
    concrete = list(model._meta.fields)  # concrete local fields only (no m2m / reverse)
    list_display = [f.name for f in concrete if not isinstance(f, models.BinaryField)][:8] or ["pk"]
    search = [f.name for f in concrete if isinstance(f, _TEXT_FIELDS)][:6]
    fks = [f.name for f in concrete if f.is_relation and (f.many_to_one or f.one_to_one)]

    attrs: dict[str, Any] = {
        "list_display": list_display,
        "list_per_page": 50,
        "list_select_related": True,
        "show_full_result_count": False,
        "raw_id_fields": fks,
    }
    if search:
        attrs["search_fields"] = search
    return type(f"{model.__name__}AutoAdmin", (admin.ModelAdmin,), attrs)


def autoregister_all() -> int:
    """Register every not-yet-registered, registerable model. Returns the count added."""
    added = 0
    for model in apps.get_models():
        if model in admin.site._registry or getattr(model._meta, "auto_created", False):
            continue  # already registered, or an auto-created m2m through table (unregisterable)
        try:
            admin.site.register(model, _generic_admin(model))
            added += 1
        except Exception:
            pass
    return added
