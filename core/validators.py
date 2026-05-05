"""Reusable field validators."""

from __future__ import annotations

import phonenumbers
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_phone(value: str) -> None:
    """E.164 validation with Uzbekistan as default region."""

    try:
        parsed = phonenumbers.parse(value, "UZ")
    except phonenumbers.NumberParseException as exc:
        raise ValidationError(_("Invalid phone number.")) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationError(_("Invalid phone number."))


def normalize_phone(value: str) -> str:
    """Return E.164 representation, defaulting region to UZ."""

    parsed = phonenumbers.parse(value, "UZ")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
