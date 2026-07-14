#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

DEPLOY_DIR="${STARFORGE_DEPLOY_DIR:-/root/starforge-deploy}"
BACKUP_ENV="${STARFORGE_BACKUP_ENV_FILE:-${DEPLOY_DIR}/backup.env}"
COMPOSE_ENV="${STARFORGE_COMPOSE_ENV:-${DEPLOY_DIR}/compose.env}"

[[ -r "$BACKUP_ENV" && -r "$COMPOSE_ENV" ]] || {
  echo "backup.env and compose.env are required" >&2
  exit 1
}

set -a
source "$BACKUP_ENV"
source "$COMPOSE_ENV"
set +a

: "${RESTIC_IMAGE:?RESTIC_IMAGE must be pinned}"
: "${POSTGRES_IMAGE:?POSTGRES_IMAGE must be pinned}"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/starforge-restore.XXXXXX")"
container="starforge-restore-verify-$$"
volume="starforge_restore_verify_$$"
password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  case "$tmp_dir" in
    /tmp/starforge-restore.*|"${TMPDIR:-/tmp}"/starforge-restore.*) rm -rf -- "$tmp_dir" ;;
    *) echo "Refusing to remove unexpected restore path: $tmp_dir" >&2 ;;
  esac
}
trap cleanup EXIT

echo "Restoring the latest encrypted PostgreSQL snapshot into an isolated directory..."
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$tmp_dir:/restore" "$RESTIC_IMAGE" \
  restore latest --tag postgres --target /restore

dump_path="$(find "$tmp_dir" -type f -name postgres.dump -print -quit)"
[[ -n "$dump_path" && -s "$dump_path" ]] || { echo "Restored dump is missing" >&2; exit 1; }
checksum_path="$(find "$tmp_dir" -type f -name SHA256SUMS -print -quit)"
[[ -n "$checksum_path" ]] || { echo "Restored checksum manifest is missing" >&2; exit 1; }
(cd "$(dirname "$checksum_path")" && sha256sum --check "$(basename "$checksum_path")")
docker run --rm -v "$(dirname "$dump_path"):/restore:ro" "$POSTGRES_IMAGE" \
  pg_restore --list /restore/"$(basename "$dump_path")" >/dev/null

docker volume create "$volume" >/dev/null
docker run -d --name "$container" \
  -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=restore \
  -v "$volume:/var/lib/postgresql/data" "$POSTGRES_IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres -d restore >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres -d restore >/dev/null

docker exec -i "$container" pg_restore -U postgres -d restore --exit-on-error <"$dump_path"
migration_count="$(docker exec "$container" psql -U postgres -d restore -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM django_migrations;")"
schema_count="$(docker exec "$container" psql -U postgres -d restore -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM information_schema.schemata;")"
[[ "$migration_count" =~ ^[0-9]+$ && "$migration_count" -gt 0 ]]
[[ "$schema_count" =~ ^[0-9]+$ && "$schema_count" -gt 0 ]]

echo "Restoring object and deployment snapshots for structural verification..."
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$tmp_dir:/restore" "$RESTIC_IMAGE" \
  restore latest --tag minio --target /restore/minio
test -d "$tmp_dir/minio"
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$tmp_dir:/restore" "$RESTIC_IMAGE" \
  restore latest --tag configuration --target /restore/configuration
find "$tmp_dir/configuration" -type f -name app.env -print -quit | grep -q .

docker run --rm --env-file "$BACKUP_ENV" "$RESTIC_IMAGE" check --read-data-subset=5%

echo "Restore verification completed successfully."
