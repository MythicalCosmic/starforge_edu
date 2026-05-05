"""Click.uz payment provider stub.

Real integration requires merchant credentials + signed webhook handling.
For v1, this stub records intents and returns deterministic redirect URLs
so the rest of the system can be exercised end-to-end without live Click.
"""

from __future__ import annotations

from typing import Any


class ClickClient:
    PROVIDER = "click"

    def create_invoice(self, *, amount_uzs: int, order_id: str, return_url: str) -> dict[str, Any]:
        raise NotImplementedError("Click integration is a v1 stub")

    def verify_webhook(self, *, payload: dict[str, Any], signature: str) -> bool:
        raise NotImplementedError
