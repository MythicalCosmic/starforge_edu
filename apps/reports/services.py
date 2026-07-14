"""Reports write-side services (D4-LB-4/5/6).

Creating a ``ReportRun`` enqueues ``build_report`` on commit; the task renders the
generator output, uploads to S3, and delivers a signed URL through
``notifications.dispatch`` (never the email client directly — DoD/§docs). The
hourly schedule scan (``run_due_report_schedules``) fires due ``ReportSchedule``
rows, guarded by ``last_run_at`` so re-running within the cadence window is a
no-op.
"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.reports.generators import get_generator
from apps.reports.models import Report, ReportFormat, ReportRun, ReportSchedule
from core.exceptions import ConflictException, PermissionException, ThrottledException, ValidationException
from core.job_limits import lock_tenant_job_queue, release_job_execution, try_acquire_job_execution
from core.permissions import PermissionRoleSet, Role, _code_allowed, has_permission_code
from core.utils import current_schema

logger = logging.getLogger("starforge.reports")

# The dispatch event name carried to the in-app/WS channel (Lane C consumes it).
REPORT_READY_EVENT = "report.ready"

# Roles that bypass per-report allowed_roles (see the whole library).
_FULL_ROLES = {Role.DIRECTOR}

# Server-owned metadata embedded in params.  It is copied to scheduled runs and
# lets selectors enforce branch visibility without trusting a client-supplied
# ``branch_id`` (some report types are scoped by cohort instead).
_SCOPE_BRANCH_IDS = "_scope_branch_ids"

_PARAMS_BY_REPORT: dict[str, set[str]] = {
    "enrollment": {"branch_id", "cohort_id"},
    "attendance": {"branch_id", "cohort_id", "date_from", "date_to"},
    "grades": {"branch_id", "term_id", "subject_id", "include_unpublished"},
    "finance": {"branch_id", "date_from", "date_to"},
    "ai_usage": {"month"},
    "storage_usage": set(),
}

# HoDs are branch/department managers.  The AI/storage aggregations have no
# branch attribution, so exposing them to a HoD would silently restore
# tenant-wide access.  Keep them director-only until their source rows carry a
# branch dimension.
_DIRECTOR_ONLY_REPORTS = {"ai_usage", "storage_usage"}
_REPORT_DOMAIN_PERMISSION = {
    "enrollment": "students:read",
    "attendance": "attendance:read",
    "grades": "academics:read",
    "finance": "finance:read",
}


def _active_branch_ids(user, roles: set[str]) -> set[int]:
    if user is None:
        return set()
    if isinstance(roles, PermissionRoleSet):
        branch_ids: set[int] = set()
        for membership in roles.membership_scopes:
            if membership.is_legacy_fallback:
                allowed = has_permission_code({membership.role}, "reports:write")
            else:
                allowed = _code_allowed(set(membership.grants), set(), "reports:write")
            if allowed:
                branch_ids.add(membership.branch_id)
        return branch_ids
    return set(user.role_memberships.filter(revoked_at__isnull=True).values_list("branch_id", flat=True))


def _positive_int(params: dict[str, Any], name: str) -> int | None:
    value = params.get(name)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not (
        isinstance(value, int) or (isinstance(value, str) and value.isdecimal())
    ):
        raise ValidationException(code="invalid_report_params", fields={name: ["Must be an integer."]})
    value = int(value)
    if value < 1:
        raise ValidationException(code="invalid_report_params", fields={name: ["Must be positive."]})
    return value


def _validate_date_param(params: dict[str, Any], name: str) -> date | None:
    value = params.get(name)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValidationException(code="invalid_report_params", fields={name: ["Use YYYY-MM-DD."]})
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationException(
            code="invalid_report_params", fields={name: ["Use a valid YYYY-MM-DD date."]}
        ) from exc
    params[name] = parsed.isoformat()
    return parsed


def _normalize_params(*, report_key: str, params: dict[str, Any], user, roles: set[str]) -> dict[str, Any]:
    """Validate report inputs and stamp an unforgeable branch-scope snapshot."""
    if not isinstance(params, dict):
        raise ValidationException(code="invalid_report_params", fields={"params": ["Must be an object."]})
    if len(params) > 20 or len(json.dumps(params, default=str)) > 16_384:
        raise ValidationException(code="invalid_report_params", fields={"params": ["Payload is too large."]})
    allowed = _PARAMS_BY_REPORT.get(report_key, set())
    # Never trust a persisted/client-provided scope snapshot: discard and
    # recompute it from current memberships below.
    params = {key: value for key, value in params.items() if key != _SCOPE_BRANCH_IDS}
    unknown = set(params) - allowed
    if unknown:
        raise ValidationException(
            code="invalid_report_params",
            fields={"params": [f"Unknown parameter(s): {', '.join(sorted(unknown))}."]},
        )

    clean = dict(params)
    branch_id = _positive_int(clean, "branch_id")
    cohort_id = _positive_int(clean, "cohort_id")
    for name in ("term_id", "subject_id"):
        if name in clean:
            parsed = _positive_int(clean, name)
            if parsed is not None:
                clean[name] = parsed
    if branch_id is not None:
        clean["branch_id"] = branch_id
    if cohort_id is not None:
        clean["cohort_id"] = cohort_id

    start = _validate_date_param(clean, "date_from")
    end = _validate_date_param(clean, "date_to")
    if start and end and start > end:
        raise ValidationException(
            code="invalid_report_params", fields={"date_to": ["Must not be before date_from."]}
        )
    if "include_unpublished" in clean and not isinstance(clean["include_unpublished"], bool):
        raise ValidationException(
            code="invalid_report_params", fields={"include_unpublished": ["Must be a boolean."]}
        )
    if clean.get("include_unpublished") and not (
        getattr(user, "is_superuser", False) or Role.DIRECTOR in roles
    ):
        raise PermissionException(code="report_forbidden")
    month = clean.get("month")
    if month not in (None, ""):
        if not isinstance(month, str) or len(month) != 7:
            raise ValidationException(code="invalid_report_params", fields={"month": ["Use YYYY-MM."]})
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError as exc:
            raise ValidationException(
                code="invalid_report_params", fields={"month": ["Use a valid YYYY-MM."]}
            ) from exc

    from apps.org.models import Branch

    target_branch: int | None = None
    if branch_id is not None:
        if not Branch.objects.filter(pk=branch_id, archived_at__isnull=True).exists():
            raise ValidationException(code="invalid_report_params", fields={"branch_id": ["Not found."]})
        target_branch = branch_id
    if cohort_id is not None:
        from apps.cohorts.models import Cohort

        cohort_branch = Cohort.objects.filter(pk=cohort_id).values_list("branch_id", flat=True).first()
        if cohort_branch is None:
            raise ValidationException(code="invalid_report_params", fields={"cohort_id": ["Not found."]})
        if target_branch is not None and target_branch != cohort_branch:
            raise ValidationException(
                code="invalid_report_params",
                fields={"cohort_id": ["The cohort is not in the selected branch."]},
            )
        target_branch = cohort_branch

    full_scope = bool(getattr(user, "is_superuser", False) or Role.DIRECTOR in roles)
    membership_branches = _active_branch_ids(user, roles)
    if not full_scope:
        if not membership_branches:
            raise PermissionException(code="report_forbidden")
        if target_branch is not None and target_branch not in membership_branches:
            raise PermissionException(code="report_forbidden")
        scope_branches = {target_branch} if target_branch is not None else membership_branches
    else:
        # Empty means tenant-wide and is intentionally visible only to directors.
        scope_branches = {target_branch} if target_branch is not None else set()
    clean[_SCOPE_BRANCH_IDS] = sorted(scope_branches)
    return clean


def _validate_recipient_ids(*, recipient_ids: Any, scope_branch_ids: list[int]) -> list[int]:
    if not isinstance(recipient_ids, list) or len(recipient_ids) > 50:
        raise ValidationException(
            code="invalid_recipients", fields={"recipient_ids": ["Must contain at most 50 user ids."]}
        )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in recipient_ids):
        raise ValidationException(
            code="invalid_recipients", fields={"recipient_ids": ["Every id must be a positive integer."]}
        )
    unique = list(dict.fromkeys(recipient_ids))
    if not unique:
        return []
    from apps.users.models import User

    users = User.objects.filter(pk__in=unique, is_active=True)
    if scope_branch_ids:
        users = users.filter(
            role_memberships__branch_id__in=scope_branch_ids,
            role_memberships__revoked_at__isnull=True,
        ).distinct()
    found = set(users.values_list("pk", flat=True))
    if found != set(unique):
        raise ValidationException(
            code="invalid_recipients",
            fields={"recipient_ids": ["A recipient is inactive, missing, or outside this branch scope."]},
        )
    return unique


def can_run_report(*, report: Report, roles: set[str], is_superuser: bool = False) -> bool:
    """True when a caller with these roles may run/see ``report``.

    Director / superuser always; otherwise the role must be in the report's
    ``allowed_roles`` list AND hold ``reports:write`` (checked by the view's
    permission class for the action; this is the per-report visibility gate).
    """
    if is_superuser or (roles & _FULL_ROLES):
        return True
    if report.key in _DIRECTOR_ONLY_REPORTS:
        return False
    allowed = set(report.allowed_roles or [])
    legacy_roles = roles.fallback_roles if isinstance(roles, PermissionRoleSet) else roles
    if legacy_roles & allowed:
        return True
    return bool(
        isinstance(roles, PermissionRoleSet)
        and has_permission_code(roles, "reports:write", {})
        and has_permission_code(roles, _REPORT_DOMAIN_PERMISSION.get(report.key, "*:*"), {})
    )


def _admit_report_run(
    *, report: Report, requested_by, params: dict[str, Any], fmt: str, recipient_ids: list[int] | None = None
) -> tuple[ReportRun, bool]:
    """Return an identical active run or create one after concurrency-safe caps."""
    lock_tenant_job_queue("documents")
    recipient_ids = recipient_ids or []
    active = (ReportRun.Status.QUEUED, ReportRun.Status.RUNNING)
    duplicate = (
        ReportRun.objects.filter(
            report=report,
            requested_by=requested_by,
            params=params,
            format=fmt,
            recipient_ids=recipient_ids,
            status__in=active,
        )
        .order_by("-created_at")
        .first()
    )
    if duplicate is not None:
        return duplicate, False

    now = timezone.now()
    user_active = ReportRun.objects.filter(requested_by=requested_by, status__in=active).count()
    tenant_active = ReportRun.objects.filter(status__in=active).count()
    user_hourly = ReportRun.objects.filter(
        requested_by=requested_by, created_at__gte=now - timedelta(hours=1)
    ).count()
    tenant_hourly = ReportRun.objects.filter(created_at__gte=now - timedelta(hours=1)).count()
    from apps.academics.models import Transcript

    transcript_active = Transcript.objects.filter(
        status__in=(Transcript.Status.PENDING, Transcript.Status.PROCESSING)
    ).count()
    transcript_hourly = Transcript.objects.filter(created_at__gte=now - timedelta(hours=1)).count()
    if user_active >= getattr(settings, "REPORT_MAX_ACTIVE_PER_USER", 3):
        raise ThrottledException(code="report_user_queue_full", wait=60)
    if tenant_active >= getattr(settings, "REPORT_MAX_ACTIVE_PER_TENANT", 20):
        raise ThrottledException(code="report_tenant_queue_full", wait=60)
    if tenant_active + transcript_active >= getattr(settings, "DOCUMENT_MAX_ACTIVE_PER_TENANT", 20):
        raise ThrottledException(code="document_tenant_queue_full", wait=60)
    if user_hourly >= getattr(settings, "REPORT_MAX_HOURLY_PER_USER", 10):
        raise ThrottledException(code="report_user_hourly_limit", wait=3600)
    if tenant_hourly >= getattr(settings, "REPORT_MAX_HOURLY_PER_TENANT", 100):
        raise ThrottledException(code="report_tenant_hourly_limit", wait=3600)
    if tenant_hourly + transcript_hourly >= getattr(settings, "DOCUMENT_MAX_HOURLY_PER_TENANT", 100):
        raise ThrottledException(code="document_tenant_hourly_limit", wait=3600)

    return (
        ReportRun.objects.create(
            report=report,
            requested_by=requested_by,
            params=params,
            recipient_ids=recipient_ids,
            format=fmt,
            status=ReportRun.Status.QUEUED,
        ),
        True,
    )


@transaction.atomic
def create_report_run(
    *, report_key: str, fmt: str | None, params: dict[str, Any], requested_by, roles: set[str]
) -> ReportRun:
    """Validate the key/format/visibility, create a queued ReportRun, enqueue
    ``build_report`` after commit. Raises 403 when the caller's roles are not in
    the report's allowed_roles, 422 for an unknown key/format."""
    get_generator(report_key)  # 422 unknown_report_key
    try:
        report = Report.objects.get(key=report_key)
    except Report.DoesNotExist as exc:
        raise ValidationException(code="unknown_report_key") from exc

    is_superuser = bool(getattr(requested_by, "is_superuser", False))
    if not can_run_report(report=report, roles=roles, is_superuser=is_superuser):
        raise PermissionException(code="report_forbidden")

    chosen = fmt or report.default_format
    if chosen not in ReportFormat.values:
        raise ValidationException(code="invalid_format")

    normalized_params = _normalize_params(
        report_key=report.key,
        params=params or {},
        user=requested_by,
        roles=roles,
    )
    run, created = _admit_report_run(
        report=report,
        requested_by=requested_by,
        params=normalized_params,
        fmt=chosen,
    )
    schema = current_schema()
    run_id = run.pk
    if created:
        transaction.on_commit(lambda: _enqueue_build(run_id, schema))
    return run


def _enqueue_build(run_id: int, schema: str) -> None:
    from celery_tasks.report_tasks import build_report

    build_report.delay(run_id, _schema_name=schema)


# --------------------------------------------------------------------------- #
# build_report body (called by the Celery task — D4-LB-4)
# --------------------------------------------------------------------------- #
def build_report_run(run_id: int) -> str | None:
    if not try_acquire_job_execution("report", run_id):
        raise ConflictException(_("This report run is already being built."), code="report_in_progress")
    try:
        return _build_report_run(run_id)
    finally:
        release_job_execution("report", run_id)


def _build_report_run(run_id: int) -> str | None:
    """Idempotent task body: queued → running → done | failed.

    Renders the generator output for the run's scoping (the requester's roles),
    uploads to ``{schema}/reports/{run_id}.{ext}``, presigns a download URL, and
    dispatches a ``report.ready`` notification to the requester. A run not in
    ``queued`` is skipped (safe re-delivery). Returns the s3 key, or None when
    skipped.
    """
    from infrastructure.storage import s3_client

    run = ReportRun.objects.select_related("report", "requested_by").get(pk=run_id)
    if run.status in (ReportRun.Status.DONE, ReportRun.Status.FAILED):
        # Terminal — a re-delivery is a no-op (idempotent).
        return run.s3_key or None
    # QUEUED or RUNNING: RUNNING means a prior worker was hard-killed (OOM/SIGKILL)
    # mid-render before its `except` could reset the run — build_report is acks_late,
    # so the broker redelivers the task. Re-DRIVE it (render is idempotent: it
    # overwrites the same S3 key), rather than early-returning and stranding the run
    # in RUNNING forever with no file, no notification, no failure, no retry.

    run.status = ReportRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    generator = get_generator(run.report.key)
    roles = _requester_roles(run.requested_by)
    data = generator.collect(run.params or {}, user=run.requested_by, roles=roles)

    locale = _requester_locale(run.requested_by)
    payload = generator.render(data, run.format, locale=locale)

    ext = "xlsx" if run.format == ReportFormat.XLSX else "pdf"
    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if run.format == ReportFormat.XLSX
        else "application/pdf"
    )
    key = f"{current_schema()}/reports/{run.pk}.{ext}"
    s3_client.upload_bytes(key, payload, content_type=content_type)

    run.s3_key = key
    run.file_bytes = len(payload)
    run.status = ReportRun.Status.DONE
    run.finished_at = timezone.now()
    run.save(update_fields=["s3_key", "file_bytes", "status", "finished_at"])

    _notify_ready(run)
    return key


def mark_run_failed(run_id: int, exc: Exception) -> None:
    ReportRun.objects.filter(pk=run_id).exclude(status=ReportRun.Status.DONE).update(
        status=ReportRun.Status.FAILED,
        error=str(exc)[:2000],
        finished_at=timezone.now(),
    )


def reset_run_for_retry(run_id: int) -> None:
    """Put a RUNNING/mid-flight run back to QUEUED so a Celery retry re-executes
    it. build_report_run early-returns on any non-QUEUED status and flips the run
    to RUNNING before doing work, so without this reset every retry would
    short-circuit and the retry budget was a dead no-op."""
    ReportRun.objects.filter(pk=run_id).exclude(status=ReportRun.Status.DONE).update(
        status=ReportRun.Status.QUEUED,
        started_at=None,
    )


def _requester_roles(user) -> set[str]:
    if user is None:
        return set()
    return {m.role for m in user.role_memberships.filter(revoked_at__isnull=True)}


def _requester_locale(user) -> str:
    return getattr(user, "preferred_language", "") or "uz"


def presign_run(run: ReportRun) -> str | None:
    """A fresh presigned download URL — only when the run is done."""
    if run.status == ReportRun.Status.DONE and run.s3_key:
        from infrastructure.storage import s3_client

        return s3_client.presign_download(run.s3_key, expires_in=600)
    return None


def _notify_ready(run: ReportRun) -> None:
    """Deliver the ready signed URL via notifications.dispatch (never email
    directly). Recipients are the requester PLUS any ``recipient_ids`` configured
    on the originating schedule (deduped); a fresh presign is embedded so the
    in-app/WS payload carries a working link."""
    # Preserve order (requester first), dedupe, drop falsy ids.
    recipients: list[int] = []
    for rid in [run.requested_by_id, *(run.recipient_ids or [])]:
        if rid and rid not in recipients:
            recipients.append(rid)
    if not recipients:
        return
    from apps.notifications.services import dispatch

    schema = current_schema()
    context = {
        "report": run.report.key,
        "report_title": run.report.title,
        "run_id": run.pk,
        "format": run.format,
        "download_url": presign_run(run) or "",
    }
    for rid in recipients:
        dispatch(
            event_type=REPORT_READY_EVENT,
            recipient_id=rid,
            context=context,
            # Per-recipient key so the in-app dedupe doesn't collapse deliveries.
            dedupe_key=f"report.ready:{schema}:{run.pk}:{rid}",
        )


# --------------------------------------------------------------------------- #
# Schedules (D4-LB-6)
# --------------------------------------------------------------------------- #
@transaction.atomic
def create_schedule(*, report_key: str, created_by, roles: set[str], **fields: Any) -> ReportSchedule:
    try:
        report = Report.objects.get(key=report_key)
    except Report.DoesNotExist as exc:
        raise ValidationException(code="unknown_report_key") from exc
    is_superuser = bool(getattr(created_by, "is_superuser", False))
    if not can_run_report(report=report, roles=roles, is_superuser=is_superuser):
        raise PermissionException(code="report_forbidden")
    fields = dict(fields)
    fields["params"] = _normalize_params(
        report_key=report.key,
        params=fields.get("params") or {},
        user=created_by,
        roles=roles,
    )
    fields["recipient_ids"] = _validate_recipient_ids(
        recipient_ids=fields.get("recipient_ids") or [],
        scope_branch_ids=fields["params"][_SCOPE_BRANCH_IDS],
    )
    return ReportSchedule.objects.create(report=report, created_by=created_by, **fields)


@transaction.atomic
def update_schedule(
    schedule: ReportSchedule, *, actor, roles: set[str], report_key: str | None = None, **changes: Any
) -> ReportSchedule:
    """Update an already selector-scoped schedule with the same create gates."""
    report = schedule.report
    if report_key is not None:
        try:
            report = Report.objects.get(key=report_key)
        except Report.DoesNotExist as exc:
            raise ValidationException(code="unknown_report_key") from exc
    if not can_run_report(
        report=report,
        roles=roles,
        is_superuser=bool(getattr(actor, "is_superuser", False)),
    ):
        raise PermissionException(code="report_forbidden")

    merged_params = changes.get("params", schedule.params or {})
    normalized = _normalize_params(
        report_key=report.key,
        params=merged_params,
        user=actor,
        roles=roles,
    )
    recipients = _validate_recipient_ids(
        recipient_ids=changes.get("recipient_ids", schedule.recipient_ids or []),
        scope_branch_ids=normalized[_SCOPE_BRANCH_IDS],
    )
    schedule.report = report
    schedule.params = normalized
    schedule.recipient_ids = recipients
    for field in ("cadence", "weekday", "day_of_month", "hour", "format", "is_active"):
        if field in changes:
            setattr(schedule, field, changes[field])
    schedule.full_clean()
    schedule.save()
    return schedule


def schedule_is_due(schedule: ReportSchedule, *, now: datetime) -> bool:
    """True when ``schedule`` should fire at ``now``: cadence anchor matches the
    current weekday/day-of-month + hour, and it hasn't already run this window.

    The ``last_run_at`` guard rejects a second fire within the same cadence period
    (a re-run of the hourly scan creates no duplicate run)."""
    if not schedule.is_active:
        return False
    local = timezone.localtime(now)
    if local.hour != schedule.hour:
        return False
    if schedule.cadence == ReportSchedule.Cadence.WEEKLY:
        if local.weekday() != schedule.weekday:
            return False
        window = timedelta(days=7)
    elif schedule.cadence == ReportSchedule.Cadence.MONTHLY:
        # Clamp the anchor to the month's last day so day_of_month in {29,30,31}
        # still fires in shorter months (Feb/Apr/Jun/Sep/Nov) instead of being
        # silently skipped. e.g. "the 31st" fires on Feb 28/29.
        last_day = calendar.monthrange(local.year, local.month)[1]
        target_day = min(schedule.day_of_month or 1, last_day)
        if local.day != target_day:
            return False
        window = timedelta(days=28)
    else:  # pragma: no cover - constrained by the model
        return False
    # last_run_at guard: reject a second fire within the same cadence window
    # (a re-run of the hourly scan must create no duplicate run).
    return not (schedule.last_run_at is not None and now - schedule.last_run_at < window)


@transaction.atomic
def fire_schedule(schedule: ReportSchedule, *, now: datetime) -> ReportRun:
    """Create a queued ReportRun for a due schedule and stamp ``last_run_at``.

    Locks the schedule row so two concurrent scans can't both fire it; re-checks
    due-ness under the lock (the last_run_at guard) before creating the run.
    """
    locked = ReportSchedule.objects.select_for_update().get(pk=schedule.pk)
    if not schedule_is_due(locked, now=now):
        # Lost the race — another scan already fired it.
        raise ValidationException(code="schedule_not_due")
    if locked.created_by_id is None:
        # The creator was deleted (SET_NULL). Without a requester there is no role
        # scope to generate against, so the run would be empty AND undelivered.
        # Refuse to create it here (deactivation is done by run_due_schedules,
        # OUTSIDE this atomic block — deactivating here would be rolled back by the
        # raise below).
        raise ValidationException(code="schedule_no_creator")
    creator_roles = _requester_roles(locked.created_by)
    if not can_run_report(
        report=locked.report,
        roles=creator_roles,
        is_superuser=bool(getattr(locked.created_by, "is_superuser", False)),
    ):
        raise PermissionException(code="report_forbidden")
    normalized_params = _normalize_params(
        report_key=locked.report.key,
        params=locked.params or {},
        user=locked.created_by,
        roles=creator_roles,
    )
    recipient_ids = _validate_recipient_ids(
        recipient_ids=list(locked.recipient_ids or []),
        scope_branch_ids=normalized_params[_SCOPE_BRANCH_IDS],
    )
    run, created = _admit_report_run(
        report=locked.report,
        requested_by=locked.created_by,
        params=normalized_params,
        recipient_ids=recipient_ids,
        fmt=locked.format,
    )
    locked.last_run_at = now
    locked.save(update_fields=["last_run_at"])
    schema = current_schema()
    run_id = run.pk
    if created:
        transaction.on_commit(lambda: _enqueue_build(run_id, schema))
    return run


def run_due_schedules(*, now: datetime | None = None) -> int:
    """Scan the current tenant's active schedules and fire the due ones. Returns
    the count fired. Idempotent within a cadence window (last_run_at guard)."""
    now = now or timezone.now()
    fired = 0
    candidates = list(ReportSchedule.objects.select_related("report", "created_by").filter(is_active=True))
    for schedule in candidates:
        if not schedule_is_due(schedule, now=now):
            continue
        if schedule.created_by_id is None:
            # Creator deleted → no scope/recipient. Deactivate (committed here,
            # outside any atomic) so it stops firing empty, undelivered runs.
            ReportSchedule.objects.filter(pk=schedule.pk).update(is_active=False)
            logger.warning("report schedule %s deactivated: creator deleted", schedule.pk)
            continue
        try:
            fire_schedule(schedule, now=now)
            fired += 1
        except PermissionException:
            ReportSchedule.objects.filter(pk=schedule.pk).update(is_active=False)
            logger.warning("report schedule %s deactivated: creator no longer authorized", schedule.pk)
        except ValidationException as exc:
            if exc.code != "schedule_not_due":
                ReportSchedule.objects.filter(pk=schedule.pk).update(is_active=False)
                logger.warning("report schedule %s deactivated: invalid persisted configuration", schedule.pk)
            continue
        except ThrottledException:
            # Queue pressure is temporary. Leave last_run_at untouched so the
            # next hourly scan can try again.
            continue
    return fired
