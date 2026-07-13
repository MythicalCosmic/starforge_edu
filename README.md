# Starforge Edu — backend

Multi-tenant Django backend for an Uzbek education platform.

## Stack
- Django 6.0 with layered plain-Django APIs; DRF remains only for reports compatibility
- Custom whole-API OpenAPI 3.0 schema, Swagger UI, and Redoc
- django-tenants (schema-per-tenant) with subdomain routing
- Channels + Redis (realtime); Celery + tenant-schemas-celery (background)
- Postgres 16, S3-compatible storage (MinIO in dev / AWS S3 in prod)
- Anthropic Claude (`claude-sonnet-4-6`) with prompt caching
- Eskiz SMS (real client + dev mock)
- uv for dependency management; ruff + mypy + pytest

## Layout
```
config/        Django project: settings split, urls, asgi/wsgi, celery
apps/          One Django app per domain (tenancy, org, users, auth, ...)
core/          Cross-cutting primitives (auth, permissions, HTTP, schema, exceptions)
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
- `http://demo.localhost:8000/admin/`  (login: `admin` / `starforge-dev`)
- `http://demo.localhost:8000/api/schema/swagger-ui/`
- `POST http://demo.localhost:8000/api/v1/auth/login/  {"username":"admin","password":"starforge-dev"}`

## Tenancy
- `apps.tenancy.Center` is the tenant model; `apps.tenancy.Domain` maps hostnames.
- `apps.tenancy` is in `SHARED_APPS` only — Center + Domain live in the public schema.
- Everything else is in `TENANT_APPS` — exists once per Center schema.
- All Celery tasks run under the right schema via `tenant-schemas-celery`.
- Channels consumers resolve tenant from hostname before any DB access (`infrastructure/websocket/middleware.py`).

## Auth
- The API uses opaque, revocable server-side sessions. Send the returned key as `Authorization: Bearer <access>`; the tenant schema containing the session binds it to that center.
- Student, teacher, parent, and staff identities and passwords live in their own role tables. Use `POST /api/v1/auth/role-login/ {username, password}` → `{success, data:{access, role, must_change_password}}`. Login is throttled per identifier and per IP.
- `POST /api/v1/auth/login/` is reserved for Django/platform-admin accounts and rejects role-account bridge principals.
- **Password reset = OTP** via Eskiz SMS or email: `POST /api/v1/auth/password/reset/{request,confirm}/`. Throttled per-identifier (3/min), per-IP, and globally; responses never reveal whether an account exists.
- Password change revokes all prior sessions and returns one fresh opaque session.
- `/admin/` uses Django's normal session authentication. Role accounts are managed in separate Student, Teacher, Parent, and Staff admin sections; hidden compatibility principals are not selectable in the User table.

## Permissions
- Role-permission matrix lives in `core/permissions.py`.
- Layered views call `check_perm()` for action-level access and query through branch/department-scoped selectors and repositories. Role changes are evaluated live on every request.

## API contract
- Tenant schema: `/api/schema/`; public/platform schema: the same path on the apex host.
- Swagger UI: `/api/schema/swagger-ui/`; Redoc: `/api/schema/redoc/`.
- `uv run python scripts/export_openapi.py --validate` exports `openapi.yaml` and `openapi-public.yaml` and verifies all operation IDs are unique.

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
