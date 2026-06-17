"""Shared Channels consumer building blocks (D4-LC-2).

``HeartbeatConsumerMixin`` gives every real consumer a server-driven liveness
check: the server sends ``{"type":"ping"}`` every ``HEARTBEAT_INTERVAL`` seconds
and the client must answer ``{"type":"pong"}``. After ``HEARTBEAT_MAX_MISSED``
unanswered pings the socket is closed 4408 (a dead/half-open connection that the
TCP keepalive would otherwise hold open for minutes, leaking a worker slot and a
Redis group membership).

``PingConsumer`` is the unchanged v1 smoke consumer (``/ws/ping/``).

Group cleanup contract: subclasses register every group they join in
``self._groups`` (via ``join_group``); ``disconnect`` cancels the heartbeat task
AND ``group_discard``-s every joined group, so a dropped socket never leaves a
stale membership on the shared channel layer.
"""

from __future__ import annotations

import asyncio

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

# Server ping cadence and tolerance. Class attributes so tests can patch the
# interval down (a 30s real interval would make the heartbeat tests glacial).
HEARTBEAT_INTERVAL = 30  # seconds between server pings
HEARTBEAT_MAX_MISSED = 2  # consecutive unanswered pings before close 4408

# Close codes (also documented in agents/API-CONTRACT.md "Realtime").
CLOSE_UNAUTHORIZED = 4401  # anonymous / cross-tenant / stale tv
CLOSE_FORBIDDEN = 4403  # authenticated but not permitted (branch scope)
CLOSE_HEARTBEAT = 4408  # heartbeat timeout (missed pongs)


def accepted_subprotocol(scope) -> str | None:
    """The subprotocol to echo in the handshake (D4-LC fix).

    RFC 6455 §4.2.2: the server's selected subprotocol MUST be one of the values
    the client offered. Browsers authenticate by offering a SINGLE value
    ``bearer.<token>`` (see middleware ``_extract_token``), so echoing a bare
    ``"bearer"`` — which the client never offered — makes the browser handshake
    fail. Echo back the exact offered ``bearer.*`` value instead. Clients that
    authenticate via the ``?token=`` query string offer no subprotocol → return
    None (accept without one)."""
    for offered in scope.get("subprotocols", []) or []:
        if offered == "bearer" or offered.startswith("bearer."):
            return offered
    return None


class HeartbeatConsumerMixin(AsyncJsonWebsocketConsumer):
    """Adds a server heartbeat + tracked group membership to a JSON consumer.

    Subclasses MUST call ``await self.start_heartbeat()`` after ``accept()`` and
    join groups via ``await self.join_group(name)``. ``receive_json`` here only
    consumes the client ``pong``; subclasses overriding it should ``super()``
    or handle ``{"type":"pong"}`` themselves.
    """

    HEARTBEAT_INTERVAL = HEARTBEAT_INTERVAL
    HEARTBEAT_MAX_MISSED = HEARTBEAT_MAX_MISSED

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._groups: set[str] = set()
        self._heartbeat_task: asyncio.Task | None = None
        self._missed_pings = 0

    # -- group tracking ---------------------------------------------------
    async def join_group(self, group: str) -> None:
        """Add this channel to ``group`` and remember it for cleanup."""
        await self.channel_layer.group_add(group, self.channel_name)
        self._groups.add(group)

    # -- heartbeat --------------------------------------------------------
    async def start_heartbeat(self) -> None:
        self._missed_pings = 0
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                # The ping we are about to send counts against the budget until a
                # pong clears it. Two pings sent with no intervening pong = close.
                self._missed_pings += 1
                if self._missed_pings > self.HEARTBEAT_MAX_MISSED:
                    # Server-initiated close does NOT trigger websocket_disconnect,
                    # so discard groups here to avoid a membership leak on 4408.
                    await self._discard_groups()
                    await self.close(code=CLOSE_HEARTBEAT)
                    return
                await self.send_json({"type": "ping"})
        except asyncio.CancelledError:  # pragma: no cover - normal on disconnect
            raise

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "pong":
            self._missed_pings = 0
            return
        # Subclasses may override to handle other inbound messages; default ignore.

    # -- teardown ---------------------------------------------------------
    async def _discard_groups(self) -> None:
        for group in list(self._groups):
            await self.channel_layer.group_discard(group, self.channel_name)
        self._groups.clear()

    async def disconnect(self, code):
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        await self._discard_groups()

    # -- helpers ----------------------------------------------------------
    def _authed_user(self):
        """Return the authenticated user or None (AnonymousUser -> None)."""
        user = self.scope.get("user")
        if user is None or isinstance(user, AnonymousUser):
            return None
        return user

    def _schema(self) -> str | None:
        tenant = self.scope.get("tenant")
        return tenant.schema_name if tenant is not None else None


class PingConsumer(AsyncJsonWebsocketConsumer):
    """Unchanged v1 smoke consumer used by the plumbing test (``/ws/ping/``)."""

    async def connect(self):
        user = self.scope.get("user")
        if isinstance(user, AnonymousUser):
            await self.close(code=4401)
            return
        await self.accept(subprotocol=accepted_subprotocol(self.scope))
        await self.send_json({"type": "hello", "user_id": user.pk})

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})
