#!/usr/bin/env bash
set -Eeuo pipefail

revision="${1:-}"
[[ -n "$revision" ]] || { echo "usage: $0 <commit-or-ref>" >&2; exit 2; }

REPO_DIR="${STARFORGE_REPO_DIR:-/root/starforge_edu}"
DEPLOY_DIR="${STARFORGE_DEPLOY_DIR:-/root/starforge-deploy}"
RELEASE_ROOT="${STARFORGE_RELEASE_ROOT:-/root/starforge-releases}"
COMPOSE_ENV="${STARFORGE_COMPOSE_ENV:-${DEPLOY_DIR}/compose.env}"
LOCK_FILE="${DEPLOY_DIR}/deploy.lock"
HEALTH_URL="${STARFORGE_HEALTH_URL:-https://starforge.78.111.91.113.nip.io/healthz/ready}"

[[ -d "$REPO_DIR/.git" && -r "$COMPOSE_ENV" ]] || {
  echo "Repository or compose environment is unavailable" >&2
  exit 1
}

exec 9>"$LOCK_FILE"
flock -n 9 || { echo "Another deployment is already running" >&2; exit 1; }

git -C "$REPO_DIR" fetch --prune origin
sha="$(git -C "$REPO_DIR" rev-parse --verify "${revision}^{commit}")"
short_sha="${sha:0:12}"
release_dir="${RELEASE_ROOT}/${sha}"
image="starforge:${sha}"

check_ci() {
  if [[ "${ALLOW_UNVERIFIED_CI:-0}" == "1" ]]; then
    echo "WARNING: CI verification was explicitly overridden for $sha" >&2
    return
  fi
  : "${GITHUB_TOKEN:?GITHUB_TOKEN is required to verify CI}"
  response="$(curl -fsS \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/MythicalCosmic/starforge_edu/commits/${sha}/check-runs")"
  CI_RESPONSE="$response" python3 - <<'PY'
import json
import os
import sys

runs = json.loads(os.environ["CI_RESPONSE"]).get("check_runs", [])
required = {"lint", "typecheck", "test", "schema", "dependency-audit", "container-smoke"}
latest = {}
for run in runs:
    latest.setdefault(run.get("name"), run)
missing = required - latest.keys()
failed = {
    name: (latest[name].get("status"), latest[name].get("conclusion"))
    for name in required & latest.keys()
    if latest[name].get("status") != "completed" or latest[name].get("conclusion") != "success"
}
if missing or failed:
    print(f"CI gate failed; missing={sorted(missing)} failed={failed}", file=sys.stderr)
    raise SystemExit(1)
PY
}

cleanup_worktree() {
  if [[ -d "$release_dir" ]]; then
    git -C "$REPO_DIR" worktree remove --force "$release_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup_worktree EXIT

check_ci
mkdir -p "$RELEASE_ROOT"
git -C "$REPO_DIR" worktree add --detach "$release_dir" "$sha"

echo "Building immutable application image $image..."
docker build --pull -f "$release_dir/docker/Dockerfile" -t "$image" "$release_dir"

export APP_IMAGE="$image"
compose=(docker compose --env-file "$COMPOSE_ENV" -f "$release_dir/docker/docker-compose.production.yml")

echo "Running production configuration checks..."
"${compose[@]}" run --rm --no-deps web python manage.py check --deploy --fail-level WARNING

if [[ "${SKIP_BACKUP:-0}" != "1" ]]; then
  STARFORGE_REPO_DIR="$release_dir" "$release_dir/scripts/backup_production.sh"
else
  echo "WARNING: pre-deploy backup was explicitly skipped" >&2
fi

previous_image="$(docker inspect starforge-web-1 --format '{{.Config.Image}}' 2>/dev/null || true)"

echo "Applying public and tenant migrations..."
"${compose[@]}" --profile tools run --rm migrate
"${compose[@]}" --profile tools run --rm collectstatic

echo "Starting release $short_sha..."
"${compose[@]}" up -d --remove-orphans postgres redis minio web daphne worker-critical worker-default beat

healthy=0
for _ in $(seq 1 36); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    healthy=1
    break
  fi
  sleep 5
done

if [[ "$healthy" != "1" ]]; then
  echo "Release failed readiness checks" >&2
  "${compose[@]}" ps >&2 || true
  if [[ -n "$previous_image" ]]; then
    echo "Rolling application containers back to $previous_image" >&2
    export APP_IMAGE="$previous_image"
    "${compose[@]}" up -d web daphne worker-critical worker-default beat || true
  fi
  exit 1
fi

# This irreversible credential-storage cutover must happen only after readiness:
# migrations run while old containers are still serving and therefore leave legacy
# keys untouched. The command is batched/idempotent, so rerunning a partially failed
# deploy is safe. From this point, any manual rollback must use a hash-aware release.
echo "Hashing legacy session credentials after release readiness..."
"${compose[@]}" run --rm --no-deps web python manage.py hash_session_keys

printf '%s\n' "$sha" >"${DEPLOY_DIR}/current_release"
docker image prune -f --filter "until=168h" >/dev/null
echo "Deployment $short_sha is healthy."
