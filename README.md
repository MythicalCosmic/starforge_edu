# Starforge Edu — backend

Multi-tenant Django backend for an Uzbek education platform.

## Stack
- Django 6.0 + DRF 3.17, simplejwt, drf-spectacular
- django-tenants (schema-per-tenant) with subdomain routing
- Channels + Redis (realtime); Celery + tenant-schemas-celery (background)
- Postgres 16, S3-compatible storage (MinIO in dev / AWS S3 in prod)
- Anthropic Claude (`claude-opus-4-7`) with prompt caching
- Eskiz SMS (real client + dev mock)
- uv for dependency management; ruff + mypy + pytest

## Layout
```
config/        Django project: settings split, urls, asgi/wsgi, celery
apps/          One Django app per domain (tenancy, org, users, auth, ...)
core/          Cross-cutting primitives (permissions, viewsets, exceptions)
infrastructure/ External clients (sms, storage, ai, payments, websocket)
celery_tasks/  Background job modules
docker/        Multi-service compose stack
scripts/       create_tenant.py, seed_dev.py
docs/          Architecture + ops docs
```

## First run
```bash
cp .env.example .env

# Bring up Postgres + Redis + MinIO
docker compose -f docker/docker-compose.yml up -d postgres redis minio

# Install deps
uv sync --all-groups

# Migrate the public schema (Center + Domain models)
uv run python manage.py migrate_schemas --shared

# Seed a demo tenant: schema=demo, hostname=demo.localhost, +superuser
uv run python scripts/seed_dev.py

# Run the dev server
uv run python manage.py runserver
```

Then hit:
- `http://demo.localhost:8000/admin/`  (login: `+998901234567` / `starforge-dev`)
- `http://demo.localhost:8000/api/schema/swagger-ui/`
- `POST http://demo.localhost:8000/api/v1/auth/otp/request/  {"identifier":"+998901234567"}`

## Tenancy
- `apps.tenancy.Center` is the tenant model; `apps.tenancy.Domain` maps hostnames.
- `apps.tenancy` is in `SHARED_APPS` only — Center + Domain live in the public schema.
- Everything else is in `TENANT_APPS` — exists once per Center schema.
- All Celery tasks run under the right schema via `tenant-schemas-celery`.
- Channels consumers resolve tenant from hostname before any DB access (`infrastructure/websocket/middleware.py`).

## Auth
- JWT everywhere via `djangorestframework-simplejwt` (15-min access, 14-day rotating refresh, Redis denylist via `token_blacklist`).
- `/admin/` keeps Django sessions enabled.
- Login = OTP via Eskiz SMS or email. Endpoints: `POST /api/v1/auth/otp/{request,verify}/` → `{access, refresh}`.
- Phone OR email may be the identifier (`apps.auth.backends.PhoneOrEmailBackend`).
- OTP throttled per-phone (3/min), per-IP (10/min), and globally (1000/h).

## Permissions
- Role-permission matrix lives in `core/permissions.py`.
- `RolePermission` (action-level) + `ObjectScopedPermission` (branch/department) compose on every `TenantSafeModelViewSet`.

## Tests
```bash
uv run pytest
uv run ruff check .
uv run mypy apps core infrastructure config
```

## Documents
- `docs/architecture.md` — tenancy, auth, permissions, events
- `docs/adding-an-app.md` — how to add a new domain app
- `docs/deployment.md` — production deployment notes
