"""Placement test engine (F1-2 / F1-4) — a paper-killing entry funnel.

A manager or teacher builds a `PlacementTest` out of ordered `PlacementQuestion`s
while it is DRAFT, submits it for review (→ PENDING), and a *different* manager
approves it (→ APPROVED) before it can be assigned to a prospective student. The
maker-checker split (the builder cannot approve their own test) is the anti-fraud
DNA: a placement decides a student's level (and the fee tier that follows), so the
test that drives it gets a second pair of eyes. `PlacementAttempt` (a lead solving
an approved test) lands in a later iteration (F1-5/F1-6).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class PlacementTest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending approval")
        APPROVED = "approved", _("Approved")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.PROTECT, null=True, blank=True, related_name="placement_tests"
    )
    branch = models.ForeignKey(
        "org.Branch", on_delete=models.PROTECT, null=True, blank=True, related_name="placement_tests"
    )
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    # The checker — must differ from created_by (maker-checker, enforced in the service).
    approved_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "created_at"))]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.title} ({self.status})"


class PlacementQuestion(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = "single_choice", _("Single choice")
        TRUE_FALSE = "true_false", _("True / false")
        WRITING = "writing", _("Writing (manually marked)")

    # Auto-gradable types carry a correct_answer; WRITING is marked by a human later.
    AUTO_GRADED_TYPES = (QuestionType.SINGLE_CHOICE, QuestionType.TRUE_FALSE)

    test = models.ForeignKey(PlacementTest, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    question_type = models.CharField(max_length=16, choices=QuestionType.choices)
    options = models.JSONField(default=list, blank=True)  # [str] for single_choice
    # str (a single_choice option) / bool (true_false) / null (writing). The "answer
    # key" that F1-6 auto-grading will score against; staff-only (never sent to leads).
    correct_answer = models.JSONField(null=True, blank=True)
    points = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        indexes = [models.Index(fields=("test", "order"))]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.test_id}:{self.prompt[:40]}"
