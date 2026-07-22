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
LOCK_FILE="${DEPLOY_DIR}/backup.lock"

for required in "$COMPOSE_FILE" "$COMPOSE_ENV" "$DB_ENV" "$MINIO_ENV" "$BACKUP_ENV"; do
  [[ -r "$required" ]] || { echo "Required backup input is unreadable: $required" >&2; exit 1; }
done

exec 8>"$LOCK_FILE"
flock -n 8 || { echo "Another backup is already running" >&2; exit 1; }

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

BACKUP_MODE="${BACKUP_MODE:-offsite}"
RESTIC_HOST="${RESTIC_HOST:-starforge-production}"
LOCAL_BACKUP_MIN_FREE_BYTES="${LOCAL_BACKUP_MIN_FREE_BYTES:-5368709120}"
restic_repository_args=()
tmp_parent="${TMPDIR:-/tmp}"
local_backup_root=""

path_contains() {
  local parent="${1%/}"
  local child="${2%/}"
  [[ "$child" == "$parent" || "$child" == "$parent/"* ]]
}

case "$BACKUP_MODE" in
  offsite)
    ;;
  local)
    [[ "$EUID" -eq 0 ]] || { echo "Local backups must run as root" >&2; exit 1; }
    : "${LOCAL_BACKUP_ROOT:?LOCAL_BACKUP_ROOT is required for local backups}"
    [[ "$LOCAL_BACKUP_ROOT" == /* && "$LOCAL_BACKUP_ROOT" != "/" ]] || {
      echo "LOCAL_BACKUP_ROOT must be an absolute non-root path" >&2
      exit 1
    }
    [[ ! -L "$LOCAL_BACKUP_ROOT" ]] || {
      echo "LOCAL_BACKUP_ROOT must not be a symbolic link" >&2
      exit 1
    }
    if [[ ! -e "$LOCAL_BACKUP_ROOT" ]]; then
      install -d -o root -g root -m 0700 -- "$LOCAL_BACKUP_ROOT"
    fi
    [[ -d "$LOCAL_BACKUP_ROOT" && ! -L "$LOCAL_BACKUP_ROOT" ]] || {
      echo "LOCAL_BACKUP_ROOT must be a directory" >&2
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

    canonical_deploy="$(realpath -e -- "$DEPLOY_DIR")"
    canonical_repo="$(realpath -e -- "$REPO_DIR")"
    if path_contains "$canonical_deploy" "$local_backup_root" || \
       path_contains "$local_backup_root" "$canonical_deploy" || \
       path_contains "$canonical_repo" "$local_backup_root" || \
       path_contains "$local_backup_root" "$canonical_repo"; then
      echo "LOCAL_BACKUP_ROOT must be separate from deploy and repository paths" >&2
      exit 1
    fi
    case "$RESTIC_REPOSITORY" in
      /repository|/repository/*) ;;
      *)
        echo "Local RESTIC_REPOSITORY must be /repository or a child of it" >&2
        exit 1
        ;;
    esac
    [[ "$LOCAL_BACKUP_MIN_FREE_BYTES" =~ ^[0-9]+$ ]] || {
      echo "LOCAL_BACKUP_MIN_FREE_BYTES must be a non-negative integer" >&2
      exit 1
    }
    restic_repository_args+=(
      --network none
      --mount "type=bind,src=${local_backup_root},dst=/repository"
    )
    tmp_parent="$local_backup_root"
    ;;
  *)
    echo "BACKUP_MODE must be either local or offsite" >&2
    exit 1
    ;;
esac

compose=(docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE")

available_bytes() {
  df -PB1 "$1" | awk 'NR == 2 { print $4 }'
}

local_source_bytes() {
  local project_name="${COMPOSE_PROJECT_NAME:-starforge}"
  local postgres_mount minio_mount postgres_bytes minio_bytes deployment_bytes
  postgres_mount="$(docker volume inspect "${project_name}_sf_pg" --format '{{.Mountpoint}}')"
  minio_mount="$(docker volume inspect "${project_name}_sf_minio" --format '{{.Mountpoint}}')"
  postgres_bytes="$(du -sb "$postgres_mount" | awk '{ print $1 }')"
  minio_bytes="$(du -sb "$minio_mount" | awk '{ print $1 }')"
  deployment_bytes="$(du -sb "$DEPLOY_DIR" | awk '{ print $1 }')"
  printf '%s\n' "$((postgres_bytes + minio_bytes + deployment_bytes))"
}

require_local_capacity() {
  local phase="$1"
  [[ "$BACKUP_MODE" == "local" ]] || return 0
  local free required
  free="$(available_bytes "$local_backup_root")"
  required="$LOCAL_BACKUP_MIN_FREE_BYTES"
  if [[ "$phase" == "preflight" ]]; then
    # Staging plus a pessimistic first Restic write can consume roughly twice
    # the live database/object/configuration footprint.
    required="$((required + (2 * $(local_source_bytes))))"
  fi
  if (( free < required )); then
    echo "Insufficient local backup capacity during $phase: free=$free required=$required" >&2
    exit 1
  fi
}

require_local_capacity preflight

tmp_dir="$(mktemp -d "${tmp_parent%/}/starforge-backup.XXXXXX")"
cleanup() {
  if [[ -n "${tmp_dir:-}" && "$tmp_dir" == "${tmp_parent%/}"/starforge-backup.* ]]; then
    rm -rf -- "$tmp_dir"
  else
    echo "Refusing to remove unexpected backup path: ${tmp_dir:-<unset>}" >&2
  fi
}
trap cleanup EXIT

echo "Creating consistent PostgreSQL logical dump..."
"${compose[@]}" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 \
  >"$tmp_dir/postgres.dump"
test -s "$tmp_dir/postgres.dump"
"${compose[@]}" exec -T postgres pg_restore --list \
  <"$tmp_dir/postgres.dump" >/dev/null

echo "Creating an object-level MinIO mirror..."
mkdir -p "$tmp_dir/minio"
minio_container="$("${compose[@]}" ps -q minio)"
[[ -n "$minio_container" ]] || { echo "MinIO container is unavailable" >&2; exit 1; }
docker run --rm --network "container:${minio_container}" \
  --env-file "$MINIO_ENV" \
  -v "$tmp_dir/minio:/backup" \
  --entrypoint /bin/sh "$MINIO_MC_IMAGE" -ceu \
  'mc alias set source http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc mirror --overwrite --remove source/ /backup/'

echo "Staging root-only deployment configuration..."
mkdir -p "$tmp_dir/deployment"
tar -C "$DEPLOY_DIR" --exclude='*.log' --exclude='*.lock' -cf - . \
  | tar -C "$tmp_dir/deployment" -xf -

(
  cd "$tmp_dir"
  find postgres.dump minio deployment -type f -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 -r sha256sum
) >"$tmp_dir/SHA256SUMS"

require_local_capacity staged

restic_run() {
  docker run --rm --env-file "$BACKUP_ENV" \
    "${restic_repository_args[@]}" "$RESTIC_IMAGE" "$@"
}

if ! restic_run snapshots >/dev/null 2>&1; then
  echo "Initializing encrypted $BACKUP_MODE Restic repository..."
  restic_run init
fi

echo "Creating one atomic PostgreSQL, MinIO, and configuration snapshot..."
backup_output="$(docker run --rm --env-file "$BACKUP_ENV" \
  "${restic_repository_args[@]}" \
  -v "$tmp_dir:/backup:ro" "$RESTIC_IMAGE" \
  backup /backup --host "$RESTIC_HOST" --tag starforge --tag production --json)"
snapshot_id="$(BACKUP_OUTPUT="$backup_output" python3 - <<'PY'
import json
import os

snapshot_id = ""
for line in os.environ["BACKUP_OUTPUT"].splitlines():
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        continue
    if payload.get("message_type") == "summary":
        snapshot_id = payload.get("snapshot_id", "")
if not snapshot_id:
    raise SystemExit("Restic did not report a snapshot ID")
print(snapshot_id)
PY
)"
[[ "$snapshot_id" =~ ^[0-9a-f]+$ ]] || {
  echo "Restic returned an invalid snapshot ID" >&2
  exit 1
}

restic_run forget --prune --host "$RESTIC_HOST" --tag starforge \
  --group-by host,paths \
  --keep-last 5 --keep-daily 14 --keep-weekly 8 --keep-monthly 12
if [[ "$BACKUP_MODE" == "local" ]]; then
  restic_run check --read-data
else
  restic_run check --read-data-subset=5%
fi

require_local_capacity verified
marker_tmp="$(mktemp "${DEPLOY_DIR}/.last_verified_backup.XXXXXX")"
printf '%s\n' "$snapshot_id" >"$marker_tmp"
chmod 0600 "$marker_tmp"
mv -f -- "$marker_tmp" "${DEPLOY_DIR}/last_verified_backup"
echo "Starforge snapshot $snapshot_id and integrity check completed."
