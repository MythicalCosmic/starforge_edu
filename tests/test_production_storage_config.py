"""Static contracts for production object-storage topology and bootstrap."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker" / "docker-compose.production.yml").read_text(encoding="utf-8")
CADDY = (ROOT / "docker" / "Caddyfile.starforge.example").read_text(encoding="utf-8")
DEPLOY = (ROOT / "scripts" / "deploy_production.sh").read_text(encoding="utf-8")
CONFIGURE = (ROOT / "scripts" / "configure_production_storage.sh").read_text(encoding="utf-8")


def test_minio_is_reachable_only_through_caddy_s3_alias():
    assert "aliases: [starforge-minio]" in COMPOSE
    assert "reverse_proxy starforge-minio:9000" in CADDY
    assert "9001" in CADDY
    assert "must remain private" in CADDY
    assert "ports:" not in COMPOSE


def test_storage_bootstrap_keeps_media_private_and_static_read_only():
    assert '[[ "$media_bucket" != "$static_bucket" ]]' in CONFIGURE
    assert 'mc anonymous set none "source/$MEDIA_BUCKET"' in CONFIGURE
    assert 'mc anonymous set-json /config/static-policy.json "source/$STATIC_BUCKET"' in CONFIGURE
    assert '"Action": ["s3:GetObject"]' in CONFIGURE
    assert "s3:ListBucket" not in CONFIGURE
    assert "STORAGE_CORS_ALLOWED_ORIGINS" in CONFIGURE
    assert "MINIO_API_CORS_ALLOW_ORIGIN" in CONFIGURE
    assert "mc cors set" not in CONFIGURE
    assert 'or "*" in origin' in CONFIGURE


def test_storage_is_configured_and_publicly_checked_before_backup_and_migrations():
    configure = DEPLOY.index("scripts/configure_production_storage.sh")
    backup = DEPLOY.index("scripts/backup_production.sh")
    migrations = DEPLOY.index('echo "Applying public and tenant migrations..."')
    assert configure < backup < migrations
    assert 'curl -fsS --max-time 15 "${AWS_S3_PUBLIC_ENDPOINT_URL%/}/minio/health/live"' in CONFIGURE
    assert 'client.put_object(Bucket=bucket, Key=key, Body=b"ok"' in CONFIGURE
    assert "client.delete_object(Bucket=bucket, Key=key)" in CONFIGURE


def test_storage_bootstrap_cannot_replace_the_candidate_image_from_compose_env():
    assert 'candidate_image="$APP_IMAGE"' in CONFIGURE
    assert 'export APP_IMAGE="$candidate_image"' in CONFIGURE
    assert 'source "$COMPOSE_ENV"' not in CONFIGURE
