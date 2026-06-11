"""Auth domain signals (TD-9 precursor).

Fired from `apps.auth.services` / views with flat primitive kwargs:
``identifier``, ``ip``, ``user_agent`` (+ ``schema_name`` for cross-context
dispatch). Day 1 consumer is a structured log line on ``starforge.auth``
(`apps.auth.receivers`); Day 3 Lane D attaches an AuditLog receiver.
"""

from __future__ import annotations

import django.dispatch

otp_requested = django.dispatch.Signal()
otp_verified = django.dispatch.Signal()
otp_failed = django.dispatch.Signal()
