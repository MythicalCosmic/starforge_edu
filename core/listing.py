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


def cursor_paginate(
    request: HttpRequest, queryset: QuerySet, *, page_size: int = 50, max_page_size: int = MAX_PAGE_SIZE
) -> tuple[list[Any], str | None, str | None]:
    """Keyset cursor pagination for an append-only timeline ordered ``(-created_at, -id)``.

    Stable under concurrent head-inserts (unlike offset pagination) — what an audit /
    activity feed needs: a ``?cursor`` walks the timeline by the (created_at, id) of the
    edge row, so newer rows inserted at the head between page reads never shift a page.
    Pure Django (no DRF): the opaque cursor is ``base64("<dir>|<iso>|<id>")``.

    ``queryset`` MUST already be ordered ``(-created_at, -id)``. Returns
    ``(rows, next_link, previous_link)`` — the links are absolute URLs (or ``None``)
    carrying the ``?cursor`` and preserving the request's other query params (filters).
    """
    size = min(_positive_int(request.GET.get("page_size"), page_size), max_page_size)
    direction, ts, obj_id = "f", None, None
    token = request.GET.get("cursor")
    if token:
        direction, ts, obj_id = _decode_cursor(token)

    if direction == "b":
        # Walk backwards (towards NEWER rows): fetch ascending past the cursor, then
        # re-present newest-first so the page reads in the timeline's native order.
        rows = list(
            queryset.filter(Q(created_at__gt=ts) | Q(created_at=ts, id__gt=obj_id)).order_by(
                "created_at", "id"
            )[: size + 1]
        )
        has_more = len(rows) > size
        rows = rows[:size]
        rows.reverse()
        has_next, has_previous = True, has_more
    else:
        qs = queryset
        if ts is not None:  # forward from a cursor -> strictly OLDER rows
            qs = qs.filter(Q(created_at__lt=ts) | Q(created_at=ts, id__lt=obj_id))
        rows = list(qs[: size + 1])
        has_more = len(rows) > size
        rows = rows[:size]
        # A forward cursor means newer rows exist (the page we came from) -> has_previous.
        has_next, has_previous = has_more, ts is not None

    next_link = _cursor_link(request, "f", rows[-1]) if (rows and has_next) else None
    previous_link = _cursor_link(request, "b", rows[0]) if (rows and has_previous) else None
    return rows, next_link, previous_link


def _cursor_link(request: HttpRequest, direction: str, row: Any) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    token = _encode_cursor(direction, row.created_at, row.id)
    parts = urlparse(request.build_absolute_uri())
    query = parse_qs(parts.query)
    query["cursor"] = [token]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def _encode_cursor(direction: str, created_at: Any, obj_id: int) -> str:
    import base64

    raw = f"{direction}|{created_at.isoformat()}|{obj_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(token: str) -> tuple[str, Any, int]:
    import base64
    import binascii

    from django.utils.dateparse import parse_datetime

    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        direction, iso, raw_id = raw.split("|")
        created_at = parse_datetime(iso)
        if direction not in ("f", "b") or created_at is None:
            raise ValueError
        return direction, created_at, int(raw_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise _bad_filter("cursor") from exc


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
