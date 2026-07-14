#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

DEPLOY_DIR="${STARFORGE_DEPLOY_DIR:-/root/starforge-deploy}"
REPO_DIR="${STARFORGE_REPO_DIR:-/root/starforge_edu}"
COMPOSE_FILE="${STARFORGE_COMPOSE_FILE:-${REPO_DIR}/docker/docker-compose.production.yml}"
COMPOSE_ENV="${STARFORGE_COMPOSE_ENV:-${DEPLOY_DIR}/compose.env}"
DB_ENV="${STARFORGE_DB_ENV_FILE:-${DEPLOY_DIR}/postgres.env}"
MINIO_ENV="${STARFORGE_MINIO_ENV_FILE:-${DEPLOY_DIR}/minio.env}"
BACKUP_ENV="${STARFORGE_BACKUP_ENV_FILE:-${DEPLOY_DIR}/backup.env}"

for required in "$COMPOSE_FILE" "$COMPOSE_ENV" "$DB_ENV" "$MINIO_ENV" "$BACKUP_ENV"; do
  [[ -r "$required" ]] || { echo "Required backup input is unreadable: $required" >&2; exit 1; }
done

set -a
# Trusted root-owned deployment files. Values must use shell-compatible KEY=VALUE syntax.
source "$COMPOSE_ENV"
source "$DB_ENV"
source "$MINIO_ENV"
source "$BACKUP_ENV"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${RESTIC_IMAGE:?RESTIC_IMAGE must be pinned}"
: "${MINIO_MC_IMAGE:?MINIO_MC_IMAGE must be pinned}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/starforge-backup.XXXXXX")"
cleanup() {
  case "$tmp_dir" in
    /tmp/starforge-backup.*|"${TMPDIR:-/tmp}"/starforge-backup.*) rm -rf -- "$tmp_dir" ;;
    *) echo "Refusing to remove unexpected backup path: $tmp_dir" >&2 ;;
  esac
}
trap cleanup EXIT

compose=(docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE")

echo "Creating consistent PostgreSQL logical dump..."
"${compose[@]}" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 \
  >"$tmp_dir/postgres.dump"
test -s "$tmp_dir/postgres.dump"
sha256sum "$tmp_dir/postgres.dump" >"$tmp_dir/SHA256SUMS"

echo "Creating an object-level MinIO mirror..."
mkdir -p "$tmp_dir/minio"
docker run --rm --network "${COMPOSE_PROJECT_NAME:-starforge}_internal" \
  --env-file "$MINIO_ENV" \
  -v "$tmp_dir/minio:/backup" \
  --entrypoint /bin/sh "$MINIO_MC_IMAGE" -ceu \
  'mc alias set source http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc mirror --overwrite --remove source/ /backup/'

restic_run() {
  docker run --rm --env-file "$BACKUP_ENV" "$RESTIC_IMAGE" "$@"
}

if ! restic_run snapshots >/dev/null 2>&1; then
  echo "Initializing encrypted off-host Restic repository..."
  restic_run init
fi

echo "Uploading encrypted PostgreSQL backup..."
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$tmp_dir:/backup:ro" "$RESTIC_IMAGE" \
  backup /backup --tag postgres --tag starforge

echo "Uploading encrypted MinIO object snapshot..."
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$tmp_dir/minio:/objects:ro" "$RESTIC_IMAGE" \
  backup /objects --tag minio --tag starforge

echo "Uploading encrypted deployment configuration..."
docker run --rm --env-file "$BACKUP_ENV" \
  -v "$DEPLOY_DIR:/deployment:ro" "$RESTIC_IMAGE" \
  backup /deployment --tag configuration --tag starforge \
  --exclude='*.log' --exclude='.autodeploy.lock'

restic_run forget --prune --keep-daily 14 --keep-weekly 8 --keep-monthly 12
restic_run check --read-data-subset=5%
echo "Starforge backup and integrity check completed."
