"""S3-compatible client.

Django uses django-storages (configured in settings.STORAGES) for
default file fields. This module exposes a thin boto3 client for
direct operations: presigned URLs, multipart uploads, bucket admin.
"""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import Config
from django.conf import settings


@lru_cache(maxsize=1)
def get_s3_client():
    opts = settings.STORAGES["default"]["OPTIONS"]
    return boto3.client(
        "s3",
        endpoint_url=opts.get("endpoint_url") or None,
        aws_access_key_id=opts["access_key"],
        aws_secret_access_key=opts["secret_key"],
        region_name=opts["region_name"],
        config=Config(
            signature_version=opts["signature_version"],
            s3={"addressing_style": opts["addressing_style"]},
        ),
    )


def presign_upload(key: str, *, expires_in: int = 600, content_type: str = "application/octet-stream") -> str:
    return get_s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.STORAGES["default"]["OPTIONS"]["bucket_name"],
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def presign_download(key: str, *, expires_in: int = 600) -> str:
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.STORAGES["default"]["OPTIONS"]["bucket_name"],
            "Key": key,
        },
        ExpiresIn=expires_in,
    )
