"""In-app messaging endpoints — plain Django views over the layered stack.

Strict participant isolation: you only ever resolve threads you're a member of, so every
detail/action is participant-gated (an out-of-scope thread 404s). Opening a thread is
messaging:write; reading + listing is messaging:read; POSTing a message additionally
requires messaging:write (so an A-2 write-revoke makes a role read-only). Messages are
append-only. The only PATCH is the caller's own per-thread notification preference;
messages themselves have no PUT/PATCH/DELETE surface.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from apps.messaging.dto.thread_dto import CreateThreadDTO
from apps.messaging.interfaces.services import IThreadService
from apps.messaging.presenters import contact_to_dict, message_to_dict, thread_to_dict
from core.api_auth import check_perm, require_auth
from core.container import container
from core.exceptions import NotFoundException, ValidationException
from core.http import int_field, read_json, str_field
from core.listing import apply_filters, paginate
from core.responses import created, error, paginated, success

_RESOURCE = "messaging"
_MAX_PARTICIPANTS = 100
_MAX_ATTACHMENTS = 10
_MAX_MESSAGE_WINDOW = timedelta(hours=26)


def _service() -> IThreadService:
    return container.resolve(IThreadService)  # type: ignore[type-abstract]


def _viewer_id(request: HttpRequest) -> int:
    user: Any = request.user  # a real User post-@require_auth (typed User|AnonymousUser)
    return user.pk


def _unread_map(request: HttpRequest, threads: list) -> dict[int, int]:
    """One bounded query for {thread_id: unread_count} across the given threads."""
    return _service().unread_counts(thread_ids=[t.id for t in threads], viewer_id=_viewer_id(request))


def _get_thread(request: HttpRequest, pk: int):
    thread = _service().get_thread(user=request.user, pk=pk)
    if thread is None:
        raise NotFoundException(code="not_found")  # non-participant -> 404, strict isolation
    return thread


def _message_window(request: HttpRequest):
    """Return a bounded, timezone-aware half-open message range.

    Mobile calendar days are converted to UTC by the client. Requiring both
    bounds prevents a date jump from accidentally turning into an unbounded
    history scan, while the half-open interval keeps adjacent days disjoint.
    """
    raw_gte = request.GET.get("created_at_gte", "").strip()
    raw_lt = request.GET.get("created_at_lt", "").strip()
    if not raw_gte and not raw_lt:
        return None
    if not raw_gte or not raw_lt:
        raise ValidationException(
            "created_at_gte and created_at_lt must be provided together.",
            code="validation_error",
            fields={
                "created_at_gte": ["Provide both UTC bounds."],
                "created_at_lt": ["Provide both UTC bounds."],
            },
        )

    try:
        lower = parse_datetime(raw_gte)
        upper = parse_datetime(raw_lt)
    except (OverflowError, ValueError):
        lower = upper = None
    if lower is None or upper is None or not timezone.is_aware(lower) or not timezone.is_aware(upper):
        raise ValidationException(
            "Message date bounds must be timezone-aware ISO-8601 datetimes.",
            code="validation_error",
            fields={
                "created_at_gte": ["Use an ISO-8601 datetime with an offset or Z."],
                "created_at_lt": ["Use an ISO-8601 datetime with an offset or Z."],
            },
        )
    if lower >= upper:
        raise ValidationException(
            "created_at_gte must be earlier than created_at_lt.",
            code="validation_error",
            fields={"created_at_lt": ["Must be later than created_at_gte."]},
        )
    if upper - lower > _MAX_MESSAGE_WINDOW:
        raise ValidationException(
            "A message date window cannot exceed 26 hours.",
            code="validation_error",
            fields={"created_at_lt": ["Choose one local calendar day."]},
        )
    return lower, upper


@csrf_exempt
@require_auth
def contacts_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    category = request.GET.get("category", "").strip().lower()
    if category not in ("", "staff", "student"):
        raise ValidationException(
            "category must be staff or student.",
            code="validation_error",
            fields={"category": ["Choose staff or student."]},
        )
    qs = _service().contacts(user=request.user, category=category)
    qs = apply_filters(
        request,
        qs,
        search_fields=(
            "username",
            "staff_profile__first_name",
            "staff_profile__middle_name",
            "staff_profile__last_name",
            "teacher_profile__first_name",
            "teacher_profile__middle_name",
            "teacher_profile__last_name",
            "student_profile__first_name",
            "student_profile__middle_name",
            "student_profile__last_name",
        ),
    )
    items, total, page, size = paginate(request, qs)
    return paginated(
        [contact_to_dict(contact) for contact in items],
        total=total,
        page=page,
        page_size=size,
        pagination_extra={"self_user_id": _viewer_id(request)},
    )


@csrf_exempt
@require_auth
def threads_collection_view(request: HttpRequest) -> HttpResponse:
    if request.method in ("GET", "HEAD"):
        check_perm(request, f"{_RESOURCE}:read")
        qs = _service().scoped_threads(user=request.user)
        # Meta.ordering is compound ("-last_message_at","-created_at") -> omit
        # default_ordering so apply_filters preserves it (only ?ordering re-orders).
        qs = apply_filters(request, qs, ordering_fields=("last_message_at", "created_at"))
        items, total, page, size = paginate(request, qs)
        unread = _unread_map(request, items)
        rows = [
            thread_to_dict(
                t,
                unread_count=unread.get(t.id, 0),
                viewer_id=_viewer_id(request),
            )
            for t in items
        ]
        return paginated(rows, total=total, page=page, page_size=size)
    if request.method == "POST":
        check_perm(request, f"{_RESOURCE}:write")
        return _create_thread(request)
    return error("Method not allowed.", code="method_not_allowed", status=405)


@csrf_exempt
@require_auth
def thread_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    thread = _get_thread(request, pk)
    unread = _unread_map(request, [thread])
    return success(
        thread_to_dict(
            thread,
            unread_count=unread.get(thread.id, 0),
            viewer_id=_viewer_id(request),
        )
    )


@csrf_exempt
@require_auth
def thread_messages_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method not in ("GET", "HEAD", "POST"):
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")  # floor for both list + send
    thread = _get_thread(request, pk)  # participant gate (404) BEFORE the write check
    if request.method == "POST":
        check_perm(request, f"{_RESOURCE}:write")  # posting additionally needs write
        return _send_message(request, thread)
    qs = _service().messages_of(thread=thread)
    window = _message_window(request)
    if window is not None:
        lower, upper = window
        qs = qs.filter(created_at__gte=lower, created_at__lt=upper)
    items, total, page, size = paginate(request, qs)
    return paginated([message_to_dict(m) for m in items], total=total, page=page, page_size=size)


@csrf_exempt
@require_auth
def thread_read_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    thread = _get_thread(request, pk)
    _service().mark_read(thread=thread, user=request.user)
    return success({"status": "ok"})


@csrf_exempt
@require_auth
def thread_preferences_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "PATCH":
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    thread = _get_thread(request, pk)
    body = read_json(request)
    if not isinstance(body.get("notifications_muted"), bool):
        raise ValidationException(
            "notifications_muted must be a boolean.",
            code="validation_error",
            fields={"notifications_muted": ["Provide true or false."]},
        )
    muted = body["notifications_muted"]
    _service().set_notifications_muted(
        thread=thread,
        user=request.user,
        muted=muted,
    )
    return success({"notifications_muted": muted})


@csrf_exempt
@require_auth
def attachment_upload_url_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:write")
    body = read_json(request)
    filename = str_field(body, "filename", max_length=255).strip()
    if not filename:
        raise ValidationException(
            "filename is required.", code="validation_error", fields={"filename": ["Required."]}
        )
    size_bytes = int_field(body, "size_bytes", required=True)
    if size_bytes is None or size_bytes < 1:
        raise ValidationException(
            "size_bytes must be positive.",
            code="validation_error",
            fields={"size_bytes": ["Must be at least 1."]},
        )
    content_type = str_field(body, "content_type", default="application/octet-stream", max_length=127).strip()
    return success(
        _service().presign_attachment(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            requested_by=request.user,
        )
    )


@csrf_exempt
@require_auth
def thread_attachment_download_view(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method not in ("GET", "HEAD"):
        return error("Method not allowed.", code="method_not_allowed", status=405)
    check_perm(request, f"{_RESOURCE}:read")
    thread = _get_thread(request, pk)
    key = request.GET.get("key", "").strip()
    if not key or len(key) > 512 or "\x00" in key:
        raise ValidationException(
            "key is required.", code="validation_error", fields={"key": ["Provide a valid attachment key."]}
        )
    return success({"url": _service().attachment_download_url(thread=thread, key=key), "expires_in": 300})


# --- helpers ---------------------------------------------------------------
def _create_thread(request: HttpRequest) -> HttpResponse:
    body = read_json(request)
    dto = CreateThreadDTO(
        participant_ids=_participant_ids(body),
        subject=str_field(body, "subject", max_length=200).strip(),
        first_body=str_field(body, "first_body").strip(),
        attachments=_attachments(body),
    )
    thread = _service().create(dto, creator=request.user)
    # A freshly created thread's only message is the creator's own opener -> unread 0.
    return created(thread_to_dict(thread, unread_count=0, viewer_id=_viewer_id(request)))


def _send_message(request: HttpRequest, thread) -> HttpResponse:
    body = read_json(request)
    text = str_field(body, "body").strip()
    attachments = _attachments(body)
    if not text and not attachments:
        raise ValidationException(
            "A message needs text or an attachment.",
            code="validation_error",
            fields={"body": ["Provide text or at least one attachment."]},
        )
    message = _service().post(thread=thread, sender=request.user, body=text, attachments=attachments)
    return created(message_to_dict(message))


def _participant_ids(body: dict[str, Any]) -> list[int]:
    """A non-empty list of integer user ids (deduped, order-preserving). Each MUST be an
    int (a non-int would break `id__in` / the dict.fromkeys dedup, and an unhashable one
    would 500) — the old ListField(child=IntegerField()) enforced this."""
    raw = body.get("participant_ids")
    if not isinstance(raw, list) or not raw:
        raise ValidationException(
            "participant_ids must be a non-empty list.",
            code="validation_error",
            fields={"participant_ids": ["Provide at least one participant id."]},
        )
    if len(raw) > _MAX_PARTICIPANTS:
        raise ValidationException(
            "Too many participants.",
            code="validation_error",
            fields={"participant_ids": [f"At most {_MAX_PARTICIPANTS} participants are allowed."]},
        )
    ids: list[int] = []
    for value in raw:
        if isinstance(value, bool):
            raise _bad_ids()
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str):
            try:
                ids.append(int(value))
            except ValueError:
                raise _bad_ids() from None
        else:
            raise _bad_ids()
    return list(dict.fromkeys(ids))


def _bad_ids() -> ValidationException:
    return ValidationException(
        "Each participant id must be an integer.",
        code="validation_error",
        fields={"participant_ids": ["Each id must be an integer."]},
    )


def _attachments(body: dict[str, Any]) -> list[str]:
    """Validated, unique messaging upload-grant keys; explicit null is invalid."""
    if "attachments" not in body:
        return []
    raw = body["attachments"]
    if not isinstance(raw, list):
        raise ValidationException(
            "attachments must be a list.",
            code="validation_error",
            fields={"attachments": ["Must be a list of keys."]},
        )
    if len(raw) > _MAX_ATTACHMENTS:
        raise ValidationException(
            "Too many attachments.",
            code="validation_error",
            fields={"attachments": [f"At most {_MAX_ATTACHMENTS} attachments are allowed."]},
        )
    if any(not isinstance(key, str) or not key.strip() or len(key) > 512 for key in raw):
        raise ValidationException(
            "Invalid attachment key.",
            code="validation_error",
            fields={"attachments": ["Each key must be non-empty text of at most 512 characters."]},
        )
    keys = [key.strip() for key in raw]
    if len(keys) != len(set(keys)):
        raise ValidationException(
            "Duplicate attachment key.",
            code="validation_error",
            fields={"attachments": ["Attachment keys must be unique."]},
        )
    return keys
