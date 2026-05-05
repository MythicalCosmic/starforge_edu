"""Project-wide exceptions and the DRF exception handler."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

logger = logging.getLogger("starforge.exceptions")


class StarforgeError(Exception):
    """Base for all domain errors. Carries a stable code + detail."""

    code: str = "error"
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_detail: str = "Something went wrong."

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        self.detail = detail or self.default_detail
        self.code = code or self.code
        super().__init__(self.detail)


class ValidationException(StarforgeError):
    code = "validation_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid input."


class PermissionException(StarforgeError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You don't have permission to do that."


class NotFoundException(StarforgeError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Resource not found."


class ThrottledException(StarforgeError):
    code = "throttled"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Too many requests."


class TenantContextMissing(StarforgeError):
    """Raised when tenant-scoped code runs without an active schema."""

    code = "tenant_required"
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "No active tenant context."


def drf_exception_handler(exc: BaseException, context: dict[str, Any]) -> Response | None:
    """Wrap DRF's default handler so all errors share an envelope."""

    if isinstance(exc, StarforgeError):
        return Response(
            {"error": {"code": exc.code, "detail": exc.detail}},
            status=exc.status_code,
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {"error": {"code": "forbidden", "detail": str(exc) or "Forbidden."}},
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, Http404):
        return Response(
            {"error": {"code": "not_found", "detail": "Resource not found."}},
            status=status.HTTP_404_NOT_FOUND,
        )

    response = drf_default_handler(exc, context)
    if response is not None:
        response.data = {"error": {"code": "api_error", "detail": response.data}}
    else:
        logger.exception("Unhandled exception in view", extra={"context": context})
    return response
