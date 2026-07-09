# API-CONTRACT.md — API Conventions & Frontend Handoff

> Two audiences. **(a) Agents** adding or changing any endpoint: these conventions are mandatory, enforced by review and CI. **(b) Frontend developers** (React web, Flutter mobile): this is your integration guide. Endpoints marked **D1–D5** land on that build day (see ROADMAP.md §5); **D0** is live now. The Day-5 Lane D pass replaces hand-written examples here with real captured responses and freezes the contract (TD-18).

---

## 1. Environments & base URLs

| Environment | REST base | WebSocket base | Notes |
|---|---|---|---|
| Dev (docker compose) | `http://demo.localhost:8000` | `ws://demo.localhost:8001` | `demo` tenant from `scripts/seed_dev.py`; `*.localhost` resolves to 127.0.0.1 |
| Dev apex (public schema) | `http://localhost:8000` | — | Platform API + platform `/admin/` |
| Prod tenant | `https://<center>.starforge.uz` | `wss://<center>.starforge.uz` | One subdomain per Center `[OWNER:O-8]` DNS/wildcard TLS, `[OWNER:O-9]` hosting |
| Prod apex | `https://starforge.uz` | — | Platform API, webhooks, tenant discovery |

Ports (from `docker/docker-compose.yml`):

| Port | Service | Purpose |
|---|---|---|
| 8000 | `web` (gunicorn, WSGI) | All REST/API traffic |
| 8001 | `daphne` (ASGI) | WebSockets only (`/ws/...`) |
| 9000 / 9001 | `minio` | S3 API / MinIO console (dev S3) |
| 5432 / 6379 | postgres / redis | Backend only — never touched by clients |

In prod a reverse proxy serves both on 443 and routes `/ws/` to daphne; clients then use one host for everything. In dev, point WS at **8001** explicitly.

**CORS posture:** `CORS_ALLOWED_ORIGINS` env list (`config/settings/base.py`), `CORS_ALLOW_CREDENTIALS = True`. Dev: add your Vite origin (e.g. `http://localhost:5173`) to `CORS_ALLOWED_ORIGINS` in compose/`.env`. Prod: strict allowlist, never `CORS_ALLOW_ALL_ORIGINS` (TASKS §25, D5-A). Mobile apps are unaffected by CORS. Auth uses the `Authorization` header, not cookies — no CSRF for API calls (CSRF applies to `/admin/` only).

---

## 2. Tenancy — what clients must know

Why: every Center lives in its **own Postgres schema** (django-tenants, ADR-001). The hostname picks the schema — `demo.localhost` serves only `demo`'s data. There is no `?tenant=` parameter and no cross-tenant API; the host **is** the tenant selector.

- **Web (React):** the app is served from the tenant subdomain. API base = `window.location.origin`. Nothing to configure (TASKS §27).
- **Mobile (Flutter):** tenant discovery per TD-19 (**D5**, public, unauthenticated):

```http
GET https://starforge.uz/api/v1/platform/resolve/?slug=demo

200 {"name": "Demo School", "base_url": "https://demo.starforge.uz",
     "ws_url": "wss://demo.starforge.uz", "logo": "https://...", "locale": "uz"}
```

Cache `base_url`/`ws_url` in app storage; ALL subsequent calls go to that host. Unknown slug → 404 `not_found`.

**JWTs are tenant-bound (TD-1, D1):** tokens carry a `schema` claim and are rejected with **401 `tenant_mismatch`** on any other tenant's host. Switching Centers = wipe tokens, resolve the new tenant, full re-login. Never share a token store across tenants.

---

## 3. Auth lifecycle

All endpoints in `apps/auth/urls.py` under `/api/v1/auth/`. **Login is username + password** (owner decision 2026-06-11). OTP codes exist only for **password reset** (sent to the phone/email on file). Accounts are created by staff; the generated username + initial password are handed to the user.

### 3.1 Login — `POST /api/v1/auth/login/` (D1)

```http
POST /api/v1/auth/login/
{"username": "aziz.karimov", "password": "<password>",
 "device_id": "a1b2c3-stable-uuid", "platform": "android"}     # device fields optional

200 {"access": "<jwt>", "refresh": "<jwt>"}
```

Failures are deliberately indistinguishable — unknown username, wrong password, and deactivated account all return:

```http
401 {"success": false, "code": "invalid_credentials", "message": "Invalid username or password."}
```

Throttles: `login_user` 5/min per username, `login_ip` 10/min per IP → `429 throttled`. `device_id` is a client-generated stable UUID (keep it in app storage); the server upserts a `Device` row (TASKS §3, D1-C).

### 3.2 Password reset — `POST /api/v1/auth/password/reset/{request,confirm}/` (D1)

```http
POST /api/v1/auth/password/reset/request/
{"identifier": "+998901234567"}                # phone (E.164) or email ON FILE

202 (empty body)    # ALWAYS 202 — even for unknown identifiers (anti-enumeration).
                    # A 6-digit code goes out via SMS (Eskiz) or email when an account matches.
```

```http
POST /api/v1/auth/password/reset/confirm/
{"identifier": "+998901234567", "code": "123456", "new_password": "<new>"}

204                 # password set; EVERY session ended — user logs in fresh
```

Request throttles: `otp_phone` 3/min per identifier + 60 s resend cooldown (`Retry-After` header set — disable the resend button that long), `otp_ip` 10/min, `otp_global` 1000/hour. Confirm: `otp_verify` 10/min; the code dies after 5 wrong attempts (`OTP_MAX_ATTEMPTS`) → `429 throttled`. Weak passwords → `400 weak_password`; wrong code → `400 validation_error`.

### 3.2b Password change — `POST /api/v1/auth/password/change/` (D1, authed)

```http
POST /api/v1/auth/password/change/
Authorization: Bearer <access>
{"old_password": "<old>", "new_password": "<new>"}

200 {"access": "<jwt>", "refresh": "<jwt>"}   # all OTHER sessions ended; store this pair
```

Errors: `400 wrong_password`, `400 weak_password`.

### 3.3 Token claims (D1-C, TD-1/TD-5)

| Claim | Meaning |
|---|---|
| `user_id` | PK of the user (`SIMPLE_JWT["USER_ID_CLAIM"]`) |
| `schema` | Issuing tenant's `schema_name` — must match the host (TD-1) |
| `tv` | User `token_version`; bumped on password/role change → all live tokens die |
| `roles` | Denormalized role codes at issue time, e.g. `["teacher"]` — UI hints ONLY, server re-checks every request |
| `exp`, `iat`, `jti`, `token_type` | Standard simplejwt claims |

Lifetimes (`SIMPLE_JWT`): **access 15 min, refresh 14 days**.

### 3.4 Refresh — `POST /api/v1/auth/refresh/` (D0)

```http
POST /api/v1/auth/refresh/
{"refresh": "<refresh-jwt>"}

200 {"access": "<new-access>", "refresh": "<new-refresh>"}
```

Rotation is ON (`ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`): the response **always contains a new refresh token; store it immediately — the old one is blacklisted and dead**. Presenting a blacklisted refresh is treated as theft: ALL of that user's refresh tokens are revoked globally (401 `refresh_reused`). The refresh path is tenant-bound like the access path — a refresh minted on another center's host returns 401 `tenant_mismatch`. Any 401 from this endpoint → wipe both tokens, route to login. Do not retry.

**Recommended client strategy:** decode `exp` from the access token; refresh proactively when < 60 s remain, or reactively on the first 401. Serialize refreshes behind a single-flight mutex (web: shared promise; Flutter: dio `QueuedInterceptor`) so parallel 401s don't double-rotate and trip reuse detection. Persist both tokens atomically.

### 3.5 Logout

```http
POST /api/v1/auth/logout/            {"refresh": "<jwt>"} → 200     # blacklists that refresh (D0)
POST /api/v1/auth/logout-all/        {} (Bearer auth)     → 204     # blacklists ALL refreshes + bumps tv (D1-C)
```

Access tokens live their remaining ≤15 min after logout; clients must also discard them locally.

### 3.6 Who am I — `GET /api/v1/users/me/` (D0)

Call once after login (and on app start) to hydrate the session. Shape from `apps/users/serializers.py: UserSerializer`:

```http
GET /api/v1/users/me/
Authorization: Bearer <access>

200 {"id": 1, "username": "aziz.karimov", "phone": "+998901234567", "email": null,
     "first_name": "Aziz", "last_name": "Karimov", "middle_name": "",
     "full_name": "Aziz Karimov", "is_active": true, "is_staff": false,
     "date_joined": "2026-06-01T09:00:00+05:00", "last_seen_at": "2026-06-10T14:30:00+05:00",
     "role_memberships": [{"id": 3, "role": "teacher", "branch": 1, "department": 2,
                           "granted_at": "2026-06-01T09:00:00+05:00"}]}   # ACTIVE memberships only
```

Drive navigation/feature visibility from `role_memberships[].role` (role codes in `core/permissions.py: Role` — `director`, `head_of_dept`, `teacher`, `student`, `parent`, `accountant`, `cashier`, `librarian`, `security`, `it`, `registrar`, `support`). D1 adds `avatar`, `preferred_language`, `birthdate`, `gender` (TASKS §3).

### 3.7 Push token registration (D1-C; delivery gated `[OWNER:O-7]`, mock-first per TD-2)

```http
POST /api/v1/users/devices/   {"device_id": "a1b2c3...", "platform": "android",
                               "push_token": "<fcm-token>"}        → 201
GET  /api/v1/users/devices/                                        → 200 list (own devices)
DELETE /api/v1/users/devices/{id}/                                 → 204 revoke (kills that device's refresh)
```

Re-POST with the same `device_id` to rotate the push token. Tokens dead after N push failures are auto-revoked (TASKS §17 bounce handling).

### 3.8 Impersonation tokens (D4-E, TD-10)

Platform admins can mint a short-lived, read-only token for a tenant. It carries `imp: true` and `ro: true` claims. **Clients must check `ro` and hide/disable every write action**; the server rejects writes regardless (403 `forbidden`). Show a visible "viewing as support" banner when `imp` is set. Heavily audited (TD-9).

---

## 4. Conventions (every endpoint, no exceptions)

### 4.0 Request headers checklist

| Header | Value | When |
|---|---|---|
| `Authorization` | `Bearer <access>` (`SIMPLE_JWT["AUTH_HEADER_TYPES"]`) | Every call except `auth/login/`, `auth/password/reset/*`, `auth/refresh/`, `platform/resolve/` |
| `Accept-Language` | `uz` \| `ru` \| `en` | Every call (§4.6) |
| `Content-Type` | `application/json` | Every request with a body (S3 PUTs excepted, §5) |
| `Idempotency-Key` | UUIDv4 | Required on payment-adjacent POSTs (§4.7) |
| `X-Request-ID` | UUIDv4 (optional) | Echoed back by the server (D1-A) — log it, quote it in bug reports |

### 4.1 Error envelope (TD-18, `core/exceptions.py`)

Every non-2xx response (except `/healthz/*` and provider-exact payment webhooks) is ONE flat shape:

```json
{"success": false, "code": "validation_error", "message": "Invalid input.",
 "errors": {"due_at": ["This field is required."]}}
```

`code` is stable and machine-readable — branch on it (or on `success`), never on `message` (which is localized per Accept-Language). `errors` appears only on validation errors. Error-code catalog:

| HTTP | `code` | When | Since |
|---|---|---|---|
| 400 | `validation_error` | Bad input; per-field detail in `fields` | D0 |
| 400 | `tenant_required` | Tenant-scoped code hit without a tenant host | D0 |
| 400 | `wrong_password` | Password change: `old_password` incorrect | D1 |
| 400 | `weak_password` | New password fails the validators (min 10 chars, not common/numeric) | D1 |
| 401 | `invalid_credentials` | Login failed (unknown username / wrong password / inactive — indistinguishable) | D1 |
| 401 | `authentication_failed` | Missing/expired/invalid access token | D0 |
| 401 | `tenant_mismatch` | Token's `schema` ≠ this host's tenant (access AND refresh paths) | D1 |
| 401 | `token_stale` | Token's `tv` ≠ current token_version (password/role change, logout-all) | D1 |
| 401 | `refresh_reused` | Blacklisted refresh replayed — ALL sessions revoked; full re-login | D1 |
| 402 | `subscription_required` | Center's subscription suspended/expired (TD-8) — see §10 | D3 |
| 403 | `forbidden` | Role lacks `resource:verb`, or object out of branch/department scope | D0 |
| 404 | `not_found` | Missing resource OR cross-tenant ID probe (indistinguishable by design) | D0 |
| 409 | `conflict` | Duplicate (e.g. schedule room/teacher overlap, idempotency replay mismatch) | D2 |
| 429 | `throttled` | Rate limit; honor `Retry-After` | D0 |
| 500 | `error` | Unhandled server error (request_id in logs, D1-A) | D0 |

(Agents: today generic DRF errors fall through as `code: "api_error"` with nested detail — `drf_exception_handler` last branch. D1 Lane C/A normalizes DRF `ValidationError`→`validation_error` with `fields`, `NotAuthenticated`/`InvalidToken`→`authentication_failed`, `Throttled`→`throttled` + `Retry-After`. Raise `StarforgeError` subclasses from services; never hand-build error JSON in a view.)

Client decision table — wire this into one HTTP interceptor, not per-screen:

| On | Do |
|---|---|
| 401 `authentication_failed` | Refresh once (single-flight, §3.4), replay the request; if refresh also 401s → wipe tokens, login screen |
| 401 `tenant_mismatch` | Wrong tenant host for this token — wipe tokens, re-resolve tenant (mobile), login screen |
| 402 `subscription_required` | Global paywall state (§10) |
| 403 `forbidden` | Show "no access", hide the action going forward — do NOT retry or logout |
| 409 `conflict` | Surface the `detail` to the user (e.g. schedule overlap); safe to retry after user edits |
| 429 `throttled` | Back off per `Retry-After`; never hammer |
| 5xx / network | Retry idempotent GETs with backoff (max 3); POSTs only if they carry an `Idempotency-Key` |

### 4.2 Pagination (`core/pagination.py`)

**Page-number** (`DefaultPagination` — the default for all list endpoints). `?page=2&page_size=50`, default 25, max 200:

```json
{"count": 312, "next": "https://demo.starforge.uz/api/v1/students/?page=3",
 "previous": "...?page=1", "results": [ ... ]}
```

Iterate by following `next` until `null` — do not compute page counts yourself.

**Cursor** (`TimelinePagination` — audit log, notification feed, append-only timelines; page size 50, ordered `-created_at`). `?cursor=<opaque>`:

```json
{"next": "...?cursor=cD0yMDI2LTA2...", "previous": null, "results": [ ... ]}
```

No `count`; treat the cursor as opaque, follow `next` until `null`.

### 4.3 Filtering / search / ordering

`django-filter` is the default backend; list endpoints additionally declare search + ordering (DoD #5). Exact filter fields per endpoint are in the OpenAPI schema.

```
GET /api/v1/students/?cohort=12&status=active          # declared filters, AND-ed
GET /api/v1/students/?search=karimov                   # icontains over declared fields (name/phone/ID)
GET /api/v1/students/?ordering=-enrollment_date        # `-` = desc; comma-separate for multi
```

Unknown filter params are ignored; invalid values → 400 `validation_error`.

### 4.4 Datetime & timezone

ISO 8601 with UTC offset, always tz-aware (`USE_TZ=True`, `TIME_ZONE="Asia/Tashkent"`): `"2026-06-10T14:30:00+05:00"`. Naive datetimes in requests are rejected. Date-only fields are `"YYYY-MM-DD"` (no offset). Clients may send any offset; render in Asia/Tashkent unless the user picked otherwise.

### 4.5 Money

All monetary amounts are **integers in minor units**: tiyin for UZS (1 UZS = 100 tiyin), cents for USD. Never floats, never decimal strings. Every money-bearing object carries a sibling `currency` field (`"UZS"` default, per-Center via TD-13). Invoices snapshot the FX rate at issuance (TASKS §15) — display historical totals from the stored amounts, never re-convert client-side.

```json
{"total": 1500000, "currency": "UZS"}      // = 15 000.00 UZS
```

### 4.6 i18n

`Accept-Language: uz | ru | en` (uz default, `LANGUAGE_CODE`). Localizes `detail` strings, validation messages, generated documents. Authenticated users' `preferred_language` (D1, TASKS §3) wins over the header for notifications/SMS. Send the header on every request anyway — it covers pre-login responses.

### 4.7 Idempotency

Payment-adjacent POSTs (payment creation, refund requests — TASKS §16/§22) **require** an `Idempotency-Key` header: client-generated UUIDv4, persisted across retries of the same logical operation. Replay with the same key returns the original response (same status); same key with a different body → 409 `conflict`. Keys are retained 24 h. Safe to send on any POST; harmless elsewhere.

---

## 5. Files (D2-E, TASKS §13/§23; presign helpers exist in `infrastructure/storage/s3_client.py`)

Uploads never go through Django — clients PUT directly to S3/MinIO via presigned URL:

```http
1) POST /api/v1/content/upload-url/
   {"filename": "essay.pdf", "content_type": "application/pdf",
    "size_bytes": 1048576, "purpose": "assignment_submission"}

   200 {"key": "demo/tmp/9f3a.../essay.pdf",
        "url": "http://localhost:9000/starforge-media/demo/tmp/...&X-Amz-Signature=...",
        "method": "PUT", "headers": {"Content-Type": "application/pdf"}, "expires_in": 600}

2) PUT <url>  (body = raw bytes, header Content-Type exactly as returned)  → 200 from S3

3) POST /api/v1/content/files/   {"key": "demo/tmp/9f3a.../essay.pdf", "title": "Essay"}
   → 201 file record   (server libmagic-validates, moves out of tmp/)
```

Rejections at step 1: type not in the Center's allowlist or size over the per-Center cap (TD-13, default 200 MB) → 400 `validation_error`. Unconfirmed `tmp/` objects expire after 7 days. Dev CORS for browser PUTs is configured on the MinIO bucket by `seed_dev.py`.

**Downloads:** every API response exposes files as short-TTL (~10 min) signed URLs, fresh on each fetch. **Never persist a signed URL** — store the resource ID, re-fetch the record when you need the link. Images additionally expose `variants: {"thumbnail": "<signed>", "medium": "<signed>"}` (Pillow, async — may be `null` for the first seconds after upload; fall back to the original).

---

## 6. Realtime — WebSocket (auth D0; real consumers D4-C, TD-15)

Connect to the **tenant host** on the ASGI port. Auth (`infrastructure/websocket/middleware.py: TenantAwareJWTAuthMiddleware`) accepts the **access** token via either transport:

```
A) Subprotocol (recommended for browsers — keeps the token out of URLs/logs):
   new WebSocket("ws://demo.localhost:8001/ws/notifications/", ["bearer." + accessToken])
   — server accepts with subprotocol "bearer"
B) Query string (Flutter/non-browser):
   ws://demo.localhost:8001/ws/notifications/?token=<access>
```

| Path | Stream | Since |
|---|---|---|
| `/ws/ping/` | Smoke test: sends `{"type":"hello","user_id":N}`; `{"type":"ping"}` → `{"type":"pong"}` | D0 |
| `/ws/notifications/` | Per-user in-app notification stream — joins `{schema}.user.{id}` + `{schema}.branch.{b}` per active RoleMembership | D4 |
| `/ws/cohorts/{id}/attendance/` | Live attendance marks for one cohort — joins `{schema}.cohort.{id}` (requires `attendance:read` + branch scope) | D4 |

Group names are **schema-prefixed** server-side (shared-Redis tenant isolation); clients never address groups directly — they just open the path and receive frames.

**Close codes** (every code a D4-C consumer can emit):

| Code | Meaning | Client action |
|---|---|---|
| **4401** | Unauthorized — anonymous, cross-tenant token (schema claim ≠ host tenant), or stale `tv` (logout-everywhere / role change / password change) | Refresh the access token (§3.4), then reconnect with the new token. If refresh also fails, send the user to login. |
| **4403** | Forbidden — authenticated but not permitted: `/ws/cohorts/{id}/attendance/` requires `attendance:read` AND (director OR a RoleMembership in the cohort's branch); unknown cohort also closes 4403 | Do NOT retry this path with the same token; the user lacks access. Other sockets stay open. |
| **4408** | Heartbeat timeout — the server sent two pings with no intervening `pong` | Treat as a dead connection; reconnect (backoff below). |

**Message envelopes** (server→client, D4 consumers):

```json
// /ws/notifications/  (relayed from notifications.dispatch in-app channel)
{"type": "notification",
 "payload": {"id": 42, "event_type": "attendance.absent", "title": "...", "body": "...",
             "data": {"student_id": 7, "lesson_id": 12}, "created_at": "2026-06-10T14:30:05+05:00"}}

// /ws/cohorts/{id}/attendance/
{"type": "attendance.update",
 "payload": {"record_id": 9, "student_id": 7, "lesson_id": 12, "status": "absent", "auto": false}}
```

Unknown `type` values must be ignored, not crash the client.

**Heartbeat (server-driven, D4-C):** the **server** sends `{"type":"ping"}` every **30 s**; the client MUST reply `{"type":"pong"}`. Two consecutive server pings with no `pong` in between → the server closes **4408**. Clients should also treat 60 s of total silence as a dead link and reconnect. Access tokens expire in 15 min — on 4401, refresh first, then reconnect.

**Reconnect procedure (both clients):**

1. On close/error (except 4403, which is a permanent deny for that path): schedule reconnect with **exponential backoff + jitter** (1 s → 2 → 4 → 8 → … cap **30 s**); reset backoff to 1 s after a connection survives 60 s.
2. Before each attempt: if the access token has < 60 s left (or the prior close was 4401), refresh it (§3.4).
3. On successful (re)connect: **resync via REST** — `GET /api/v1/notifications/` (cursor feed) for missed items; for an attendance dashboard, re-fetch `GET /api/v1/attendance/records/?lesson=...`. Re-subscribe (reopen the same paths) after reconnect.
4. Pause attempts when the app is backgrounded (mobile) or the tab is hidden (web); reconnect on foreground.

**Contract: WS is best-effort, REST is the source of truth.** Messages missed while disconnected are NOT replayed over WS — a dropped socket simply misses the frame. The in-app feed (`GET /api/v1/notifications/`) and the attendance records endpoint are authoritative on reconnect. Never make a business decision from a WS payload alone — a WS event is a hint to re-fetch, the REST record is the fact.

---

## 7. Webhooks (server-to-server — not for frontend consumption)

Payment providers call the **public schema** (apex host), one path per provider per Center (TD-6, D3-B): `POST /api/v1/webhooks/click/<center_slug>/`, `.../payme/<center_slug>/` (JSON-RPC), `.../uzum/<center_slug>/`. Signature-verified against that tenant's `ProviderConfig`, replay-protected, error envelope per TD-18. Gated `[OWNER:O-3]` Click, `[OWNER:O-4]` Payme, `[OWNER:O-6]` Uzum — mock webhooks in dev (TD-2).

**What web/mobile do instead:** after initiating a payment, poll `GET /api/v1/payments/{id}/` every 3–5 s (cap ~2 min) for `status` ∈ `pending | completed | failed | cancelled`, **and** subscribe to `/ws/notifications/` where `payment.completed`/`payment.failed` arrives as a push. Recommended: WS for instant UI, polling as fallback; the `Payment` record is the truth.

---

## 8. Domain API index

Tenant host, prefix `/api/v1/` (`config/urls.py`); platform rows are apex (`config/urls_public.py`). Standard CRUD = `GET list / POST / GET {id} / PATCH {id} / DELETE {id}` on the base path. Permission codes are TD-5 `resource:verb` against `ROLE_PERMISSION_MATRIX` (`core/permissions.py`); list/retrieve need `:read`, mutations `:write` unless stated. **Since** = build day (ROADMAP §5).

| Endpoint | Purpose | Permission | Since |
|---|---|---|---|
| `POST auth/login/` · `refresh/` · `logout/` | Auth lifecycle (§3) | public | D1 |
| `POST auth/password/change/` · `reset/request/` · `reset/confirm/` | Password management (§3.2) | change: authed; reset: public | D1 |
| `POST auth/logout-all/` | Revoke all sessions | authenticated | D1 |
| `GET users/me/` | Current user + role_memberships | authenticated | D0 |
| `GET users/` · `GET users/{id}/` | User directory | `users:read` | D0 |
| `GET/POST/DELETE users/devices/` | Devices + push tokens (§3.6) | authenticated (own) | D0/D1 |
| `CRUD org/branches/` · `org/departments/` · `org/rooms/` | Org structure, rooms, hours, holidays | `org:read/write` | D1 |
| `GET org/settings/` · `PATCH org/settings/` | `CenterSettings` singleton (TD-13) | `org:read` / `org:write` | D1 |
| `CRUD students/` | StudentProfile + enrollment state machine | `students:read/write` | D1 |
| `GET students/{id}/dashboard/` | Aggregate: grades+attendance+assignments+finance | `students:read` (self/parent scoped) | D1 skeleton, full D3 |
| `POST students/import/` | Bulk CSV/Excel import (async, returns task) | `students:write` | D1 |
| `CRUD parents/` · `CRUD parents/guardians/` | ParentProfile + Guardian links | `parents:read/write` | D1 |
| `GET parents/me/students/` | Parent's linked students + per-student dashboard | `students:read_own_children` | D1 |
| `CRUD teachers/` | TeacherProfile, availability | `teachers:read/write` | D1 |
| `CRUD cohorts/` · `cohorts/{id}/members/` | Class groups + membership w/ dates | `cohorts:read/write` | D1 |
| `CRUD schedule/lessons/` · `schedule/rules/` | Lessons + recurrence (TD-12); 409 `conflict` on overlap | `schedule:read/write` | D2 |
| `GET schedule/ical/{token}/` | Per-user iCalendar feed (signed token, no JWT) | token-auth | D2 |
| `POST attendance/lessons/{id}/mark/` | (Bulk) mark per lesson | `attendance:write` | D2 |
| `GET attendance/records/` · `summary/` | Records + per-student/term % | `attendance:read*` | D2 |
| `CRUD academics/subjects/` · `exams/` · `results/` · `grades/` | Exams, grade entry (per-Center scheme, TD-13) | `academics:read/write` | D2 |
| `GET academics/students/{id}/transcript/` | Transcript PDF — 202 → poll → signed URL (TD-14) | `academics:read` (scoped) | D2 |
| `CRUD assignments/` · `assignments/{id}/submissions/` | Homework + S3 submissions (§5 flow) | `assignments:read/write` | D2 |
| `POST content/upload-url/` · `CRUD content/files/` · `folders/` | Library + signed upload (§5) | `content:read/write` | D2 |
| `CRUD finance/invoices/` · `discounts/` · `refunds/` | Invoicing, allocation | `finance:read/write` | D3 |
| `GET finance/students/{id}/statement/` | Statement of account PDF (202 → signed URL) | `finance:read_own`/`finance:read` | D3 |
| `POST payments/` (Idempotency-Key required) · `GET payments/{id}/` | Initiate + poll status (§7) | `payments:write` / `payments:read` | D3 |
| `GET payments/{id}/receipt/` | Receipt PDF + fiscal QR (TD-7, `[OWNER:O-5]` mock-first) | `payments:read` | D3 |
| `GET notifications/feed/` (cursor) · `POST notifications/{id}/read/` | In-app feed + read receipts | authenticated (own) | D3 |
| `GET/PATCH notifications/preferences/` | Per-event × channel prefs, quiet hours | authenticated (own) | D3 |
| `GET billing/subscription/` | Center's plan/status/period (TD-8) — 402-allowlisted | `org:read` | D3 |
| `GET audit/logs/` (cursor, read-only) | Append-only audit trail (TD-9) | `audit:read` | D3 |
| `POST ai/assignment-feedback/` · `exam-questions/` · `summarize/` | AI features — 202 + request id (budgeted, Celery-only, `[OWNER:O-2]` mock-first) | `assignments:write`/`academics:write`/`content:read` | D4 |
| `GET ai/requests/{id}/` · `GET ai/usage/` | Poll AI result · Center budget usage | per-feature / `org:read` | D4 |
| `GET reports/` · `POST reports/{id}/run/` · `GET reports/runs/{id}/` | Report library, 202 run → signed URL (PDF/XLSX) | `reports:read` | D4 |
| `CRUD printing/printers/` · `GET printing/jobs/` · `POST printing/jobs/` | Admin: printers + job queue | `printing:read/write` | D4 |
| `POST printing/agent/claim/` · `POST printing/agent/jobs/{id}/status/` | Branch print agent (separate repo) — Branch-bound long-lived token, NOT JWT | agent token | D4 |
| **apex** `GET/POST platform/centers/` + `suspend/` `activate/` | Center CRUD + lifecycle (TD-10) | platform staff (TD-3) | D0 broken → D1 |
| **apex** `GET platform/centers/{id}/usage/` · `subscriptions/` ops | Per-center usage, plan management `[OWNER:O-12]` | platform staff | D4 |
| **apex** `POST platform/impersonate/` | Mint read-only impersonation token (§3.7) | platform staff | D4 |
| **apex** `GET platform/resolve/?slug=` | Mobile tenant discovery (TD-19, §2) | public | D5 |
| **apex** `POST webhooks/{click,payme,uzum}/<center_slug>/` | Provider callbacks (§7) — not for frontends | signature | D3 |

OpenAPI is the authoritative per-field reference: `GET /api/schema/` (YAML), Swagger UI at `/api/schema/swagger-ui/`, Redoc at `/api/schema/redoc/` (D0).

---

## 9. Client generation (D5-D, TASKS §27)

```bash
# 1. Schema (CI job validates this on every PR)
uv run python manage.py spectacular --file openapi.yaml --validate

# 2. TypeScript (React web) — @hey-api/openapi-ts, axios client (pairs with TanStack Query)
npx @hey-api/openapi-ts -i openapi.yaml -o clients/typescript -c @hey-api/client-axios

# 3. Dart (Flutter) — openapi-generator, dio
npx @openapitools/openapi-generator-cli generate -i openapi.yaml -g dart-dio \
    -o clients/dart --additional-properties=pubName=starforge_api
```

**Regeneration policy:** CI diffs the generated `openapi.yaml` against the committed one (D5-D wires the gate, TASKS §1); a PR that changes the schema **fails until both clients are regenerated and committed** in the same PR. Generated code is never hand-edited.

**Versioning (TD-18):** everything is `/api/v1/`. After Day-5 handoff, v1 is frozen for breaking changes — additive only (new endpoints, new optional fields; clients must tolerate unknown fields). Breaking changes ship as `/api/v2/` alongside v1.

---

## 10. Paywall — 402 handling clients MUST implement (D3-E, TD-8)

When a Center's subscription is suspended/expired, **every tenant API route** returns:

```http
402 {"success": false, "code": "subscription_required",
     "message": "This center's subscription has expired."}
```

Required client behavior — treat 402 like a global state, not a per-call error:

1. Intercept 402 at the HTTP-client level (axios interceptor / dio interceptor).
2. Do NOT log the user out and do NOT retry — tokens are still valid.
3. Route to a full-screen renewal page: Center name, plan/status/period from `GET /api/v1/billing/subscription/` (allowlisted), and the platform payment link / "contact +998 ... " per `[OWNER:O-12]`/`[OWNER:O-13]`. Web and mobile show the same screen.
4. Re-probe (e.g. re-fetch the subscription) on app foreground/refresh; clear the state when calls succeed again.

**Allowlisted while suspended** (still 200): `/api/v1/auth/*`, `/api/v1/billing/subscription/`, `/admin/`, `/api/schema/*`. Everything else 402s — including WS-adjacent REST; expect WS connects to be refused too.

---

## Appendix — agent checklist before merging any endpoint

- [ ] Path under `/api/v1/`, registered in the app's `urls.py` (TD-18; DoD #6)
- [ ] Errors only via `StarforgeError` subclasses / DRF exceptions — envelope comes out right automatically (§4.1)
- [ ] List endpoint: paginated, filterable, searchable, ordered (§4.2–4.3; DoD #5)
- [ ] Per-action `required_perms` declared — fail-closed (TD-4/TD-5); row added to §8 table with the real permission code
- [ ] Money as integer minor units + `currency` (§4.5); datetimes tz-aware (§4.4); strings `gettext_lazy` (§4.6)
- [ ] `@extend_schema` with summary, tags, examples, error responses (DoD #7) — then `uv run python manage.py spectacular --file openapi.yaml --validate` passes
- [ ] External calls in Celery only; payment-adjacent POSTs accept `Idempotency-Key` (§4.7; DoD #9)
- [ ] New/changed endpoint reflected in this file's §8 index in the same PR

*Maintained by Day-5 Lane D. Agents: if your endpoint deviates from this file, fix the endpoint or fix this file in the same PR — never let them drift.*
