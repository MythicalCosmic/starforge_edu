"""Public-schema webhook intake (D3-B-5, TD-6).

The ONE sanctioned public→tenant hop. These are plain DRF ``APIView``s with
``authentication_classes = []`` / ``permission_classes = []`` — NOT
``TenantSafeModelViewSet``, whose ``initial()`` raises ``TenantContextMissing``
on the public schema (see ``core/viewsets.py``). The "authentication" here is the
PROVIDER SIGNATURE, not a JWT — providers push to us on the apex/public host.

Flow (CODE-GUIDE §3 item 5):
    resolve Center by slug (404 if absent/inactive)
      → schema_context(center.schema_name)
        → load that tenant's ProviderConfig
          → verify the signature BEFORE touching any row
            → record WebhookEvent (replay dedupe)
              → process

TD-18 envelope note: Click and Uzum errors use the standard ``{"error": {...}}``
envelope. **Payme speaks pure JSON-RPC 2.0** — HTTP 200 always, errors in the
``error`` member — which is the documented TD-18 exception (Payme's protocol is
non-negotiable). See WORKLOG / agents/API-CONTRACT.md.
"""

from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments import services
from apps.payments.models import Provider, ProviderConfig
from core.exceptions import ValidationException
from core.utils import client_ip


def _resolve_center(center_slug: str):
    """Resolve an active Center by slug on the public schema. Returns None → 404."""
    from apps.tenancy.models import Center

    return Center.objects.filter(slug=center_slug, is_active=True).first()


def _error(code: str, detail: str, *, http_status: int) -> Response:
    return Response({"error": {"code": code, "detail": detail}}, status=http_status)


class _PublicWebhookView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    provider: str = ""

    def _config(self) -> ProviderConfig | None:
        return ProviderConfig.objects.filter(provider=self.provider, is_active=True).first()


class ClickWebhookView(_PublicWebhookView):
    provider = Provider.CLICK

    def post(self, request, center_slug: str, *args, **kwargs):
        center = _resolve_center(center_slug)
        if center is None:
            return _error("not_found", "Center not found.", http_status=status.HTTP_404_NOT_FOUND)
        with schema_context(center.schema_name):
            config = self._config()
            payload = request.data if isinstance(request.data, dict) else {}
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
                provider=self.provider,
                event_id=event_id,
                payload=payload,
                remote_ip=client_ip(request),
                signature_valid=valid,
            )
            if not valid:
                return Response({"error": ERROR_SIGN_CHECK_FAILED, "error_note": "SIGN CHECK FAILED"})
            if not is_new:
                # Replay: side effects already ran — acknowledge without re-processing.
                return Response({"error": ERROR_SUCCESS, "error_note": "Already processed"})

            if int(payload.get("action", -1)) == ACTION_COMPLETE:
                from apps.finance.models import Invoice

                invoice = Invoice.objects.filter(number=payload.get("merchant_trans_id", "")).first()
                if invoice is not None:
                    try:
                        services.process_click_complete(payload=payload, invoice=invoice)
                    except ValidationException:
                        # Amount mismatch (provider reported != invoice total):
                        # reject the event so a Click retry is NOT swallowed as a
                        # duplicate, and never credit the invoice. Click reads the
                        # error member; -1 is its generic failure code.
                        services.mark_webhook_rejected(event)
                        return Response({"error": ERROR_SIGN_CHECK_FAILED, "error_note": "Amount mismatch"})
            services.mark_webhook_processed(event)
            return Response({"error": ERROR_SUCCESS, "error_note": "Success"})


class PaymeWebhookView(_PublicWebhookView):
    provider = Provider.PAYME

    def post(self, request, center_slug: str, *args, **kwargs):
        # Payme always returns HTTP 200 ONCE the tenant is resolved (errors live in
        # the JSON-RPC `error` member). An unknown/inactive center is a routing
        # failure (no tenant, no ProviderConfig) — it returns the TD-6 404 envelope
        # like every other webhook, BEFORE any tenant context is entered.
        from infrastructure.payments.payme import get_payme_client

        body: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
        center = _resolve_center(center_slug)
        if center is None:
            return _error("not_found", "Center not found.", http_status=status.HTTP_404_NOT_FOUND)
        with schema_context(center.schema_name):
            config = self._config()
            key = getattr(config, "payme_key", "") if config else ""
            auth_header = request.META.get("HTTP_AUTHORIZATION")
            store = services.PaymeDBStore()
            client = get_payme_client()

            # Replay dedupe is keyed on the Payme transaction id (params.id) for
            # the mutating methods; read-only methods are naturally idempotent.
            method = body.get("method")
            params = body.get("params") or {}
            if method in ("CreateTransaction",) and params.get("id"):
                # Payme's CreateTransaction is idempotent on params.id — a repeat of
                # the same id is an EXPECTED retry, not a nonce-replay, so it must
                # not be flagged `duplicate`. The handler echoes the existing txn.
                services.record_webhook_event(
                    provider=self.provider,
                    event_id=str(params["id"]),
                    payload=body,
                    remote_ip=client_ip(request),
                    signature_valid=client.verify_auth(auth_header=auth_header, key=key),
                    idempotent_retry=True,
                )
            response = client.handle(body=body, auth_header=auth_header, key=key, store=store)
            return Response(response)


class UzumWebhookView(_PublicWebhookView):
    provider = Provider.UZUM

    def post(self, request, center_slug: str, *args, **kwargs):
        center = _resolve_center(center_slug)
        if center is None:
            return _error("not_found", "Center not found.", http_status=status.HTTP_404_NOT_FOUND)
        with schema_context(center.schema_name):
            config = self._config()
            payload = request.data if isinstance(request.data, dict) else {}
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
                provider=self.provider,
                event_id=event_id,
                payload=payload,
                remote_ip=client_ip(request),
                signature_valid=valid,
            )
            if not valid:
                return _error(
                    "invalid_signature",
                    "Signature verification failed.",
                    http_status=status.HTTP_400_BAD_REQUEST,
                )
            if not is_new:
                return Response({"status": "duplicate"})

            from apps.finance.models import Invoice

            order_ref = payload.get("order_id") or payload.get("order_number") or payload.get("account", "")
            invoice = Invoice.objects.filter(number=order_ref).first()
            if invoice is not None:
                try:
                    services.process_uzum_payment(payload=payload, invoice=invoice)
                except ValidationException:
                    # Amount mismatch: reject (do not credit the invoice) and mark
                    # the event rejected so a retry is not swallowed as a duplicate.
                    services.mark_webhook_rejected(event)
                    return _error(
                        "amount_mismatch",
                        "Reported amount does not match the invoice total.",
                        http_status=status.HTTP_400_BAD_REQUEST,
                    )
            services.mark_webhook_processed(event)
            return Response({"status": "ok"})
