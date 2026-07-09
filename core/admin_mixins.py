"""Shared admin mixins.

``ReadOnlyAdmin`` makes a model view-only in ``/admin/``: still searchable and
filterable for review, but no add / change / delete. It's for append-only or
system-managed tables where hand-editing would corrupt an invariant — the money
ledger and approval state machine (anti-fraud "money can't disappear" trail), the
auth sessions (the ``key`` is a live Bearer token), and the campaign send-log
(rows are frozen at build time, not authored by hand).

Registering a model with any explicit admin (including this one) also makes the
``core.admin_autoregister`` sweep skip it — the sweep only touches models that
nothing has registered yet.
"""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return False
