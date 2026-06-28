"""Cards services (F12-1): define card types, issue / revoke cards, scan to check in."""

from __future__ import annotations

import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.cards.models import Card, CardScan, CardType
from core.exceptions import NotFoundException, UnprocessableEntity


@transaction.atomic
def create_card_type(*, name: str, created_by=None) -> CardType:
    return CardType.objects.create(name=name, created_by=created_by)


@transaction.atomic
def set_card_type_active(*, card_type: CardType, is_active: bool) -> CardType:
    card_type.is_active = is_active
    card_type.save(update_fields=["is_active", "updated_at"])
    return card_type


def _generate_code() -> str:
    """A unique, hard-to-guess scan payload (~22 url-safe chars = 128 bits)."""
    return secrets.token_urlsafe(16)


@transaction.atomic
def issue_card(*, student, card_type: CardType, issued_by=None) -> Card:
    """Issue a card of `card_type` to `student` with a fresh unique code. A retired card
    type can't be issued. The unique-code generation retries on the astronomically
    unlikely collision so it never surfaces as a 500."""
    if not card_type.is_active:
        raise UnprocessableEntity(_("That card type is retired."), code="card_type_inactive")
    for _attempt in range(5):
        try:
            with transaction.atomic():
                return Card.objects.create(
                    student=student, card_type=card_type, code=_generate_code(), issued_by=issued_by
                )
        except IntegrityError:
            continue  # code collision — try a new one
    raise UnprocessableEntity(_("Could not allocate a unique card code."), code="card_code_unavailable")


@transaction.atomic
def revoke_card(*, card_id: int, actor=None, reason: str = "") -> Card:
    """Deactivate a card (lost / replaced). Locked + active-only so it can't be double-
    revoked; a revoked card then scans as invalid."""
    card = Card.objects.select_for_update().filter(pk=card_id).first()
    if card is None:
        raise NotFoundException(_("Card not found."), code="card_not_found")
    if not card.is_active:
        raise UnprocessableEntity(_("This card is already revoked."), code="card_not_active")
    card.is_active = False
    card.revoked_at = timezone.now()
    card.revoke_reason = reason
    card.save(update_fields=["is_active", "revoked_at", "revoke_reason"])
    return card


@transaction.atomic
def scan_card(*, code: str, scanned_by=None) -> dict:
    """Scan a card code to check a student in. An unknown code is a clean 404; a known
    code is ALWAYS logged (even a revoked card — the audit trail of an attempted entry),
    and the result reports whether the card was valid + who it belongs to."""
    card = (
        Card.objects.select_related("student__user", "card_type")
        .filter(code=(code or "").strip())
        .first()
    )
    if card is None:
        raise NotFoundException(_("No card matches that code."), code="card_not_found")
    valid = card.is_active
    scan = CardScan.objects.create(card=card, scanned_by=scanned_by, was_valid=valid)
    student = card.student
    return {
        "scan_id": scan.pk,
        "valid": valid,
        "student": student.pk,
        "student_name": (student.user.get_full_name() if student.user else "") or "",
        "card_type": card.card_type.name,
        "scanned_at": scan.scanned_at,
    }
