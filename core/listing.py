"""List-endpoint helpers for the layered (plain-view) style — the filtering, search,
ordering, and pagination that DRF's filter backends + paginator gave a ViewSet, as
composable functions a plain ``list_view`` calls before handing the page to a presenter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.core.exceptions import FieldError
from django.db import models
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from core.exceptions import ValidationException

_TRUE = ("true", "1", "yes", "t")
_FALSE = ("false", "0", "no", "f")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
# A page whose offset would exceed this is treated as past-the-end (empty) rather
# than passed to the DB — Postgres OFFSET is a bigint and a giant ?page overflows it.
_MAX_OFFSET = 1_000_000_000


def apply_filters(
    request: HttpRequest,
    queryset: QuerySet,
    *,
    filter_fields: Sequence[str] = (),
    search_fields: Sequence[str] = (),
    ordering_fields: Sequence[str] = (),
    default_ordering: str | None = None,
) -> QuerySet:
    """Apply ``?<field>=`` exact filters, ``?search=`` (icontains across
    ``search_fields``), and ``?ordering=`` (whitelisted to ``ordering_fields``,
    leading ``-`` for desc). Unknown ordering falls back to ``default_ordering``."""
    for field in filter_fields:
        raw = request.GET.get(field)
        if not raw:
            continue
        value: Any = raw
        # Coerce a boolean query param ("true"/"false"/"1"/"0") — Django's model
        # BooleanField rejects lowercase "true" and would raise ValidationError.
        try:
            model_field = queryset.model._meta.get_field(field.split("__")[0])
        except Exception:
            model_field = None
        if isinstance(model_field, models.BooleanField):
            low = raw.lower()
            if low in _TRUE:
                value = True
            elif low in _FALSE:
                value = False
            else:
                continue  # unparseable boolean — ignore the filter rather than 500
        elif "\x00" in raw:
            raise _bad_filter(field)  # NUL bytes crash psycopg at bind time
        # A non-numeric value for an int/FK-typed field raises ValueError at query-build
        # time; turn that into a clean 400 instead of a leaked 500.
        try:
            queryset = queryset.filter(**{field: value})
        except (ValueError, FieldError, ValidationException):
            raise _bad_filter(field) from None

    term = request.GET.get("search")
    if term and search_fields:
        if "\x00" in term:
            raise _bad_filter("search")
        clause = Q()
        for field in search_fields:
            clause |= Q(**{f"{field}__icontains": term})
        queryset = queryset.filter(clause)

    ordering = request.GET.get("ordering")
    if ordering and ordering.lstrip("-") in ordering_fields:
        queryset = queryset.order_by(ordering)
    elif default_ordering is not None:
        queryset = queryset.order_by(default_ordering)
    return queryset


def paginate(
    request: HttpRequest, queryset: QuerySet, *, default_size: int = DEFAULT_PAGE_SIZE
) -> tuple[list[Any], int, int, int]:
    """Slice ``queryset`` by ``?page`` / ``?page_size`` (size capped at MAX_PAGE_SIZE).
    Returns ``(items, total, page, page_size)``; counts before slicing for the meta.
    Pass the result to ``core.responses.paginated`` after mapping items to dicts."""
    page = _positive_int(request.GET.get("page"), 1)
    size = min(_positive_int(request.GET.get("page_size"), default_size), MAX_PAGE_SIZE)
    total = queryset.count()
    start = (page - 1) * size
    if start > _MAX_OFFSET:
        # Past-the-end (a giant ?page): return an empty page instead of overflowing
        # the DB's bigint OFFSET with a 500.
        return [], total, page, size
    return list(queryset[start : start + size]), total, page, size


def _positive_int(raw: str | None, fallback: int) -> int:
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return value if value >= 1 else fallback


def _bad_filter(field: str) -> ValidationException:
    return ValidationException(
        f"Invalid value for filter '{field}'.",
        code="validation_error",
        fields={field: ["Invalid value."]},
    )
