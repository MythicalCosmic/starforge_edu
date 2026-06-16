"""Notifications write-side services (D3-C-3/7/8/10).

The single fan-out for SMS / email / push / in-app / WebSocket (TD-15). Domain
apps never call adapters — they emit signals; ``apps/notifications/receivers``
calls ``dispatch()``; the Celery task does the per-channel routing.

Public contract (published to WORKLOG — Lanes A/B/E call/trigger these):

    dispatch(*, event_type, recipient_id, context, dedupe_key=None, channels=None)
        -> Notification

    - get_or_create on ``dedupe_key`` => second call with the same key is a no-op
      that returns the existing row (and does NOT re-queue the task).
    - Queues ``dispatch_notification`` (Celery) on commit.
    - Unknown ``recipient_id`` is logged and dropped (raises nothing).
    - ``channels`` is an optional whitelist subset; None = all channels (subject
      to preferences).

DEFAULT_MATRIX — the per-(event_type, channel) opt-in default when a user has no
explicit ``NotificationPreference`` row:
    - in-app: ALWAYS on (every event).
    - SMS:   on for attendance.absent, payments.*, finance.*.
    - push:  on for everything.
    - email: on for finance.* and billing.*.

Quiet hours (from CenterSettings, default 22:00-07:00 Asia/Tashkent): SMS + push
are deferred via Celery ``eta`` to the window end; in-app + email send
immediately.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from string import Template
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import (
    Channel,
    EventType,
    Notification,
    NotificationPreference,
    NotificationTemplate,
)
from core.utils import current_schema, stable_hash

logger = logging.getLogger("starforge.notifications")

ALL_CHANNELS = (Channel.IN_APP, Channel.EMAIL, Channel.SMS, Channel.PUSH)

# Events whose SMS channel defaults ON. push defaults ON everywhere; in-app
# always ON; email defaults ON for finance.* + billing.*.
_SMS_DEFAULT_ON = {
    EventType.ATTENDANCE_ABSENT,
    EventType.PAYMENTS_PAYMENT_COMPLETED,
    EventType.PAYMENTS_PAYMENT_FAILED,
    EventType.FINANCE_INVOICE_ISSUED,
    EventType.FINANCE_PAYMENT_REMINDER,
}
_EMAIL_DEFAULT_ON_PREFIXES = ("finance.", "billing.")


def default_channel_enabled(event_type: str, channel: str) -> bool:
    """The default matrix value for an (event_type, channel) with no pref row."""
    if channel == Channel.IN_APP:
        return True
    if channel == Channel.PUSH:
        return True
    if channel == Channel.SMS:
        return event_type in _SMS_DEFAULT_ON
    if channel == Channel.EMAIL:
        return event_type.startswith(_EMAIL_DEFAULT_ON_PREFIXES)
    return False


def channel_enabled_for_user(*, user_id: int, event_type: str, channel: str) -> bool:
    """Effective opt-in: an explicit preference row wins over the default matrix."""
    pref = (
        NotificationPreference.objects.filter(user_id=user_id, event_type=event_type, channel=channel)
        .values_list("enabled", flat=True)
        .first()
    )
    if pref is not None:
        return pref
    return default_channel_enabled(event_type, channel)


# ---------------------------------------------------------------------------
# dispatch — the public entry point
# ---------------------------------------------------------------------------
@transaction.atomic
def dispatch(
    *,
    event_type: str,
    recipient_id: int,
    context: dict[str, Any],
    dedupe_key: str | None = None,
    channels: list[str] | None = None,
) -> Notification | None:
    """Create (idempotently) a Notification for one recipient and queue fan-out.

    Returns the Notification (existing one on a dedupe hit), or None when the
    recipient does not exist (logged + dropped — raises nothing).
    """
    from apps.users.models import User  # lazy: avoid import cost at module load

    if not User.objects.filter(pk=recipient_id).exists():
        logger.warning(
            "dispatch dropped: unknown user id=%s event=%s schema=%s",
            recipient_id,
            event_type,
            current_schema(),
        )
        return None

    title, body = render_template(
        event_type=event_type, channel=Channel.IN_APP, user_id=recipient_id, context=context
    )

    if dedupe_key:
        notification, created = Notification.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "user_id": recipient_id,
                "event_type": event_type,
                "title": title,
                "body": body,
                "data": _json_safe(context),
            },
        )
        if not created:
            # Idempotent no-op: do NOT re-queue the fan-out task.
            return notification
    else:
        notification = Notification.objects.create(
            user_id=recipient_id,
            event_type=event_type,
            title=title,
            body=body,
            data=_json_safe(context),
        )

    schema = current_schema()
    notif_id = notification.pk
    chans = list(channels) if channels else None
    transaction.on_commit(lambda: _queue_dispatch(notif_id, chans, schema))
    return notification


def _queue_dispatch(notification_id: int, channels: list[str] | None, schema: str) -> None:
    from celery_tasks.notification_tasks import dispatch_notification

    dispatch_notification.delay(notification_id, channels=channels, _schema_name=schema)


def _json_safe(context: dict[str, Any]) -> dict[str, Any]:
    """JSON-serializable copy of the context for the Notification.data column."""
    safe: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, (str, int, float, bool, type(None))):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


# ---------------------------------------------------------------------------
# Template rendering (D3-C-7)
# ---------------------------------------------------------------------------
def _user_locale(user_id: int) -> str:
    from apps.org.selectors import get_center_settings
    from apps.users.models import User

    lang = User.objects.filter(pk=user_id).values_list("preferred_language", flat=True).first()
    if lang:
        return lang
    # Fall back to the center default grading/locale knob if one exists, else uz.
    settings_obj = get_center_settings()
    return getattr(settings_obj, "default_language", "") or "uz"


def render_template(
    *, event_type: str, channel: str, user_id: int, context: dict[str, Any]
) -> tuple[str, str]:
    """Return ``(subject, body)`` for an (event_type, channel, user-locale).

    Locale resolution: ``User.preferred_language`` -> en->uz fallback chain.
    Rendering: ``string.Template.safe_substitute`` — missing vars render
    literally, NO attribute access, NO eval (Jinja-safe per TASKS §17).
    """
    locale = _user_locale(user_id)
    template = _lookup_template(event_type=event_type, channel=channel, locale=locale)
    if template is None:
        # No template at all for this event/channel: degrade to a generic line so
        # an in-app row still carries something readable.
        label = dict(EventType.choices).get(event_type, event_type)
        return str(label), ""
    subject = Template(template.subject).safe_substitute(context) if template.subject else ""
    body = Template(template.body).safe_substitute(context)
    return subject, body


# Locale fallback order for any requested locale: requested -> en -> uz.
def _fallback_locales(locale: str) -> list[str]:
    chain = [locale]
    for fallback in ("en", "uz"):
        if fallback not in chain:
            chain.append(fallback)
    return chain


def _lookup_template(*, event_type: str, channel: str, locale: str) -> NotificationTemplate | None:
    rows = list(NotificationTemplate.objects.filter(event_type=event_type, channel=channel, is_active=True))
    by_locale = {row.locale: row for row in rows}
    for candidate in _fallback_locales(locale):
        if candidate in by_locale:
            return by_locale[candidate]
    return None


# ---------------------------------------------------------------------------
# Quiet hours (D3-C-8)
# ---------------------------------------------------------------------------
def in_quiet_hours(*, at: datetime, start: time, end: time) -> bool:
    """True if ``at`` (tz-aware) falls inside the [start, end) quiet window.

    Handles wrap-around windows (e.g. 22:00-07:00 spans midnight).
    """
    now_t = timezone.localtime(at).time()
    if start <= end:
        return start <= now_t < end
    # Wrap-around: inside if at/after start OR before end.
    return now_t >= start or now_t < end


def quiet_hours_eta(*, at: datetime, end: time) -> datetime:
    """The datetime at which the quiet window ends, on or after ``at``."""
    local = timezone.localtime(at)
    candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# Preferences bulk upsert (D3-C-8 / endpoint)
# ---------------------------------------------------------------------------
@transaction.atomic
def upsert_preferences(*, user, rows: list[dict[str, Any]]) -> list[NotificationPreference]:
    """Bulk upsert preference rows for ``user``. Each row: event_type/channel/enabled."""
    out: list[NotificationPreference] = []
    for row in rows:
        pref, _created = NotificationPreference.objects.update_or_create(
            user=user,
            event_type=row["event_type"],
            channel=row["channel"],
            defaults={"enabled": row["enabled"]},
        )
        out.append(pref)
    return out


# ---------------------------------------------------------------------------
# Read receipts (D3-C-9)
# ---------------------------------------------------------------------------
@transaction.atomic
def mark_read(*, user, notification_id: int) -> bool:
    """Mark one of the user's own notifications read. Returns True if a row changed."""
    updated = Notification.objects.filter(pk=notification_id, user=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return bool(updated)


@transaction.atomic
def mark_all_read(*, user) -> int:
    """Mark every unread notification of the user read in a single UPDATE."""
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())


# ---------------------------------------------------------------------------
# Cohort announcements (D3-C-10)
# ---------------------------------------------------------------------------
def announce_cohort(
    *, cohort_id: int, title: str, body: str, actor=None, announcement_id: str | None = None
) -> dict[str, Any]:
    """Fan out a ``cohorts.announcement`` to every active member, chunked + rate
    limited (the per-user task carries ``rate_limit="25/s"``).

    Dedupe key per (announcement, user) so a re-fire of the same announcement
    delivers each member exactly once.
    """
    from apps.cohorts.models import CohortMembership

    ann_id = announcement_id or stable_hash(f"{cohort_id}:{title}:{timezone.now().isoformat()}")[:24]
    user_ids = list(
        CohortMembership.objects.filter(cohort_id=cohort_id, end_date__isnull=True)
        .select_related("student")
        .values_list("student__user_id", flat=True)
    )
    schema = current_schema()
    context = {"title": title, "body": body}

    from celery_tasks.notification_tasks import announce_cohort_chunk

    chunk_size = 100
    chunks = 0
    for start in range(0, len(user_ids), chunk_size):
        batch = user_ids[start : start + chunk_size]
        announce_cohort_chunk.delay(
            user_ids=batch,
            announcement_id=ann_id,
            title=title,
            body=body,
            context=context,
            _schema_name=schema,
        )
        chunks += 1
    return {"announcement_id": ann_id, "recipients": len(user_ids), "chunks": chunks}
