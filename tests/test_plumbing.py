"""Channels + Celery plumbing (D1-LE-6). Documents the pattern for D4-C."""

from datetime import timedelta

import pytest
from channels.testing import WebsocketCommunicator
from django.utils import timezone
from django_tenants.utils import schema_context

from config.asgi import application

HOST_HEADERS = [(b"host", b"a.localhost")]


@pytest.mark.channels
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_ws_anonymous_rejected(tenant_a):
    comm = WebsocketCommunicator(application, "/ws/ping/", headers=HOST_HEADERS)
    connected, close_code = await comm.connect()
    assert not connected
    assert close_code == 4401  # PingConsumer rejects anonymous


@pytest.mark.django_db
def test_celery_eager_purges_expired_otp(tenant_a):
    from apps.users.models import OTP
    from celery_tasks.cleanup_tasks import purge_expired_otps

    with schema_context(tenant_a.schema_name):
        OTP.objects.create(
            identifier="+998900000999",
            channel=OTP.CHANNEL_SMS,
            code_hash="x",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        purge_expired_otps()  # runs synchronously under CELERY_TASK_ALWAYS_EAGER
        assert OTP.objects.filter(expires_at__lt=timezone.now()).count() == 0
