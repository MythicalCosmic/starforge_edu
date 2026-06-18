"""Billing models — TD-8 platform monetization (PUBLIC schema only).

These tables live exclusively in the public schema (apps.billing is in
SHARED_APPS, NOT TENANT_APPS). One Plan catalog platform-wide; one
Subscription per Center; one UsageSnapshot per (Center, day).

Cross-schema note: a tenant-schema `post_save` receiver cannot audit
Subscription (it is a public-schema row). Lane E writes subscription audit
entries explicitly via `audit_log()` inside `schema_context(center.schema_name)`
from its services (see Lane D decision in DAY-3.md).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Plan(models.Model):
    """A subscription tier (TD-8 field list, verbatim). `[OWNER:O-12]` real pricing."""

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    max_students = models.PositiveIntegerField()
    max_branches = models.PositiveIntegerField()
    ai_tokens_month = models.BigIntegerField()
    storage_gb = models.PositiveIntegerField()
    price_uzs = models.DecimalField(max_digits=18, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("price_uzs",)
        constraints = [
            models.CheckConstraint(condition=models.Q(price_uzs__gte=0), name="plan_price_non_negative"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} ({self.price_uzs} UZS)"


class Subscription(models.Model):
    """One Center's subscription state.

    "Expired" is represented as `suspended` — there is no separate expired
    status; the nightly metering task flips trialing/active/past_due → suspended.
    """

    class Status(models.TextChoices):
        TRIALING = "trialing", _("Trialing")
        ACTIVE = "active", _("Active")
        PAST_DUE = "past_due", _("Past due")
        SUSPENDED = "suspended", _("Suspended")

    center = models.OneToOneField("tenancy.Center", on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIALING, db_index=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("center_id",)
        indexes = [
            models.Index(fields=("status", "current_period_end"), name="billing_sub_status_end_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.center_id}:{self.status}"


class UsageSnapshot(models.Model):
    """Daily usage meter per Center (one row per (center, date)). Re-running the
    nightly task updates the row, never duplicates it."""

    center = models.ForeignKey("tenancy.Center", on_delete=models.CASCADE, related_name="usage_snapshots")
    date = models.DateField()
    students_count = models.PositiveIntegerField(default=0)
    storage_bytes = models.BigIntegerField(default=0)
    ai_tokens_used = models.BigIntegerField(default=0)
    dau = models.PositiveIntegerField(default=0)  # daily active users captured at snapshot time
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=("center", "date"), name="usage_one_snapshot_per_center_day"),
        ]
        indexes = [models.Index(fields=("center", "date"), name="billing_usage_center_date_idx")]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.center_id}@{self.date}"
