"""Per-tenant organizational structure: Branch + Department.

Lives in tenant schemas only. A row's tenant is the schema it lives in;
no FK to Center is needed because django-tenants enforces isolation at
the connection level.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


def _default_allowed_file_types() -> list[str]:
    return ["pdf", "mp4", "pptx", "docx", "mp3", "jpg", "jpeg", "png", "webp"]  # D2-E-2


def _default_otp_channel_prefs() -> dict[str, bool]:
    return {"sms": True, "email": True}


class Branch(models.Model):
    """A physical location of the education center (city / building)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    address = models.CharField(max_length=512, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    timezone = models.CharField(max_length=64, default="Asia/Tashkent")
    is_active = models.BooleanField(default=True)

    # Soft capacity caps (null = unlimited). These never block writes — they
    # surface a `capacity_status.over` flag for the UI (D1-LF-5).
    max_students = models.PositiveIntegerField(null=True, blank=True)
    max_teachers = models.PositiveIntegerField(null=True, blank=True)

    # Soft delete: `destroy` archives instead of deleting (D1-LF-7).
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Branches"

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Department(models.Model):
    """A teaching/admin unit inside a Branch (math, languages, finance, etc.)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # head targets users.User (not teachers.TeacherProfile) because Lane D merges
    # after Lane F. `set_department_head` validates a TeacherProfile exists once
    # that app lands (D1-LF-4 / D1-LD-10).
    head = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="headed_departments",
    )
    budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("branch", "slug"),)
        ordering = ("branch", "name")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch.name}/{self.name}"


class CenterSettings(models.Model):
    """Per-Center knob store (TD-13). Tenant-schema singleton at pk=1.

    Every school-variable number lives here instead of as a code constant.
    Consume through the cached accessor `apps.org.selectors.get_center_settings`,
    never by querying this table in a hot path.
    """

    class GradingScheme(models.TextChoices):
        LETTER = "letter", _("Letter (A–F)")
        GPA = "gpa", _("GPA (0–4)")
        PERCENTAGE = "percentage", _("Percentage (0–100)")

    class Language(models.TextChoices):
        UZBEK = "uz", _("Uzbek")
        RUSSIAN = "ru", _("Russian")
        ENGLISH = "en", _("English")

    open_registration = models.BooleanField(default=False)  # TD-17
    # F1-8 / D-8: when True, a reception group proposal needs a manager's acceptance
    # before the lead is enrolled; when False, reception's proposal enrolls directly.
    require_group_acceptance = models.BooleanField(default=False)
    # D4-LF-3 (TD-13): the center's default notification language. Blank means
    # "no preference" — the locale fallback chain then uses the en→uz lingua
    # franca order. A center serving Uzbek can set "uz" to prefer it over en.
    default_language = models.CharField(
        max_length=8,
        blank=True,
        default="",
        choices=Language.choices,
        help_text=_("Default notification language; blank uses the en→uz fallback."),
    )
    grading_scheme = models.CharField(
        max_length=16, choices=GradingScheme.choices, default=GradingScheme.PERCENTAGE
    )
    honor_roll_min = models.DecimalField(  # D2-C-2
        max_digits=5, decimal_places=2, default=Decimal("90")
    )
    academic_warning_max = models.DecimalField(  # D2-C-2
        max_digits=5, decimal_places=2, default=Decimal("60")
    )
    late_threshold_minutes = models.PositiveSmallIntegerField(default=10)
    attendance_correction_window_hours = models.PositiveSmallIntegerField(default=24)
    auto_absent_after_minutes = models.PositiveSmallIntegerField(default=30)  # D2-B-2
    assignment_grace_minutes = models.PositiveSmallIntegerField(default=0)
    assignment_max_resubmits = models.PositiveSmallIntegerField(default=2)  # D2-D-2
    max_upload_mb = models.PositiveIntegerField(default=200)  # D2-E uses this as max_file_size_mb
    storage_quota_gb = models.PositiveIntegerField(null=True, blank=True)  # D2-E-2 (null = unlimited)
    allowed_file_types = models.JSONField(default=_default_allowed_file_types)
    currency_primary = models.CharField(max_length=3, default="UZS")
    currency_secondary = models.CharField(max_length=3, default="USD")
    fx_source = models.CharField(max_length=32, default="cbu")
    # D3-A finance knobs (consumed by apps/finance/services.py):
    fx_rate_usd_manual = models.DecimalField(  # used when fx_source == "manual"
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    sibling_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    payment_reminder_interval_days = models.PositiveSmallIntegerField(default=3)
    quiet_hours_start = models.TimeField(default=time(22, 0))
    quiet_hours_end = models.TimeField(default=time(7, 0))
    otp_channel_prefs = models.JSONField(default=_default_otp_channel_prefs)
    otp_cooldown_seconds = models.PositiveSmallIntegerField(default=60)
    student_id_pattern = models.CharField(max_length=64, default="{CODE}-{YYYY}-{NNNNN}")
    center_code = models.CharField(max_length=16, blank=True)
    # D4-LA-7 (TD-13): gates the request-driven AI exam-generation endpoint.
    ai_exam_generation_enabled = models.BooleanField(default=False)
    # F8-1: which placement question types this center allows when authoring tests.
    # Empty (default) = no restriction (all types). A non-empty list restricts both
    # manual and AI authoring to exactly those PlacementQuestion.QuestionType values.
    placement_allowed_question_types = models.JSONField(default=list, blank=True)
    # F24-1: when a student's total ACTIVE penalty points cross this threshold, the
    # crossing penalty is flagged + branch managers are notified. 0 = disabled.
    penalty_escalation_threshold = models.PositiveSmallIntegerField(default=0)
    # F15-1: when False, the student/parent report omits classroom rank entirely — some
    # centers reject ranking on principle (dignity DNA). Default True (rank shown).
    show_classroom_rank = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Center settings"
        verbose_name_plural = "Center settings"

    def __str__(self) -> str:  # pragma: no cover
        return "CenterSettings"

    @classmethod
    def load(cls) -> CenterSettings:
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class Room(models.Model):
    """A bookable space inside a Branch."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=100)
    capacity = models.PositiveSmallIntegerField(default=0)
    equipment = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("branch", "name"),)
        ordering = ("branch", "name")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch_id}:{self.name}"


class BranchWorkingHours(models.Model):
    """One row per (branch, weekday). Replaced wholesale via the bulk-set
    endpoint (D1-LF-2)."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Monday")
        TUESDAY = 1, _("Tuesday")
        WEDNESDAY = 2, _("Wednesday")
        THURSDAY = 3, _("Thursday")
        FRIDAY = 4, _("Friday")
        SATURDAY = 5, _("Saturday")
        SUNDAY = 6, _("Sunday")

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="working_hours")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    opens_at = models.TimeField()
    closes_at = models.TimeField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = (("branch", "weekday"),)
        ordering = ("branch", "weekday")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_closed=True) | models.Q(opens_at__lt=models.F("closes_at")),
                name="working_hours_open_before_close_or_closed",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch_id}:{self.weekday}"


class BranchHoliday(models.Model):
    """A per-branch closed/special day, layered over national holidays (D2-A)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=200)
    is_working_day_override = models.BooleanField(default=False)

    class Meta:
        unique_together = (("branch", "date"),)
        ordering = ("date",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch_id}:{self.date}"


class BranchTransfer(models.Model):
    """Audit-style record of a student moving between branches. FK to users.User
    (not students.StudentProfile) to avoid depending on Lane D (D1-LF-6)."""

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="branch_transfers")
    from_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_out")
    to_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_in")
    reason = models.CharField(max_length=64, blank=True)
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfers_made",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user_id}:{self.from_branch_id}->{self.to_branch_id}"
