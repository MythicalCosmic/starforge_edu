"""Teacher write services (TASKS §7) + the F13-1 dynamic payout/salary engine."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.teachers.models import PayoutPolicy, TeacherProfile
from apps.users.services import resolve_or_create_user
from core.exceptions import UnprocessableEntity, ValidationException

_CENT = Decimal("0.01")


@transaction.atomic
def create_teacher(
    *,
    branch,
    department=None,
    phone: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    hire_date=None,
    subjects: list | None = None,
    qualifications: str = "",
    salary_type: str = TeacherProfile.SalaryType.MONTHLY,
    rate=None,
    is_substitute: bool = False,
) -> TeacherProfile:
    if department is not None and department.branch_id != branch.id:
        raise ValidationException(
            _("Department must belong to the teacher's branch."), code="department_branch_mismatch"
        )
    user = resolve_or_create_user(
        phone=phone, email=email, first_name=first_name, last_name=last_name, middle_name=middle_name
    )
    if TeacherProfile.objects.filter(user=user).exists():
        raise ValidationException(_("This person already has a teacher profile."), code="duplicate_teacher")
    return TeacherProfile.objects.create(
        user=user,
        branch=branch,
        department=department,
        hire_date=hire_date,
        subjects=subjects or [],
        qualifications=qualifications,
        salary_type=salary_type,
        rate=rate,
        is_substitute=is_substitute,
    )


# ---------------------------------------------------------------------------
# F13-1 — dynamic payout policy + salary computation + A-1 salary-prep
# ---------------------------------------------------------------------------
def _money(raw, field: str) -> Decimal:
    """A positive, finite, 2-dp money amount, else a clean 400 (never a 500 / overflow)."""
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationException(_("Must be a number."), code="validation_error", fields={field: ["Must be a number."]}) from None
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e12"):
        raise ValidationException(_("Out of range."), code="validation_error", fields={field: ["Must be a positive amount."]})
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _percent(raw) -> Decimal:
    try:
        pct = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationException(_("Percent must be a number."), code="validation_error", fields={"tuition_percent": ["Must be a number."]}) from None
    if not pct.is_finite() or not (Decimal("0") < pct <= Decimal("100")):
        raise ValidationException(_("Percent must be between 0 and 100."), code="validation_error", fields={"tuition_percent": ["0 < percent <= 100."]})
    return pct.quantize(_CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def set_payout_policy(
    *, teacher: TeacherProfile, method: str, hourly_rate_uzs=None, flat_amount_uzs=None,
    tuition_percent=None, is_active: bool = True,
) -> PayoutPolicy:
    """Create or replace a teacher's dynamic pay rule (F13-1). Validates that the params
    required by the chosen method are present + in range; irrelevant params are cleared so
    a policy can't carry stale values from a prior method."""
    if method not in PayoutPolicy.Method.values:
        raise ValidationException(
            _("Unknown payout method."), code="validation_error",
            fields={"method": [f"Must be one of {list(PayoutPolicy.Method.values)}."]},
        )
    fields: dict = {"method": method, "is_active": is_active,
                    "hourly_rate_uzs": None, "flat_amount_uzs": None, "tuition_percent": None}
    if method == PayoutPolicy.Method.HOURLY:
        fields["hourly_rate_uzs"] = _money(hourly_rate_uzs, "hourly_rate_uzs")
    elif method == PayoutPolicy.Method.FLAT_MONTHLY:
        fields["flat_amount_uzs"] = _money(flat_amount_uzs, "flat_amount_uzs")
    elif method == PayoutPolicy.Method.PERCENT_OF_TUITION:
        fields["tuition_percent"] = _percent(tuition_percent)
    policy, _created = PayoutPolicy.objects.update_or_create(teacher=teacher, defaults=fields)
    return policy


def _period_bounds(period_start: dt.date, period_end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """[start 00:00, end+1day 00:00) as tz-aware datetimes — the period is inclusive of both
    the start and end dates."""
    if period_end < period_start:
        raise ValidationException(
            _("period_end must be on or after period_start."), code="validation_error",
            fields={"period_end": ["Must be on or after period_start."]},
        )
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(dt.datetime.combine(period_start, dt.time.min), tz)
    end_dt = timezone.make_aware(dt.datetime.combine(period_end + dt.timedelta(days=1), dt.time.min), tz)
    return start_dt, end_dt


def _teacher_student_ids(teacher: TeacherProfile) -> list[int]:
    """Student ids ACTIVELY enrolled in a cohort this teacher teaches (primary or co)."""
    from django.db.models import Q

    from apps.cohorts.models import Cohort, CohortMembership

    cohort_ids = list(
        Cohort.objects.filter(Q(primary_teacher=teacher) | Q(co_teachers__teacher=teacher))
        .values_list("id", flat=True)
    )
    return list(
        CohortMembership.objects.filter(cohort_id__in=cohort_ids, end_date__isnull=True)
        .values_list("student_id", flat=True).distinct()
    )


def compute_payout(*, teacher: TeacherProfile, period_start: dt.date, period_end: dt.date) -> dict:
    """Compute what `teacher` is owed for the period under their active PayoutPolicy (F13-1).
    Returns {method, amount_uzs (Decimal, 2dp), breakdown} — a pure read, no side effects."""
    policy = PayoutPolicy.objects.filter(teacher=teacher, is_active=True).first()
    if policy is None:
        raise UnprocessableEntity(
            _("This teacher has no active payout policy."), code="no_payout_policy"
        )
    start_dt, end_dt = _period_bounds(period_start, period_end)

    if policy.method == PayoutPolicy.Method.HOURLY:
        from apps.schedule.models import Lesson

        seconds = Decimal("0")
        for lesson in (
            Lesson.objects.filter(teacher=teacher, starts_at__gte=start_dt, starts_at__lt=end_dt)
            .exclude(status=Lesson.Status.CANCELLED)
            .only("starts_at", "ends_at")
        ):
            seconds += Decimal((lesson.ends_at - lesson.starts_at).total_seconds())
        hours = (seconds / Decimal("3600")).quantize(_CENT, rounding=ROUND_HALF_UP)
        assert policy.hourly_rate_uzs is not None  # invariant: set for the HOURLY method
        amount = (hours * policy.hourly_rate_uzs).quantize(_CENT, rounding=ROUND_HALF_UP)
        breakdown = {"hours": str(hours), "hourly_rate_uzs": str(policy.hourly_rate_uzs)}

    elif policy.method == PayoutPolicy.Method.PERCENT_OF_TUITION:
        from apps.finance.models import PaymentAllocation

        student_ids = _teacher_student_ids(teacher)
        collected = (
            PaymentAllocation.objects.filter(
                invoice__student_id__in=student_ids,
                created_at__gte=start_dt, created_at__lt=end_dt,
            ).aggregate(total=Sum("amount_uzs"))["total"]
            or Decimal("0")
        )
        assert policy.tuition_percent is not None  # invariant: set for the PERCENT method
        amount = (collected * policy.tuition_percent / Decimal("100")).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        breakdown = {"collected_uzs": str(collected), "tuition_percent": str(policy.tuition_percent)}

    else:  # FLAT_MONTHLY
        assert policy.flat_amount_uzs is not None  # invariant: set for the FLAT method
        amount = policy.flat_amount_uzs.quantize(_CENT, rounding=ROUND_HALF_UP)
        breakdown = {"flat_amount_uzs": str(policy.flat_amount_uzs)}

    return {"method": policy.method, "amount_uzs": amount, "breakdown": breakdown}


def prepare_salary(
    *, teacher: TeacherProfile, period_start: dt.date, period_end: dt.date, requested_by=None
):
    """Compute the teacher's payout for the period and raise a salary-prep request through
    the A-1 approvals engine (F13-1). A manager approves it and a cashier disburses it — the
    teacher never approves or disburses their own pay (SoD, wired in approvals). Returns the
    created ApprovalRequest."""
    from apps.approvals.services import KIND_SALARY_PREP, create_request

    result = compute_payout(teacher=teacher, period_start=period_start, period_end=period_end)
    amount = result["amount_uzs"]
    if amount <= 0:
        raise UnprocessableEntity(
            _("The computed payout for this period is zero — nothing to prepare."),
            code="zero_payout",
        )
    payee = (teacher.user.get_full_name() if teacher.user else "") or f"teacher#{teacher.pk}"
    return create_request(
        kind=KIND_SALARY_PREP,
        title=f"Salary {period_start.isoformat()}..{period_end.isoformat()}: {payee}"[:200],
        requested_by=requested_by,
        amount_uzs=amount,
        branch=teacher.branch,
        payload={
            "teacher_user_id": teacher.user_id,
            "party_label": payee,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "method": result["method"],
            "breakdown": result["breakdown"],
        },
    )
