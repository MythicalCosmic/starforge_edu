"""Regression tests for the notification Celery fan-out (celery_tasks/notification_tasks).

Covers the verified bugs in the messaging cluster:
- in-app/WS group name is SCHEMA-prefixed (cross-tenant leak on shared Redis).
- quiet-hours deferral is idempotent under Celery at-least-once redelivery of
  ``dispatch_notification`` (no double SMS/push), and ``deliver_single_channel``
  no-ops on a second deferred run.
"""

from __future__ import annotations

from datetime import time

import pytest
import time_machine
from django_tenants.utils import schema_context

pytestmark = pytest.mark.django_db


def _user_with_phone(tenant):
    from apps.users.tests.factories import UserFactory

    with schema_context(tenant.schema_name):
        return UserFactory(phone="+998901112233", email="payer@example.com")


def _set_quiet_hours(tenant, *, start, end):
    from apps.org.models import CenterSettings

    with schema_context(tenant.schema_name):
        cs = CenterSettings.load()
        cs.quiet_hours_start = start
        cs.quiet_hours_end = end
        cs.save(update_fields=["quiet_hours_start", "quiet_hours_end"])


# --------------------------------------------------------------------------- #
# In-app WS group name must be schema-prefixed (cross-tenant isolation)
# --------------------------------------------------------------------------- #
@time_machine.travel("2026-06-16 12:00:00 +05:00", tick=False)
def test_in_app_group_send_is_schema_prefixed(tenant_a, monkeypatch, django_capture_on_commit_callbacks):
    """The producer group name MUST be ``{schema}.user.{id}`` — an unscoped
    ``user.{id}`` collides across tenants on the shared Redis channel layer
    (tenant A user 5 receives tenant B user 5's notifications)."""
    from apps.notifications.services import dispatch

    captured: list[str] = []

    def fake_group_send(group, message):
        captured.append(group)

    # _deliver_in_app imports group_send from this module at call time, so
    # patching the source-module attribute is what takes effect.
    monkeypatch.setattr("infrastructure.websocket.channel_layer.group_send", fake_group_send)

    user = _user_with_phone(tenant_a)
    with schema_context(tenant_a.schema_name), django_capture_on_commit_callbacks(execute=True):
        dispatch(
            event_type="attendance.absent",
            recipient_id=user.pk,
            context={"lesson_id": 1},
            channels=["in_app"],  # in-app only
            dedupe_key=f"grp:{user.pk}",
        )

    assert captured, "in-app delivery must call group_send"
    group = captured[0]
    assert group == f"{tenant_a.schema_name}.user.{user.pk}"
    assert group.startswith(f"{tenant_a.schema_name}.")
    # The pre-fix unscoped name must never be produced.
    assert group != f"user.{user.pk}"


# --------------------------------------------------------------------------- #
# Quiet-hours deferral is idempotent under dispatch_notification redelivery
# --------------------------------------------------------------------------- #
@time_machine.travel("2026-06-16 23:30:00 +05:00", tick=False)
def test_quiet_hours_redelivery_does_not_double_defer(
    tenant_a, monkeypatch, django_capture_on_commit_callbacks
):
    """A Celery redelivery of ``dispatch_notification`` for a quiet-hours channel
    that already has a SKIPPED_QUIET_HOURS marker must NOT record a second skip
    nor schedule a second deferred delivery (which would double-send paid SMS)."""
    import celery_tasks.notification_tasks as nt
    from apps.notifications.models import Channel, Notification, NotificationDelivery
    from apps.notifications.services import dispatch

    _set_quiet_hours(tenant_a, start=time(22, 0), end=time(7, 0))

    schedule_calls: list[dict] = []

    def fake_apply_async(*args, **kwargs):
        schedule_calls.append(kwargs)
        return None

    monkeypatch.setattr(nt.deliver_single_channel, "apply_async", fake_apply_async)

    user = _user_with_phone(tenant_a)
    with schema_context(tenant_a.schema_name):
        with django_capture_on_commit_callbacks(execute=True):
            notif = dispatch(
                event_type="payments.payment_completed",
                recipient_id=user.pk,
                context={"amount": "1"},
                dedupe_key=f"qh:{user.pk}",
            )
        # First dispatch already ran the fan-out once (one SMS deferral scheduled).
        sms_skips = NotificationDelivery.objects.filter(
            notification=notif, channel=Channel.SMS, status=NotificationDelivery.Status.SKIPPED_QUIET_HOURS
        ).count()
        assert sms_skips == 1
        first_schedule_count = len(schedule_calls)
        assert first_schedule_count >= 1

        # Simulate Celery redelivering the SAME dispatch task.
        nt.dispatch_notification(notif.pk)

        # No SECOND skip marker, no SECOND scheduled deferral for SMS.
        assert (
            NotificationDelivery.objects.filter(
                notification=notif,
                channel=Channel.SMS,
                status=NotificationDelivery.Status.SKIPPED_QUIET_HOURS,
            ).count()
            == 1
        )
        # The redelivery must not have scheduled additional SMS deferrals.
        sms_schedules = [c for c in schedule_calls if (c.get("kwargs") or {}).get("channel") == Channel.SMS]
        assert len(sms_schedules) == 1
        # sanity: still a single notification row
        assert Notification.objects.filter(pk=notif.pk).count() == 1


@time_machine.travel("2026-06-16 12:00:00 +05:00", tick=False)
def test_deliver_single_channel_second_run_is_noop(tenant_a, sms_outbox, django_capture_on_commit_callbacks):
    """``deliver_single_channel`` must send at most once: a redelivery (or two
    skip markers producing two scheduled tasks) at window end sends ONE SMS."""
    from apps.notifications.models import Channel, NotificationDelivery
    from apps.notifications.services import dispatch
    from celery_tasks.notification_tasks import deliver_single_channel

    user = _user_with_phone(tenant_a)
    with schema_context(tenant_a.schema_name):
        # Create a notification with a standing SKIPPED_QUIET_HOURS SMS marker,
        # as the quiet-hours branch would have left.
        with django_capture_on_commit_callbacks(execute=False):
            notif = dispatch(
                event_type="payments.payment_completed",
                recipient_id=user.pk,
                context={"amount": "1"},
                dedupe_key=f"dsc:{user.pk}",
            )
        NotificationDelivery.objects.create(
            notification=notif,
            channel=Channel.SMS,
            status=NotificationDelivery.Status.SKIPPED_QUIET_HOURS,
            provider_response={"deferred_to": "2026-06-16T07:00:00+05:00"},
        )
        sms_outbox.clear()

        # First window-end run: delivers (deferred_to in the past).
        r1 = deliver_single_channel(notif.pk, Channel.SMS, deferred_to="2026-06-16T07:00:00+05:00")
        # Second run (redelivery): must no-op.
        r2 = deliver_single_channel(notif.pk, Channel.SMS, deferred_to="2026-06-16T07:00:00+05:00")

    assert r1 == "sent"
    assert r2 == "already_delivered"
    assert len(sms_outbox) == 1  # exactly one SMS, never two
