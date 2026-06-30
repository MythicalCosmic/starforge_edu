"""Request helpers for the layered (plain-Django) view style — parse the JSON body
the way DTOs are built from it. Bad JSON / non-object bodies are a clean 400."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from core.exceptions import ValidationException


def read_json(request: HttpRequest) -> dict[str, Any]:
    """The request body as a JSON object (``{}`` when empty). 400 on invalid JSON or a
    non-object body (a list/number/string)."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        raise ValidationException(_("Request body must be valid JSON."), code="invalid_json") from None
    if not isinstance(data, dict):
        raise ValidationException(_("Request body must be a JSON object."), code="invalid_json")
    return data


def str_field(data: dict[str, Any], name: str, *, default: str = "") -> str:
    """A string field, coerced from None to ``default``; a non-string is a 400."""
    value = data.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValidationException(
            _("%(field)s must be a string.") % {"field": name},
            code="validation_error",
            fields={name: ["Must be a string."]},
        )
    return value
