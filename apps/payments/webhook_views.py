"""Public-schema webhook intake (D3-B-5, TD-6), layered/off-DRF.

The ONE sanctioned public->tenant hop. These are PLAIN @csrf_exempt function views
with NO @require_auth — the "authentication" is the PROVIDER SIGNATURE, not a
session (providers push to us on the apex/public host). They return each provider's
EXACT expected response shape, NOT the success()/error() envelope.

Flow (CODE-GUIDE §3 item 5):
    resolve Center by slug (404 if absent/inactive)
      -> schema_context(center.schema_name)
        -> load that tenant's ProviderConfig
          -> verify the signature BEFORE touching any row
            -> record WebhookEvent (replay dedupe)
              -> process

TD-18 envelope note: Click and Uzum errors use the standard ``{"error": {...}}``
envelope. Payme speaks pure JSON-RPC 2.0 (HTTP 200 always, errors in the ``error``
member) — the documented TD-18 exception (Payme's protocol is non-negotiable).
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_tenants.utils import schema_context

from apps.payments import services
from apps.payments.models import Provider, ProviderConfig
from core.exceptions import ValidationException
from core.utils import client_ip


def _resolve_center(center_slug: str):
    """Resolve an active Center by slug on the public schema. Returns None -> 404."""
    from apps.tenancy.models import Center

    return Center.objects.filter(slug=center_slug, is_active=True).first()


def _error(code: str, detail: str, *, http_status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "detail": detail}}, status=http_status)


def _json_body(request: HttpRequest) -> dict[str, Any]:
    """The request body as a JSON object, or {} when empty / not an object /
    unparseable (providers post JSON; a garbage body must not 500)."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _config(provider: str) -> ProviderConfig | None:
    return ProviderConfig.objects.filter(provider=provider, is_active=True).first()


@csrf_exempt
def click_webhook_view(request: HttpRequest, center_slug: str) -> HttpResponse:
    if request.method != "POST":
        return _error("method_not_allowed", "Only POST is allowed.", http_status=405)
    center = _resolve_center(center_slug)
    if center is None:
        return _error("not_found", "Center not found.", http_status=404)
    with schema_context(center.schema_name):
        config = _config(Provider.CLICK)
        payload = _json_body(request)
        secret = getattr(config, "click_secret_key", "") if config else ""
        from infrastructure.payments.click import (
            ACTION_COMPLETE,
            ERROR_SIGN_CHECK_FAILED,
            ERROR_SUCCESS,
            get_click_client,
        )

        valid = bool(config) and get_click_client().verify_signature(payload=payload, secret_key=secret)
        event_id = str(payload.get("click_trans_id", "")) + ":" + str(payload.get("action", ""))
        event, is_new = services.record_webhook_event(
            provider=Provider.CLICK,
            event_id=event_id,
            payload=payload,
            remote_ip=client_ip(request),
            signature_valid=valid,
        )
        if not valid:
            return JsonResponse({"error": ERROR_SIGN_CHECK_FAILED, "error_note": "SIGN CHECK FAILED"})
        if not is_new:
            # Replay: side effects already ran — acknowledge without re-processing.
            return JsonResponse({"error": ERROR_SUCCESS, "error_note": "Already processed"})

        if int(payload.get("action", -1)) == ACTION_COMPLETE:
            from apps.finance.models import Invoice

            invoice = Invoice.objects.filter(number=payload.get("merchant_trans_id", "")).first()
            if invoice is not None:
                try:
                    services.process_click_complete(payload=payload, invoice=invoice)
                except ValidationException:
                    # Amount mismatch: reject the event so a Click retry is NOT swallowed
                    # as a duplicate, and never credit the invoice. -1 is Click's generic code.
                    services.mark_webhook_rejected(event)
                    return JsonResponse({"error": ERROR_SIGN_CHECK_FAILED, "error_note": "Amount mismatch"})
        services.mark_webhook_processed(event)
        return JsonResponse({"error": ERROR_SUCCESS, "error_note": "Success"})


@csrf_exempt
def payme_webhook_view(request: HttpRequest, center_slug: str) -> HttpResponse:
    if request.method != "POST":
        return _error("method_not_allowed", "Only POST is allowed.", http_status=405)
    # Payme always returns HTTP 200 ONCE the tenant is resolved (errors live in the
    # JSON-RPC `error` member). An unknown/inactive center is a routing failure -> the
    # TD-6 404 envelope, BEFORE any tenant context is entered.
    from infrastructure.payments.payme import get_payme_client

    body = _json_body(request)
    center = _resolve_center(center_slug)
    if center is None:
        return _error("not_found", "Center not found.", http_status=404)
    with schema_context(center.schema_name):
        config = _config(Provider.PAYME)
        key = getattr(config, "payme_key", "") if config else ""
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        store = services.PaymeDBStore()
        client = get_payme_client()

        method = body.get("method")
        # `params` is attacker-controlled: a dict body carrying a non-dict params
        # ([...], "x", 5) would make params.get("id") raise AttributeError -> 500,
        # breaking Payme's always-HTTP-200 JSON-RPC contract. Coerce to {}.
        raw_params = body.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        if method in ("CreateTransaction",) and params.get("id"):
            # Payme's CreateTransaction is idempotent on params.id — a repeat of the same
            # id is an EXPECTED retry, not a nonce-replay, so it must not be flagged
            # `duplicate`. The handler echoes the existing txn.
            services.record_webhook_event(
                provider=Provider.PAYME,
                event_id=str(params["id"]),
                payload=body,
                remote_ip=client_ip(request),
                signature_valid=client.verify_auth(auth_header=auth_header, key=key),
                idempotent_retry=True,
            )
        response = client.handle(body=body, auth_header=auth_header, key=key, store=store)
        return JsonResponse(response)


@csrf_exempt
def uzum_webhook_view(request: HttpRequest, center_slug: str) -> HttpResponse:
    if request.method != "POST":
        return _error("method_not_allowed", "Only POST is allowed.", http_status=405)
    center = _resolve_center(center_slug)
    if center is None:
        return _error("not_found", "Center not found.", http_status=404)
    with schema_context(center.schema_name):
        config = _config(Provider.UZUM)
        payload = _json_body(request)
        api_key = getattr(config, "uzum_api_key", "") if config else ""
        # Uzum sends the HMAC in the X-Signature header, not the body.
        signature = request.META.get("HTTP_X_SIGNATURE", "")
        from infrastructure.payments.uzum import get_uzum_client

        valid = bool(config) and get_uzum_client().verify_signature(
            payload=payload, signature=signature, api_key=api_key
        )
        event_id = str(
            payload.get("event_id") or payload.get("transaction_id") or payload.get("order_id", "")
        )
        event, is_new = services.record_webhook_event(
            provider=Provider.UZUM,
            event_id=event_id,
            payload=payload,
            remote_ip=client_ip(request),
            signature_valid=valid,
        )
        if not valid:
            return _error("invalid_signature", "Signature verification failed.", http_status=400)
        if not is_new:
            return JsonResponse({"status": "duplicate"})

        from apps.finance.models import Invoice

        order_ref = payload.get("order_id") or payload.get("order_number") or payload.get("account", "")
        invoice = Invoice.objects.filter(number=order_ref).first()
        if invoice is not None:
            try:
                services.process_uzum_payment(payload=payload, invoice=invoice)
            except ValidationException:
                # Amount mismatch: reject (do not credit the invoice) and mark the event
                # rejected so a retry is not swallowed as a duplicate.
                services.mark_webhook_rejected(event)
                return _error(
                    "amount_mismatch",
                    "Reported amount does not match the invoice total.",
                    http_status=400,
                )
        services.mark_webhook_processed(event)
        return JsonResponse({"status": "ok"})
