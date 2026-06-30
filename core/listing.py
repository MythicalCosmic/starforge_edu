"""List-endpoint helpers for the layered (plain-view) style — the filtering, search,
ordering, and pagination that DRF's filter backends + paginator gave a ViewSet, as
composable functions a plain ``list_view`` calls before handing the page to a presenter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db import models
from django.db.models import Q, QuerySet
from django.http import HttpRequest

_TRUE = ("true", "1", "yes", "t")
_FALSE = ("false", "0", "no", "f")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


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
        queryset = queryset.filter(**{field: value})

    term = request.GET.get("search")
    if term and search_fields:
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
    return list(queryset[start : start + size]), total, page, size


def _positive_int(raw: str | None, fallback: int) -> int:
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return value if value >= 1 else fallback
