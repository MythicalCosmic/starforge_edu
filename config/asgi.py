"""ASGI entrypoint with Channels routing.

In dev: `daphne config.asgi:application` (or via docker compose).
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Initialize Django ASGI app first, then import everything else (the imports
# below depend on apps being loaded).
django_asgi_app = get_asgi_application()

from infrastructure.websocket.middleware import TenantAwareJWTAuthMiddleware  # noqa: E402
from infrastructure.websocket.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": TenantAwareJWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
