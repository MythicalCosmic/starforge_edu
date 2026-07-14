"""Django storage backends for split internal and browser-facing S3 endpoints."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from storages.backends.s3 import S3Storage


class DualEndpointS3Storage(S3Storage):
    """Use the private endpoint for I/O and the public endpoint for URLs.

    MinIO is reached over the private Docker network for uploads, downloads, and
    ``collectstatic``.  URL generation is local SigV4 work, so a second storage
    instance can safely sign the browser-reachable endpoint without making a
    network request through the public reverse proxy.
    """

    def __init__(self, **options: Any) -> None:
        self._public_storage_options = options.copy()
        super().__init__(**options)

    @cached_property
    def _public_url_storage(self) -> S3Storage:
        public_endpoint = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", "").strip()
        if not public_endpoint:
            raise ImproperlyConfigured(
                "AWS_S3_PUBLIC_ENDPOINT_URL is required to generate browser-facing storage URLs."
            )
        options = self._public_storage_options.copy()
        options["endpoint_url"] = public_endpoint
        return S3Storage(**options)

    def url(
        self,
        name: str,
        parameters: dict[str, Any] | None = None,
        expire: int | None = None,
        http_method: str | None = None,
    ) -> str:
        return self._public_url_storage.url(
            name,
            parameters=parameters,
            expire=expire,
            http_method=http_method,
        )
