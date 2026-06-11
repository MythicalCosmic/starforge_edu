# Architecture

## Tenancy
- **Strategy:** schema-per-tenant via `django-tenants`.
- **Tenant model:** `apps.tenancy.Center` (lives in `SHARED_APPS` only).
- **Hostname → tenant:** `apps.tenancy.Domain` rows; e.g. `acme.starforge.uz` → `Center(schema_name='acme')`.
- **`SHARED_APPS`:** `django_tenants`, `apps.tenancy`, Django contrib (admin/auth/contenttypes/sessions/messages/staticfiles), `django_celery_beat`, `channels`, `corsheaders`.
- **`TENANT_APPS`:** users, auth, org (Branch+Department), the 16 domain apps, plus contrib (so Django admin works inside a tenant).
- **Migrations:** `migrate_schemas --shared` for public; `migrate_schemas` runs per tenant when a new Center is created (auto, via `auto_create_schema=True`).
- **Celery:** `tenant-schemas-celery` activates the right schema for every task. Pass `_schema_name="acme"` when delaying from a context that already knows the tenant (otherwise the request middleware already set the connection).
- **Channels:** `TenantAwareJWTAuthMiddleware` resolves tenant from hostname, then authenticates the user. **Never** access tenant data from a consumer before this middleware has run.
- **Management commands:** wrap with `schema_context("acme"):` or use `tenant_command`.

## Auth
- **Tokens:** JWT (simplejwt). Access 15min, refresh 14d, rotation on, blacklist on. Both tokens carry TD-1 claims: `schema` (issuing tenant — enforced on access AND refresh paths, 401 `tenant_mismatch` otherwise) and `tv` (token version — bumped on password change, role change, logout-everywhere).
- **Login flow:** `POST /api/v1/auth/login/ {username, password}` → `{access, refresh}` (owner decision 2026-06-11; supersedes OTP-as-login).
- **Password reset:** `POST /api/v1/auth/password/reset/request/ {identifier}` (always 202, anti-enumeration) → SMS/email OTP → `POST /api/v1/auth/password/reset/confirm/ {identifier, code, new_password}` (ends all sessions).
- **Password change:** `POST /api/v1/auth/password/change/` — ends all other sessions, returns a fresh pair.
- **Admin:** `/admin/` sessions; staff log in with username (stock backend) or phone/email (`PhoneOrEmailBackend`).
- **Logout:** `POST /api/v1/auth/logout/ {refresh}` blacklists one refresh; `POST /api/v1/auth/logout-all/` revokes everything.

## Permissions
- **Matrix:** `core/permissions.py: ROLE_PERMISSION_MATRIX` — single source of truth.
- **Action-level (TD-5):** viewsets declare `resource = "<name>"` (verbs derived per action: list/retrieve → `:read`, create/update/destroy → `:write`) plus `required_perms: dict` for custom actions/overrides. Views with neither mapping are **fail-closed** (denied). The flat `required_perm` attribute is gone.
- **Row-level:** `read_self` / `read_own_children` verbs are enforced by queryset scoping in `selectors.py` (the gate grants `:read`; the selector narrows rows to self / linked children).
- **Object-level:** `ObjectScopedPermission` reads `view.object_scope = "branch" | "department"` and checks `RoleMembership(user, branch[, department])`.
- **Director / superuser:** bypass.

## Events / cross-app coupling
- Apps emit Django signals; `apps/notifications/services.dispatch(event)` is the canonical fan-out for sms/email/push/in-app. Apps must NOT call channel adapters directly.
- Audit logging is signal-driven and lives in `apps/audit/` (out of `apps/reports/`).

## Cost guardrails
- AI calls (`apps/ai/`) are Celery-only. `TenantAIBudget` checked before queueing.
- Anthropic client (`infrastructure/ai/anthropic_client.py`) caches identical prompt+system+model triplets in Redis; Anthropic prompt caching is enabled by default at the request level.
- OTP is throttled three ways (per-phone, per-IP, global). Eskiz mocked in dev.

## Storage
- **`STORAGES["default"]`** is S3-compatible. Use the same code against AWS S3 (prod) and MinIO (dev).
- Signed up/download via `infrastructure/storage/s3_client.py`.

## Realtime
- ASGI via Daphne; channel layer on Redis (`channels-redis`).
- One demo consumer at `/ws/ping/` proves the wiring; per-app routing aggregates into `infrastructure/websocket/routing.py`.

## Out of scope (post-v1)
- Branch print agent (separate Go/Python repo).
- Live integration with Click / Payme / Uzum (stubs only in v1).
- Frontends (React + Flutter).
- Production deploy beyond the compose stack.
