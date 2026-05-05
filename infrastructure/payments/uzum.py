"""Uzum payment provider stub."""

from __future__ import annotations

from typing import Any


class UzumClient:
    PROVIDER = "uzum"

    def create_invoice(self, *, amount_uzs: int, order_id: str) -> dict[str, Any]:
        raise NotImplementedError("Uzum integration is a v1 stub")

    def verify_webhook(self, *, payload: dict[str, Any], signature: str) -> bool:
        raise NotImplementedError
