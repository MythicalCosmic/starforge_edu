#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

DEPLOY_DIR="${STARFORGE_DEPLOY_DIR:-/root/starforge-deploy}"
REPO_DIR="${STARFORGE_REPO_DIR:-/root/starforge_edu}"
COMPOSE_FILE="${STARFORGE_COMPOSE_FILE:-${REPO_DIR}/docker/docker-compose.production.yml}"
COMPOSE_ENV="${STARFORGE_COMPOSE_ENV:-${DEPLOY_DIR}/compose.env}"
APP_ENV="${STARFORGE_APP_ENV_FILE:-${DEPLOY_DIR}/app.env}"
MINIO_ENV="${STARFORGE_MINIO_ENV_FILE:-${DEPLOY_DIR}/minio.env}"
BACKUP_ENV="${STARFORGE_BACKUP_ENV_FILE:-${DEPLOY_DIR}/backup.env}"

[[ "$EUID" -eq 0 ]] || { echo "Production storage configuration must run as root" >&2; exit 1; }
for required in "$COMPOSE_FILE" "$COMPOSE_ENV" "$APP_ENV" "$MINIO_ENV" "$BACKUP_ENV"; do
  [[ -r "$required" ]] || { echo "Required storage input is unreadable: $required" >&2; exit 1; }
done

set -a
# Trusted root-owned deployment files. Values must use shell-compatible KEY=VALUE syntax.
source "$COMPOSE_ENV"
source "$MINIO_ENV"
source "$BACKUP_ENV"
set +a

app_env_value() {
  local key="$1" line
  line="$(grep -m 1 "^${key}=" "$APP_ENV" || true)"
  printf '%s' "${line#*=}"
}

AWS_STORAGE_BUCKET_NAME="$(app_env_value AWS_STORAGE_BUCKET_NAME)"
AWS_STATIC_BUCKET_NAME="$(app_env_value AWS_STATIC_BUCKET_NAME)"
AWS_S3_PUBLIC_ENDPOINT_URL="$(app_env_value AWS_S3_PUBLIC_ENDPOINT_URL)"
STORAGE_CORS_ALLOWED_ORIGINS="$(app_env_value STORAGE_CORS_ALLOWED_ORIGINS)"

: "${MINIO_MC_IMAGE:?MINIO_MC_IMAGE must be pinned}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${AWS_STORAGE_BUCKET_NAME:?AWS_STORAGE_BUCKET_NAME is required}"
: "${AWS_STATIC_BUCKET_NAME:?AWS_STATIC_BUCKET_NAME is required}"
: "${AWS_S3_PUBLIC_ENDPOINT_URL:?AWS_S3_PUBLIC_ENDPOINT_URL is required}"
: "${STORAGE_CORS_ALLOWED_ORIGINS:?STORAGE_CORS_ALLOWED_ORIGINS is required}"

media_bucket="$AWS_STORAGE_BUCKET_NAME"
static_bucket="$AWS_STATIC_BUCKET_NAME"
[[ "$media_bucket" != "$static_bucket" ]] || {
  echo "Media and static buckets must be different; static is intentionally public-read" >&2
  exit 1
}
bucket_pattern='^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'
[[ "$media_bucket" =~ $bucket_pattern && "$static_bucket" =~ $bucket_pattern ]] || {
  echo "Storage bucket names are invalid" >&2
  exit 1
}

tmp_dir="$(mktemp -d /tmp/starforge-storage.XXXXXX)"
cleanup() {
  if [[ -n "${tmp_dir:-}" && "$tmp_dir" == /tmp/starforge-storage.* ]]; then
    rm -rf -- "$tmp_dir"
  else
    echo "Refusing to remove unexpected storage path: ${tmp_dir:-<unset>}" >&2
  fi
}
trap cleanup EXIT

STORAGE_CORS_ALLOWED_ORIGINS="$STORAGE_CORS_ALLOWED_ORIGINS" STATIC_BUCKET="$static_bucket" \
  python3 - "$tmp_dir/media-cors.xml" "$tmp_dir/static-cors.xml" \
    "$tmp_dir/static-policy.json" <<'PY'
import json
import os
import sys
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

origins = [value.strip() for value in os.environ["STORAGE_CORS_ALLOWED_ORIGINS"].split(",") if value.strip()]
if not origins:
    raise SystemExit("At least one storage CORS origin is required")
for origin in origins:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "*" in origin
    ):
        raise SystemExit(f"Invalid storage CORS origin: {origin}")

allowed_origins = "\n".join(f"    <AllowedOrigin>{escape(origin)}</AllowedOrigin>" for origin in origins)


def cors_xml(methods: tuple[str, ...]) -> str:
    allowed_methods = "\n".join(f"    <AllowedMethod>{method}</AllowedMethod>" for method in methods)
    return f"""<CORSConfiguration>
  <CORSRule>
{allowed_origins}
{allowed_methods}
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
    <MaxAgeSeconds>3600</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>
"""


with open(sys.argv[1], "w", encoding="utf-8") as media:
    media.write(cors_xml(("GET", "PUT", "POST", "HEAD")))
with open(sys.argv[2], "w", encoding="utf-8") as static:
    static.write(cors_xml(("GET", "HEAD")))
with open(sys.argv[3], "w", encoding="utf-8") as policy:
    json.dump(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{os.environ['STATIC_BUCKET']}/*"],
                }
            ],
        },
        policy,
    )
PY

compose=(docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE")
minio_container="$("${compose[@]}" ps -q minio)"
[[ -n "$minio_container" ]] || { echo "MinIO container is unavailable" >&2; exit 1; }

docker run --rm --network "container:${minio_container}" \
  --env-file "$MINIO_ENV" \
  -e "MEDIA_BUCKET=$media_bucket" \
  -e "STATIC_BUCKET=$static_bucket" \
  -v "$tmp_dir:/config:ro" \
  --entrypoint /bin/sh "$MINIO_MC_IMAGE" -ceu '
    mc alias set source http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc mb --ignore-existing "source/$MEDIA_BUCKET" "source/$STATIC_BUCKET" >/dev/null
    mc anonymous set none "source/$MEDIA_BUCKET" >/dev/null
    mc anonymous set-json /config/static-policy.json "source/$STATIC_BUCKET" >/dev/null
    mc cors set "source/$MEDIA_BUCKET" /config/media-cors.xml >/dev/null
    mc cors set "source/$STATIC_BUCKET" /config/static-cors.xml >/dev/null
  '

curl -fsS --max-time 15 "${AWS_S3_PUBLIC_ENDPOINT_URL%/}/minio/health/live" >/dev/null
"${compose[@]}" run --rm --no-deps -T web python - <<'PY'
from urllib.request import urlopen

from django.conf import settings

from infrastructure.storage.s3_client import get_s3_client

bucket = settings.STORAGES["staticfiles"]["OPTIONS"]["bucket_name"]
endpoint = settings.AWS_S3_PUBLIC_ENDPOINT_URL.rstrip("/")
key = ".starforge-storage-write-check"
client = get_s3_client()
try:
    client.put_object(Bucket=bucket, Key=key, Body=b"ok", ContentType="text/plain")
    with urlopen(f"{endpoint}/{bucket}/{key}", timeout=15) as response:  # noqa: S310
        if response.status != 200 or response.read() != b"ok":
            raise SystemExit("Public static storage verification returned unexpected content")
finally:
    client.delete_object(Bucket=bucket, Key=key)
PY
echo "Production storage buckets, policies, CORS, and public endpoint are ready."
