"""Org-domain presenters — plain dict mappers (replace the DRF ModelSerializers).

Decimals are rendered as strings and times as ``HH:MM:SS`` to match the previous
DRF output exactly (DRF's default COERCE_DECIMAL_TO_STRING + TimeField format).
"""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps

from apps.org.models import (
    Branch,
    BranchHoliday,
    BranchTransfer,
    BranchWorkingHours,
    CenterSettings,
    Department,
    Room,
)


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def department_to_dict(d: Department) -> dict[str, Any]:
    return {
        "id": d.id,
        "branch": d.branch_id,
        "name": d.name,
        "slug": d.slug,
        "description": d.description,
        "is_active": d.is_active,
        "head": d.head_id,
        "budget": _dec(d.budget),
        "created_at": d.created_at.isoformat(),
    }


def working_hour_to_dict(w: BranchWorkingHours) -> dict[str, Any]:
    return {
        "id": w.id,
        "weekday": w.weekday,
        "opens_at": w.opens_at.isoformat(),
        "closes_at": w.closes_at.isoformat(),
        "is_closed": w.is_closed,
    }


def holiday_to_dict(h: BranchHoliday) -> dict[str, Any]:
    return {
        "id": h.id,
        "date": h.date.isoformat(),
        "name": h.name,
        "is_working_day_override": h.is_working_day_override,
    }


def room_to_dict(r: Room) -> dict[str, Any]:
    return {
        "id": r.id,
        "branch": r.branch_id,
        "name": r.name,
        "capacity": r.capacity,
        "equipment": r.equipment,
        "is_active": r.is_active,
        "notes": r.notes,
        "created_at": r.created_at.isoformat(),
    }


def branch_to_dict(b: Branch) -> dict[str, Any]:
    return {
        "id": b.id,
        "name": b.name,
        "slug": b.slug,
        "address": b.address,
        "phone": b.phone,
        "timezone": b.timezone,
        "is_active": b.is_active,
        "max_students": b.max_students,
        "max_teachers": b.max_teachers,
        "archived_at": b.archived_at.isoformat() if b.archived_at else None,
        "departments": [department_to_dict(d) for d in b.departments.all()],
        "working_hours": [working_hour_to_dict(w) for w in b.working_hours.all()],
        "created_at": b.created_at.isoformat(),
    }


def branch_capacity_status(b: Branch) -> dict[str, Any]:
    try:
        StudentProfile = django_apps.get_model("students", "StudentProfile")
    except LookupError:
        current = 0
    else:
        current = (
            StudentProfile.objects.filter(branch=b)
            .exclude(status__in=("graduated", "withdrawn"))
            .count()
        )
    return {
        "current_students": current,
        "max_students": b.max_students,
        "over": b.max_students is not None and current > b.max_students,
    }


def branch_detail_to_dict(b: Branch) -> dict[str, Any]:
    return {**branch_to_dict(b), "capacity_status": branch_capacity_status(b)}


def transfer_to_dict(t: BranchTransfer) -> dict[str, Any]:
    return {
        "id": t.id,
        "user": t.user_id,
        "from_branch": t.from_branch_id,
        "to_branch": t.to_branch_id,
        "reason": t.reason,
        "actor": t.actor_id,
        "created_at": t.created_at.isoformat(),
    }


# The writable + read (updated_at) fields the settings endpoint exposes (TD-13 —
# mirrors CenterSettingsSerializer.Meta.fields, never __all__).
_SETTINGS_INT_FIELDS = (
    "late_threshold_minutes",
    "attendance_correction_window_hours",
    "auto_absent_after_minutes",
    "assignment_grace_minutes",
    "assignment_max_resubmits",
    "max_upload_mb",
    "storage_quota_gb",
    "payment_reminder_interval_days",
    "otp_cooldown_seconds",
    "penalty_escalation_threshold",
)
_SETTINGS_BOOL_FIELDS = (
    "open_registration",
    "require_group_acceptance",
    "ai_exam_generation_enabled",
    "show_classroom_rank",
)
_SETTINGS_STR_FIELDS = (
    "grading_scheme",
    "currency_primary",
    "currency_secondary",
    "fx_source",
    "student_id_pattern",
    "center_code",
)
_SETTINGS_DEC_FIELDS = (
    "honor_roll_min",
    "academic_warning_max",
    "fx_rate_usd_manual",
    "sibling_discount_percent",
)
_SETTINGS_JSON_FIELDS = (
    "allowed_file_types",
    "otp_channel_prefs",
    "placement_allowed_question_types",
)


def settings_to_dict(s: CenterSettings) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _SETTINGS_INT_FIELDS + _SETTINGS_BOOL_FIELDS + _SETTINGS_STR_FIELDS + _SETTINGS_JSON_FIELDS:
        out[f] = getattr(s, f)
    for f in _SETTINGS_DEC_FIELDS:
        out[f] = _dec(getattr(s, f))
    out["quiet_hours_start"] = s.quiet_hours_start.isoformat()
    out["quiet_hours_end"] = s.quiet_hours_end.isoformat()
    out["updated_at"] = s.updated_at.isoformat()
    return out
