"""D3-F-1/2/3 — webhook signature tampering, replay protection, wrong-tenant slug.

Adversarial coverage of the public-schema webhook intake (TD-6):
``POST /api/v1/webhooks/<provider>/<center_slug>/``. The webhook is posted to
the apex/public host; the view resolves the tenant by slug, enters
``schema_context``, loads that tenant's ProviderConfig, and verifies the
provider signature BEFORE touching any row (CODE-GUIDE §3 item 5).

F-1 signature tampering:
  - Click bad sign -> error ``-1``, zero Payment rows.
  - Payme wrong HTTP Basic -> ``-32504``, HTTP 200, JSON-RPC error member.
  - Uzum bad HMAC -> rejected, ``WebhookEvent.status == "rejected"``.

F-2 replay protection:
  - Same Payme ``CreateTransaction`` id twice -> identical response, ONE Payment.
  - Same Click ``click_trans_id`` complete twice -> second recorded as
    ``duplicate``; allocation runs exactly once (assert allocation row count).

F-3 wrong-tenant slug:
  - A signature valid for center A posted to center B's slug fails against B's
    ProviderConfig (Payme: account error in -31050..-31099); no rows either side.
  - A nonexistent slug -> 404 envelope.

Lane B builds the clients/views in parallel; lane imports are lazy. The
orchestrator runs this on Postgres after A..E merge.
"""

from __future__ import annotations

import pytest

from apps.payments.tests import _helpers as helpers
from apps.payments.tests import builders as bld

pytestmark = pytest.mark.django_db

AMOUNT_UZS = "150000.00"
AMOUNT_TIYIN = 15_000_000
ACCOUNT = {"order_id": "INV-2026-000001"}


@pytest.fixture(autouse=True)
def _map_testserver_to_public(public_tenant):
    """Webhooks are posted to the apex/``testserver`` host (public schema, TD-6).
    django-tenants only routes ``testserver`` to the public schema when a Domain
    row maps it — the root ``public_tenant`` fixture creates that mapping. Without
    it the POST 404s (no tenant for the host), not a view bug."""
    return public_tenant


@pytest.fixture
def configured_a(tenant_a):
    helpers.seed_provider_configs(tenant_a)
    helpers.seed_open_invoice(tenant_a, number=ACCOUNT["order_id"], amount_uzs=AMOUNT_UZS)
    return tenant_a


@pytest.fixture
def configured_b(tenant_b):
    helpers.seed_provider_configs(tenant_b)
    # tenant_b has its OWN invoice numbering; A's INV-2026-000001 must not resolve.
    helpers.seed_open_invoice(tenant_b, number="INV-2026-000777", amount_uzs=AMOUNT_UZS)
    return tenant_b


def _post_payme(center, payload, *, wrong_auth=False):
    return helpers.public_client().post(
        helpers.webhook_url("payme", center.schema_name),
        data=payload,
        format="json",
        **bld.payme_auth_headers(wrong=wrong_auth),
    )


def _post_click(center, payload):
    return helpers.public_client().post(
        helpers.webhook_url("click", center.schema_name), data=payload, format="json"
    )


def _post_uzum(center, body, headers):
    return helpers.public_client().post(
        helpers.webhook_url("uzum", center.schema_name), data=body, format="json", **headers
    )


# --------------------------------------------------------------------------- #
# D3-F-1 — signature tampering
# --------------------------------------------------------------------------- #
def test_click_invalid_signature_rejected_minus_1_zero_rows(configured_a):
    """Click: flipped one char in sign_string -> error -1, zero Payment rows."""
    payload = bld.make_click_complete(
        merchant_trans_id=ACCOUNT["order_id"], amount=AMOUNT_UZS, tamper_sign=True
    )
    resp = _post_click(configured_a, payload)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    # Click's own error envelope: error == -1 on bad sign.
    assert body.get("error") == -1, body
    assert helpers.payment_rows(configured_a) == []


def test_payme_wrong_basic_auth_minus_32504_http200(configured_a):
    """Payme: wrong Basic auth -> -32504, HTTP 200, JSON-RPC error member."""
    payload = bld.payme_check_perform(amount_tiyin=AMOUNT_TIYIN, account=ACCOUNT)
    resp = _post_payme(configured_a, payload, wrong_auth=True)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32504
    assert "result" not in body
    assert helpers.payment_rows(configured_a) == []


def test_uzum_bad_hmac_rejected_webhookevent(configured_a):
    """Uzum: bad HMAC -> rejected; a WebhookEvent row records status=rejected."""
    body, headers = bld.make_uzum_webhook(order_id=ACCOUNT["order_id"], amount=AMOUNT_UZS, tamper_sign=True)
    resp = _post_uzum(configured_a, body, headers)
    # Uzum/Click use the standard TD-18 envelope on errors (Lane B decision).
    assert resp.status_code in (400, 401, 403), resp.content
    events = helpers.webhook_event_rows(configured_a, provider="uzum")
    assert events, "a WebhookEvent should be recorded even for a rejected webhook"
    assert any(e.status == "rejected" and e.signature_valid is False for e in events)
    assert helpers.payment_rows(configured_a) == []


def test_uzum_valid_hmac_accepted(configured_a):
    """Control: a correctly-signed Uzum webhook is accepted (signature_valid)."""
    body, headers = bld.make_uzum_webhook(order_id=ACCOUNT["order_id"], amount=AMOUNT_UZS)
    resp = _post_uzum(configured_a, body, headers)
    assert resp.status_code in (200, 201, 202), resp.content
    events = helpers.webhook_event_rows(configured_a, provider="uzum", event_id="uzum-evt-1")
    assert events
    assert events[0].signature_valid is True


# --------------------------------------------------------------------------- #
# D3-F-2 — replay protection
# --------------------------------------------------------------------------- #
def test_payme_create_transaction_replay_one_payment(configured_a):
    """Same Payme CreateTransaction id twice -> identical response, one Payment."""
    payload = bld.payme_create_transaction(
        payme_id="replay-create-1", amount_tiyin=AMOUNT_TIYIN, account=ACCOUNT
    )
    first = _post_payme(configured_a, payload).json()
    second = _post_payme(configured_a, payload).json()
    assert "result" in first
    assert "result" in second
    assert second["result"]["create_time"] == first["result"]["create_time"]
    assert second["result"]["state"] == 1
    rows = helpers.payment_rows(configured_a, provider_txn_id="replay-create-1")
    assert len(rows) == 1


def test_click_complete_replay_duplicate_single_allocation(configured_a):
    """Same Click click_trans_id complete twice -> second recorded duplicate;
    allocation runs exactly once."""
    prepare = bld.make_click_prepare(merchant_trans_id=ACCOUNT["order_id"], amount=AMOUNT_UZS)
    _post_click(configured_a, prepare)
    complete = bld.make_click_complete(
        click_trans_id=prepare["click_trans_id"],
        merchant_trans_id=ACCOUNT["order_id"],
        amount=AMOUNT_UZS,
    )
    first = _post_click(configured_a, complete)
    assert first.status_code == 200, first.content
    second = _post_click(configured_a, complete)
    assert second.status_code == 200, second.content

    # exactly one completed Payment, and exactly one allocation for it
    pays = helpers.payment_rows(configured_a, provider="click", provider_txn_id=prepare["click_trans_id"])
    assert len(pays) == 1
    allocs = helpers.allocation_rows(configured_a, payment_id=pays[0].id)
    assert len(allocs) == 1
    # the replay is recorded as a duplicate WebhookEvent
    events = helpers.webhook_event_rows(configured_a, provider="click")
    assert any(e.status == "duplicate" for e in events)


# --------------------------------------------------------------------------- #
# D3-F-3 — wrong-tenant slug
# --------------------------------------------------------------------------- #
def test_payme_valid_for_a_posted_to_b_fails_no_rows(configured_a, configured_b):
    """A signature/account valid for center A, posted to center B's slug, must
    fail against B's ProviderConfig + invoices (account error band); no rows in
    either schema."""
    payload = bld.payme_create_transaction(
        payme_id="cross-slug-1", amount_tiyin=AMOUNT_TIYIN, account=ACCOUNT
    )
    resp = _post_payme(configured_b, payload)  # A's invoice number, B's slug
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "error" in body
    code = body["error"]["code"]
    # A's INV number does not exist in B -> account error band -31050..-31099.
    assert -31099 <= code <= -31050
    assert helpers.payment_rows(configured_a) == []
    assert helpers.payment_rows(configured_b) == []


def test_nonexistent_slug_404(configured_a):
    """A webhook for an unknown center slug -> 404 envelope (TD-6)."""
    payload = bld.payme_check_perform(amount_tiyin=AMOUNT_TIYIN, account=ACCOUNT)
    resp = helpers.public_client().post(
        helpers.webhook_url("payme", "no_such_center"),
        data=payload,
        format="json",
        **bld.payme_auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_inactive_center_slug_404(configured_a):
    """An inactive center resolves to 404 (the slug lookup filters is_active)."""
    from apps.tenancy.models import Center

    Center.objects.filter(schema_name=configured_a.schema_name).update(is_active=False)
    try:
        payload = bld.payme_check_perform(amount_tiyin=AMOUNT_TIYIN, account=ACCOUNT)
        resp = _post_payme(configured_a, payload)
        assert resp.status_code == 404
    finally:
        Center.objects.filter(schema_name=configured_a.schema_name).update(is_active=True)
