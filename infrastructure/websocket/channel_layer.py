"""Helpers for sending messages into the Channels layer from sync code."""

from __future__ import annotations

from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def group_send(group: str, message: dict[str, Any]) -> None:
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(group, message)
