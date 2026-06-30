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


def _bad(name: str, msg: str) -> ValidationException:
    return ValidationException(
        _("%(field)s: %(msg)s") % {"field": name, "msg": msg},
        code="validation_error",
        fields={name: [msg]},
    )


def str_field(data: dict[str, Any], name: str, *, default: str = "") -> str:
    """A string field, coerced from None to ``default``; a non-string is a 400."""
    value = data.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise _bad(name, "Must be a string.")
    return value


def int_field(data: dict[str, Any], name: str, *, required: bool = False, default: int | None = None) -> int | None:
    """An int field (accepts an int or a numeric string). Missing -> default / 400 if required."""
    if name not in data or data[name] is None:
        if required:
            raise _bad(name, "This field is required.")
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _bad(name, "Must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _bad(name, "Must be an integer.") from None


def bool_field(data: dict[str, Any], name: str, *, default: bool = False) -> bool:
    """A bool field (accepts a JSON bool or "true"/"false"/"1"/"0")."""
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "t")
    raise _bad(name, "Must be a boolean.")
