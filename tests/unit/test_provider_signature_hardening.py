from __future__ import annotations

import base64

from infrastructure.payments.click import RealClickClient
from infrastructure.payments.payme import RealPaymeClient
from infrastructure.payments.uzum import RealUzumClient


def test_uzum_non_ascii_signature_is_rejected_without_type_error():
    client = RealUzumClient()
    assert client.verify_signature(payload={"order": "1"}, signature="é", api_key="secret") is False


def test_click_non_ascii_signature_is_rejected_without_type_error():
    client = RealClickClient()
    payload = {
        "click_trans_id": "1",
        "service_id": "2",
        "merchant_trans_id": "3",
        "amount": "100",
        "action": 0,
        "sign_time": "2026-01-01",
        "sign_string": "é",
    }
    assert client.verify_signature(payload=payload, secret_key="secret") is False


def test_payme_non_ascii_basic_secret_is_rejected_without_type_error():
    token = base64.b64encode("Paycom:ключ".encode()).decode()
    assert RealPaymeClient().verify_auth(auth_header=f"Basic {token}", key="secret") is False
