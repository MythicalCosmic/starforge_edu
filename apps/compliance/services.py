"""Rule book services: create/update (auto version-bump on body change) +
acknowledge."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.compliance.models import Penalty, Rule, RuleAcknowledgment
from core.exceptions import NotFoundException, UnprocessableEntity


@transaction.atomic
def update_rule_body(*, rule: Rule, body: str | None = None, title: str | None = None, **fields) -> Rule:
    """Apply edits; bump the version (forcing re-acknowledgment) only when the body
    actually changes."""
    if body is not None and body != rule.body:
        rule.body = body
        rule.version += 1
    if title is not None:
        rule.title = title
    for key, value in fields.items():
        setattr(rule, key, value)
    rule.save()
    return rule


@transaction.atomic
def acknowledge(*, rule: Rule, user) -> RuleAcknowledgment:
    """Record that `user` accepted the CURRENT version of `rule`. Idempotent."""
    ack, _created = RuleAcknowledgment.objects.get_or_create(rule=rule, user=user, version=rule.version)
    return ack


@transaction.atomic
def issue_penalty(*, student, points: int, reason: str, issued_by, rule=None) -> Penalty:
    """Issue a demerit against a student. The branch is taken from the student, so the
    penalty is always attributable to where the student belongs (no branch guessing)."""
    return Penalty.objects.create(
        student=student,
        points=points,
        reason=reason,
        branch=student.branch,
        issued_by=issued_by,
        rule=rule,
    )


@transaction.atomic
def waive_penalty(*, penalty_id: int, actor, reason: str = "") -> Penalty:
    """Reverse an active penalty (a manager corrects a mistake / accepts an appeal).
    Locked + active-only, so a penalty can't be double-waived. Issuing (penalty:write)
    and waiving (penalty:waive) are separate permissions — the teacher who issued a
    demerit can't quietly undo it; a manager must."""
    penalty = Penalty.objects.select_for_update().filter(pk=penalty_id).first()
    if penalty is None:
        raise NotFoundException(_("Penalty not found."), code="penalty_not_found")
    if penalty.status != Penalty.Status.ACTIVE:
        raise UnprocessableEntity(_("Only an active penalty can be waived."), code="penalty_not_active")
    penalty.status = Penalty.Status.WAIVED
    penalty.waived_by = actor
    penalty.waived_at = timezone.now()
    penalty.waive_reason = reason
    penalty.save(update_fields=["status", "waived_by", "waived_at", "waive_reason"])
    return penalty
