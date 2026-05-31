"""Middleware that publishes the request's actor into the audit ContextVar."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .context import ActorContext, reset_actor, set_actor


def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        token = set_actor(
            ActorContext(
                user=user if getattr(user, "is_authenticated", False) else None,
                ip=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        )
        try:
            return self.get_response(request)
        finally:
            reset_actor(token)
