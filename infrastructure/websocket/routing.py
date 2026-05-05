"""Top-level Channels URL routing.

Each app can expose its own websocket_urlpatterns; aggregate them here.
"""

from __future__ import annotations

from django.urls import path

from .consumers import PingConsumer

websocket_urlpatterns = [
    path("ws/ping/", PingConsumer.as_asgi()),
]
