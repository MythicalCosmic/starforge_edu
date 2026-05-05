"""Payme.uz payment provider stub.

Payme uses JSON-RPC over HTTP for webhooks. For v1 this stub holds the
shape so apps.payments can register the model + URL routing now and
swap implementations later.
"""

from __future__ import annotations

from typing import Any


class PaymeClient:
    PROVIDER = "payme"

    def create_invoice(self, *, amount_uzs: int, order_id: str) -> dict[str, Any]:
        raise NotImplementedError("Payme integration is a v1 stub")

    def handle_jsonrpc(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
