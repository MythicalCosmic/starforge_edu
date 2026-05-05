#!/usr/bin/env bash
set -euo pipefail

case "${1:-web}" in
  web)
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -
    ;;
  daphne)
    exec daphne -b 0.0.0.0 -p 8001 config.asgi:application
    ;;
  worker)
    exec celery -A config worker --loglevel=info --concurrency=4
    ;;
  beat)
    exec celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  migrate)
    exec python manage.py migrate_schemas --shared
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
