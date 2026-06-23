"""Rule book services: create/update (auto version-bump on body change) +
acknowledge."""

from __future__ import annotations

from django.db import transaction

from apps.compliance.models import Rule, RuleAcknowledgment


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
    ack, _created = RuleAcknowledgment.objects.get_or_create(
        rule=rule, user=user, version=rule.version
    )
    return ack
