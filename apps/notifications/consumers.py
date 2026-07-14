"""Notification WebSocket consumer (D4-LC-3).

``ws/notifications/`` — any authenticated user. On connect the socket joins:

  - ``f"{schema}.user.{user_id}"`` — the per-user fan-out group that
    ``apps.notifications.services.push_in_app`` (the in-app channel of
    ``dispatch()``) writes to. The schema prefix is mandatory: user ids are
    per-tenant autoincrements, so an unscoped ``user.5`` collides across tenants
    on the shared Redis channel layer. This MATCHES the producer scheme in
    ``celery_tasks/notification_tasks._deliver_in_app`` (the code is the source
    of truth — DAY-4.md's "user.{id}" predates the Day-3 schema-prefix fix).
Handler ``notification_message`` relays the producer payload to the socket as
``{"type": "notification", "payload": {...}}``. The relayed envelope strips the
channel-layer ``"type"`` routing key and forwards the remaining fields.

Anonymous / cross-tenant / stale-tv connections never reach here as a real user
(the middleware yields AnonymousUser); the consumer closes 4401.
"""

from __future__ import annotations

from infrastructure.websocket.consumers import (
    CLOSE_UNAUTHORIZED,
    HeartbeatConsumerMixin,
    accepted_subprotocol,
)


class NotificationConsumer(HeartbeatConsumerMixin):
    async def connect(self):
        user = self._authed_user()
        schema = self._schema()
        if user is None or schema is None:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        await self.accept(subprotocol=accepted_subprotocol(self.scope))
        await self.join_group(f"{schema}.user.{user.pk}")
        await self.start_heartbeat()

    async def notification_message(self, event: dict) -> None:
        """Relay a producer payload (group_send type ``notification.message``)."""
        payload = {k: v for k, v in event.items() if k != "type"}
        await self.send_json({"type": "notification", "payload": payload})
