"""Rule book / policy acknowledgment (PRODUCT_VISION #12).

Each center has a rule book. Everyone must be FORCED to read and accept the rules
that apply to their role, and re-accept when a rule changes (version bump). Content
is role-filtered: a cashier shouldn't see teacher-only rules.
"""

from __future__ import annotations

from django.db import models


class Rule(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    # Bumped whenever the body changes -> everyone must re-acknowledge.
    version = models.PositiveIntegerField(default=1)
    # Role codes this rule applies to (e.g. ["teacher", "assistant"]); empty = everyone.
    applies_to_roles = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.title} v{self.version}"


class RuleAcknowledgment(models.Model):
    """One person's acceptance of one rule AT a specific version. A new version
    leaves the old ack in place but no longer counts as 'current', so the rule
    re-appears as pending."""

    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="acknowledgments")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="rule_acknowledgments")
    version = models.PositiveIntegerField()
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-acknowledged_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("rule", "user", "version"), name="one_ack_per_rule_user_version"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ack:{self.user_id}:{self.rule_id}v{self.version}"
