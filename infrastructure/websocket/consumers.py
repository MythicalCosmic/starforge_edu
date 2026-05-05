"""Demo Channels consumer used by the v1 smoke test."""

from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser


class PingConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if isinstance(user, AnonymousUser):
            await self.close(code=4401)
            return
        await self.accept(subprotocol="bearer")
        await self.send_json({"type": "hello", "user_id": user.pk})

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})
