#!/usr/bin/env bash
set -euo pipefail

case "${1:-web}" in
  web)
    # iCal feeds carry a signed credential in the URL path. Keep useful request
    # telemetry without logging request targets/query strings or bearer material.
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${WEB_CONCURRENCY:-2}" --timeout "${GUNICORN_TIMEOUT_SECONDS:-60}" \
      --no-control-socket \
      --access-logfile - --access-logformat '%(h)s %(m)s %(s)s %(L)s'
    ;;
  daphne)
    exec daphne -b 0.0.0.0 -p 8001 config.asgi:application
    ;;
  worker)
    worker_args=(
      celery -A config worker
      --loglevel="${CELERY_LOG_LEVEL:-info}"
      --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
      --prefetch-multiplier=1
    )
    if [[ -n "${CELERY_QUEUES:-}" ]]; then
      worker_args+=(--queues="${CELERY_QUEUES}")
    fi
    exec "${worker_args[@]}"
    ;;
  beat)
    exec celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  migrate)
    # Migrate the public schema (shared apps) AND every tenant schema. Bare
    # migrate_schemas does both; running --shared first surfaces shared-app
    # failures with a clearer error before tenant migrations fan out (TD-17).
    python manage.py migrate_schemas --shared
    exec python manage.py migrate_schemas --tenant
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
