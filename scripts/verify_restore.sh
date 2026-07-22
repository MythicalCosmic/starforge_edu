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

BACKUP_MODE="${BACKUP_MODE:-offsite}"
RESTIC_HOST="${RESTIC_HOST:-starforge-production}"
restic_repository_args=()
case "$BACKUP_MODE" in
  offsite)
    ;;
  local)
    : "${LOCAL_BACKUP_ROOT:?LOCAL_BACKUP_ROOT is required for local backups}"
    [[ "$LOCAL_BACKUP_ROOT" == /* && "$LOCAL_BACKUP_ROOT" != "/" ]] || {
      echo "LOCAL_BACKUP_ROOT must be an absolute non-root path" >&2
      exit 1
    }
    local_backup_root="$(realpath -e -- "$LOCAL_BACKUP_ROOT")"
    [[ "$local_backup_root" == "${LOCAL_BACKUP_ROOT%/}" ]] || {
      echo "LOCAL_BACKUP_ROOT must not traverse symbolic links" >&2
      exit 1
    }
    [[ "$(stat -c '%u:%g:%a' "$local_backup_root")" == "0:0:700" ]] || {
      echo "LOCAL_BACKUP_ROOT must be owned by root:root with mode 0700" >&2
      exit 1
    }
    case "${RESTIC_REPOSITORY:-}" in
      /repository|/repository/*) ;;
      *)
        echo "Local RESTIC_REPOSITORY must be /repository or a child of it" >&2
        exit 1
        ;;
    esac
    restic_repository_args+=(
      --network none
      --mount "type=bind,src=${local_backup_root},dst=/repository"
    )
    ;;
  *)
    echo "BACKUP_MODE must be either local or offsite" >&2
    exit 1
    ;;
esac

restic_run() {
  docker run --rm --env-file "$BACKUP_ENV" \
    "${restic_repository_args[@]}" "$RESTIC_IMAGE" "$@"
}

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

snapshot="${STARFORGE_RESTORE_SNAPSHOT:-}"
if [[ -z "$snapshot" && -r "${DEPLOY_DIR}/last_verified_backup" ]]; then
  snapshot="$(<"${DEPLOY_DIR}/last_verified_backup")"
fi
snapshot="${snapshot:-latest}"

echo "Restoring atomic snapshot $snapshot into an isolated directory..."
docker run --rm --env-file "$BACKUP_ENV" \
  "${restic_repository_args[@]}" \
  -v "$tmp_dir:/restore" "$RESTIC_IMAGE" \
  restore "$snapshot" --host "$RESTIC_HOST" --tag starforge --target /restore

dump_path="$(find "$tmp_dir" -type f -name postgres.dump -print -quit)"
[[ -n "$dump_path" && -s "$dump_path" ]] || { echo "Restored dump is missing" >&2; exit 1; }
checksum_path="$(find "$tmp_dir" -type f -name SHA256SUMS -print -quit)"
[[ -n "$checksum_path" ]] || { echo "Restored checksum manifest is missing" >&2; exit 1; }
(cd "$(dirname "$checksum_path")" && sha256sum --check "$(basename "$checksum_path")")
docker run --rm -v "$(dirname "$dump_path"):/restore:ro" "$POSTGRES_IMAGE" \
  pg_restore --list /restore/"$(basename "$dump_path")" >/dev/null

docker volume create "$volume" >/dev/null
docker run -d --name "$container" \
  --memory=384m --cpus=0.5 --pids-limit=100 \
  -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=restore \
  -v "$volume:/var/lib/postgresql/data" "$POSTGRES_IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres -d restore >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres -d restore >/dev/null

docker exec -i "$container" pg_restore -U postgres -d restore \
  --exit-on-error --no-owner --no-acl <"$dump_path"
migration_count="$(docker exec "$container" psql -U postgres -d restore -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM django_migrations;")"
schema_count="$(docker exec "$container" psql -U postgres -d restore -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM information_schema.schemata;")"
[[ "$migration_count" =~ ^[0-9]+$ && "$migration_count" -gt 0 ]]
[[ "$schema_count" =~ ^[0-9]+$ && "$schema_count" -gt 0 ]]

echo "Checking restored object and deployment snapshots..."
find "$tmp_dir" -type d -name minio -print -quit | grep -q .
find "$tmp_dir" -type f -path '*/deployment/app.env' -print -quit | grep -q .

if [[ "$BACKUP_MODE" == "local" ]]; then
  restic_run check --read-data
else
  restic_run check --read-data-subset=5%
fi

echo "Restore verification completed successfully."
