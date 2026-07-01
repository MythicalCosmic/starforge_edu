"""CenterSettings endpoint — GET/PATCH the TD-13 singleton. org:read to read,
org:write to update."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.org.interfaces.services import ICenterSettingsService
from apps.org.presenters import settings_to_dict
from core.api_auth import check_perm, require_auth
from core.container import container
from core.http import read_json
from core.responses import error, success

_RESOURCE = "org"


def _service() -> ICenterSettingsService:
    return container.resolve(ICenterSettingsService)  # type: ignore[type-abstract]


@csrf_exempt
@require_auth
def settings_view(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        check_perm(request, f"{_RESOURCE}:read")
        return success(settings_to_dict(_service().read()))
    if request.method in ("PATCH", "PUT"):
        check_perm(request, f"{_RESOURCE}:write")
        return success(settings_to_dict(_service().update(read_json(request))))
    return error("Method not allowed.", code="method_not_allowed", status=405)
