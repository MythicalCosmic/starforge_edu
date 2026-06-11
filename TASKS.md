# starforge_edu — backend tasks (exhaustive)

Every feature, every detail, in dependency order. Check items off as you ship them.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 0. Bootstrap (do first thing next session)

- [~] `docker compose -f docker/docker-compose.yml up -d postgres redis minio` (owner is setting up Postgres)
- [~] Wait for `pg_isready` and `redis-cli ping` to succeed (pending owner DB)
- [~] Create the `starforge` database if absent (pending owner DB)
- [x] `uv run python manage.py makemigrations` — generated real `0001_initial.py` per app (26 migration files)
- [x] Inspect each generated migration before committing (spot-checked `users`/`org`: db_constraint=False FKs + dependency ordering correct)
- [ ] Commit migrations as a single commit: `chore(migrations): initial migration graph for v1 apps` (will commit when asked)
- [~] `uv run python manage.py migrate_schemas --shared` — public schema (pending owner DB)
- [~] `uv run python scripts/seed_dev.py` (seed extended: branch/dept/2 teachers/cohort/5 students/2 parents; pending owner DB to run)
- [~] Verify `http://demo.localhost:8000/admin/` loads and login works (pending owner DB)
- [~] Verify `http://demo.localhost:8000/api/schema/swagger-ui/` renders (pending owner DB)
- [~] Hit `POST /api/v1/auth/login/ {"username","password"}`, get `{access, refresh}` back (AUTH PIVOT 2026-06-11: login = username+password; test written; pending owner DB)
- [~] Hit `POST .../auth/password/reset/request/` + `confirm/` — OTP now serves password reset only (tests written; pending owner DB)
- [~] Hit `GET /api/v1/users/me/` with Bearer, get 200 (test written; pending owner DB)
- [~] Verify tenant isolation: token from `demo` must NOT work against another tenant's hostname (test GREEN-by-construction, TD-1; pending owner DB to run)

---

## 1. Tooling, CI, infra polish

- [~] Pre-commit: `uv run pre-commit install` to wire local hooks (owner runs locally)
- [~] CI: push to GitHub, confirm jobs green (ci.yml updated; pending push)
- [x] Add `coverage` reporting to the test job (`pytest --cov=apps --cov=core --cov-fail-under=70`)
- [x] Add a `dependabot.yml` for weekly Python + GitHub Actions updates
- [~] Add a CODEOWNERS file once the team is more than one person (deferred — single dev)
- [x] Add a `Makefile` with `up`/`migrate`/`seed`/`test`/`lint`/`schema`/`makemigrations`
- [x] Configure ruff to fail on warnings in CI (verified — `ruff check` clean)
- [x] Configure mypy to run cleanly (now FULLY clean — 0 errors across 260 files)
- [~] Wire `drf-spectacular` schema diff in CI (DEFERRED to D5-D per plan)
- [x] Add Sentry error tracking (config-only, guarded; no DSN committed)
- [x] Add structured JSON logging for prod settings (`JsonFormatter`, prod only)
- [x] Add request ID middleware (`X-Request-ID` echoed back, surfaced in logs)
- [x] Add health check endpoints: `/healthz/live` + `/healthz/ready` (DB + Redis)
- [~] Add Prometheus metrics endpoint (DEFERRED to D5-A per plan)
- [~] Document runbook for rotating SECRET_KEY and ESKIZ credentials (DEFERRED to D5-E)

---

## 2. Tenancy (apps/tenancy + apps/org)

### Center lifecycle

- [x] `provision_center` service: validate slug is Postgres-safe (regex `^[a-z][a-z0-9_]{0,62}$`)
- [x] Reject duplicate slug with a clear error (`slug_taken`, pre-check not IntegrityError)
- [x] Reject reserved slugs: `public`, `admin`, `www`, `api`, `static`, `media` (`slug_reserved`)
- [x] On Center delete, refuse if tenant has > 0 users (require explicit `force=True`)
- [x] Center deactivation flow: `InactiveTenantMiddleware` → 503 `center_inactive`
- [x] Trial expiration: `deactivate_expired_trials` beat task (hourly, idempotent)
- [x] Center "soft delete" with archival schema rename + `archive_center` management command

### Domain management

- [x] Multiple domains per Center — `set-primary` platform endpoint (atomic)
- [~] Domain ownership verification: TXT record check (stub `verify_domain_txt` mock-pass, O-8)
- [ ] Wildcard fallback: `*.starforge.uz` resolves to apex with marketing site (O-8)

### Branch / Department

- [x] Branch schema: working hours, holidays, room list
- [x] Department: budget, head-of-department FK (+ TeacherProfile validation)
- [x] Branch ↔ Department ↔ User membership table (`RoleMembership`, now consumed)
- [~] Move/transfer student between branches: `record_transfer` history (full cascade is D2+)
- [x] Soft-delete a Branch: refuse if it has active students; allow if archived

### Public-schema admin

- [x] Restrict `/admin/` on apex domain to platform staff only (TD-3 public users + IsAdminUser)
- [ ] Tenant impersonation tool (DEFERRED to D4-E control center)
- [ ] Tenant usage dashboard (DEFERRED to D4-E control center)

---

## 3. Users + Auth (apps/users + apps/auth)

> **AUTH PIVOT (owner decision, 2026-06-11):** login is **username + password**
> (`POST /api/v1/auth/login/`); `User.username` is the unique identity
> (auto-generated for staff-created accounts). OTP items below are repurposed —
> they now power **password reset** (`/auth/password/reset/{request,confirm}/`)
> and future contact verification, never login. "Phone OR email login" items
> apply to `/admin/` sessions only.

### User model

- [ ] Add `avatar` ImageField (S3-backed via django-storages)
- [~] Add `birthdate`, `gender`, `national_id` (birthdate+gender DONE; national_id via EncryptedCharField deferred)
- [ ] Add `address` (separate model: country/region/city/street/postal)
- [x] Add `preferred_language` (one of uz/en/ru)
- [ ] Add `notification_preferences` per channel × event type (D3 notifications)
- [x] Validate phone in E.164 (`core.validators.normalize_phone`)
- [~] Validate email uniqueness case-insensitively (lowered on create; DB citext deferred)
- [x] Allow either phone OR email login (BOTH-for-high-risk is TBD)
- [ ] User merge tool: combine two users with the same person behind them (admin-only)
- [ ] User deactivation vs deletion (GDPR-style erasure with audit retention)

### OTP

- [ ] OTP code length configurable per channel (SMS=6, email=8?)
- [x] OTP cooldown: last OTP < 60s ago → 429 (CenterSettings.otp_cooldown_seconds)
- [x] OTP attempt limit: 5 wrong codes → throttled (increment now persists before raise)
- [x] OTP audit log: `otp_requested/verified/failed` signals with ip + user_agent (log-only; AuditLog D3)
- [x] Detect OTP enumeration: per-IP distinct-identifier cap per hour
- [ ] OTP via WhatsApp — separate channel
- [ ] OTP voice call fallback (Eskiz supports this)
- [~] OTP for email needs a different template (HTML + plaintext) — D3 notifications
- [x] OTP cleanup: `purge_expired_otps` registered daily in `CELERY_BEAT_SCHEDULE`

### JWT

- [x] Issue JWT with extra claims: `schema`, `tv`, `roles[]` (TD-1, on access + refresh)
- [x] Token versioning: bump `token_version` to invalidate all live tokens
- [x] Refresh token reuse detection: blacklisted refresh reused → revoke ALL + bump tv (`refresh_reused`)
- [~] Device-bound refresh: device registered on verify; refresh-time device validation deferred
- [x] Logout-everywhere endpoint: `POST /api/v1/auth/logout-all/`
- [ ] JWT revocation list cleanup: scheduled task to drop blacklisted refreshes after expiry

### Devices

- [x] Device registration on login (auto-create from User-Agent + client device_id)
- [x] Device list endpoint: `GET /api/v1/users/devices/`
- [x] Device revocation: `DELETE /api/v1/users/devices/{id}/` (soft, sets `revoked_at`)
- [x] Push token registration per device (store-only, O-7 for real FCM/APNs send)
- [ ] Detect impossible travel: flag same user from far-apart IPs within minutes

### Sessions / admin

- [x] Force re-login when password changes (`set_user_password` bumps tv)
- [x] Force re-login when role membership changes (RoleMembership receivers bump tv)
- [x] "Last seen at" updated on every authenticated request (throttled, in authenticator)
- [ ] "Login from new device" notification (push + email) (D3)

### Permissions

- [x] Wire ROLE_PERMISSION_MATRIX into every ViewSet (`resource`+`required_perms`, flat `required_perm` removed)
- [x] Object-level scoping: viewsets set `object_scope` where branch/department-scoped
- [x] Permission cache: memoize role memberships per request (one query)
- [ ] Add `RoleMembership` admin UI with bulk grant / bulk revoke
- [~] Audit every permission grant (tv-bump receivers exist; AuditLog row in D3)
- [x] Permission test matrix: parameterized pytest over (role, endpoint, verb)

---

## 4. Org structure (apps/org)

- [x] Branch CRUD with permission gates (only director / IT)
- [x] Department CRUD scoped to a Branch
- [x] Branch operating hours by weekday (bulk-replace endpoint)
- [x] Branch holidays (per-branch override; national-holiday seeding is D2)
- [x] Department head assignment (FK to User, validates TeacherProfile)
- [~] Department budget vs spent rollup (budget field done; spent-from-finance is D3)
- [x] Branch transfer history (`BranchTransfer` + `record_transfer`)
- [x] Branch capacity tracking (max students, max teachers — soft caps + `capacity_status`)
- [x] Room model under Branch: name, capacity, equipment (availability windows D2)

---

## 5. Students (apps/students)

- [x] Replace placeholder `StudentItem` with real `StudentProfile(OneToOne→User)`
- [x] Fields: enrollment_date, academic_level, current_cohort, guardian links, medical_notes (encrypted), emergency_contacts (JSON)
- [x] Student photo (S3 via django-storages, ImageField)
- [x] Student ID generation (auto, per-Center pattern — `DEMO-2026-00042`)
- [x] Enrollment workflow state machine (lead → … → graduated/withdrawn, re-enroll)
- [x] Drop / re-enroll history with reason codes (`EnrollmentEvent`)
- [x] Bulk import from CSV (stdlib `csv` not pandas; savepoint-per-row)
- [~] Student dashboard endpoint (skeleton; full aggregation D3)
- [x] Birthday list endpoint (filter by branch/cohort)
- [x] Student search on name + phone + ID (icontains; FTS deferred to D5)

---

## 6. Parents (apps/parents)

- [x] Replace placeholder with real `ParentProfile(OneToOne→User)`
- [x] `Guardian` link model: parent → student, with relationship type
- [x] Primary guardian flag (one per student — conditional UniqueConstraint + service guard)
- [x] Custody / visitation rules (`custody_notes` field)
- [x] Multiple students per parent (siblings) — `GET /parents/{id}/students/`
- [x] Parent → student visibility scope (selector scoping, read_own_children)
- [~] Parent app endpoints: dashboard per linked student (students list; full dashboard D3)
- [x] Pickup authorization list (separate from Guardian)
- [ ] Parent satisfaction survey (defer)

---

## 7. Teachers (apps/teachers)

- [x] Replace placeholder with real `TeacherProfile(OneToOne→User)`
- [x] Fields: hire_date, subjects[], qualifications, salary_type+rate, department FK
- [ ] Teacher availability calendar (weekly windows) (D2)
- [x] Substitute teacher pool (`is_substitute` flag + filter)
- [ ] Teacher load report (D2)
- [ ] Performance reviews (lifecycle)
- [ ] Teacher payroll inputs (push to `apps.finance` once wired)

---

## 8. Cohorts (apps/cohorts) — class groups

- [x] Replace placeholder with real `Cohort` model
- [x] Fields: name, branch FK, department FK, level, start/end_date, capacity, primary_teacher FK
- [x] Cohort membership: students with start/end dates (one-active constraint)
- [x] Co-teacher assignments (`CohortTeacher`)
- [x] Cohort rooms (`default_room` FK)
- [x] Move student between cohorts mid-term (history preserved, `cohort_member_moved` signal)
- [x] Cohort archive at end of term (read-only; writes → `cohort_archived`)
- [ ] Cohort messaging: bulk send (via notifications, D3)

---

## 9. Schedule (apps/schedule)

- [ ] Replace placeholder with `Lesson`, `TimeSlot`, `Room`, `Holiday` models
- [ ] Recurring lessons (RRULE-style: every Mon/Wed/Fri at 14:00 for 12 weeks)
- [ ] One-off lesson edits (cancel one occurrence, move one occurrence)
- [ ] Room booking conflict detection
- [ ] Teacher conflict detection (one teacher, one place at a time)
- [ ] Cohort conflict detection (one cohort, one lesson at a time)
- [ ] Holiday import (Asia/Tashkent national holidays seeded; per-branch overrides)
- [ ] Generate iCalendar feed per user (signed URL with token)
- [ ] Push notification 30 min before lesson
- [ ] Bulk reschedule (whole-week shift)
- [ ] Term/semester boundaries that auto-archive lessons

---

## 10. Attendance (apps/attendance)

- [ ] Replace placeholder with real `AttendanceRecord` model: student, lesson, status (present/absent/late/excused), marked_by, marked_at, note
- [ ] Mark-attendance endpoint scoped to a Lesson (teacher only)
- [ ] Bulk mark by cohort
- [ ] Attendance summary per student per term (% present)
- [ ] Auto-mark "absent" 30 min after lesson start if no record exists (Celery)
- [ ] Late threshold configurable per Center (default 10 min)
- [ ] Notify guardian on absence (via notification dispatch)
- [ ] Attendance correction window (24h to amend; after that requires director approval)
- [ ] Attendance export per cohort per term (CSV/PDF)
- [ ] Attendance dashboard per cohort per teacher

---

## 11. Academics (apps/academics)

- [ ] Replace placeholder with `Subject`, `Exam`, `ExamResult`, `Grade`, `Transcript` models
- [ ] Grading scheme (per-Center: letter A–F, GPA 0–4, percentage 0–100)
- [ ] Exam types: midterm, final, quiz, project, oral
- [ ] Exam generation (AI-assisted via apps.ai — gated)
- [ ] Grade entry per cohort per exam
- [ ] Bulk grade entry by CSV
- [ ] Grade audit (who changed, when, old value)
- [ ] Auto-calculate term grade from weighted exam results
- [ ] Generate transcript PDF per student
- [ ] Honor roll / academic-warning detection (configurable thresholds)
- [ ] Parent visibility: only student's grades, only after publication

---

## 12. Assignments / homework (apps/assignments)

- [ ] Replace placeholder with `Assignment`, `Submission`, `Grade` models
- [ ] Teacher creates assignment for a cohort with due date + attachments
- [ ] Student submits with attachments (S3) or text body
- [ ] Late submission flag with configurable grace period
- [ ] Plagiarism check stub (defer real integration)
- [ ] AI-assisted feedback (apps.ai)
- [ ] Resubmit allowed up to N times
- [ ] Grade rubric per assignment
- [ ] Assignment notifications: created, due-soon, graded

---

## 13. Content (apps/content)

- [ ] Replace placeholder with `LessonFile`, `Folder`, `ContentLibrary` models
- [ ] Hierarchy: Subject → Course → Module → Lesson → File
- [ ] File upload via signed S3 URL (already plumbed in infrastructure/storage)
- [ ] File-type allowlist (PDF, MP4, PPTX, DOCX, MP3, common image formats)
- [ ] File size cap (configurable per Center, default 200MB)
- [ ] libmagic content-type validation on upload
- [ ] Antivirus scan stub (defer ClamAV integration)
- [ ] Versioning per file
- [ ] Visibility scoping: department / cohort / role
- [ ] Watch / view tracking (who opened what, when)
- [ ] Download counter
- [ ] AI summary per file (gated by tenant AI budget)

---

## 14. Printing (apps/printing) — server side only

- [ ] Replace placeholder with `PrintJob`, `Printer`, `BranchAgent` models
- [ ] PrintJob fields: status (queued/picked/printing/done/failed), source (assignment/transcript/report), payload (S3 key), pages, copies, color, duplex, branch_id, agent_id, requested_by
- [ ] Printer registration per Branch (name, model, ip, capabilities)
- [ ] Branch agent auth: long-lived API token bound to a Branch
- [ ] Job claim endpoint for the agent: `POST /api/v1/printing/agent/claim/` returns next queued job
- [ ] Job status update endpoint for the agent
- [ ] Job retry policy on failure (max 3, exponential backoff)
- [ ] Print quotas per cohort per term (paper saving)
- [ ] Print job audit (who printed what, when, how many pages)
- [ ] **NOTE:** the actual CUPS-talking branch agent is a separate repo. Don't add CUPS code here.

---

## 15. Finance (apps/finance)

- [ ] Replace placeholder with `Invoice`, `InvoiceLine`, `Discount`, `Refund`, `CashierShift` models
- [ ] Invoice issuance per student per term (auto on enrollment)
- [ ] Tuition fee schedules per Center / per Cohort
- [ ] Sibling discount, scholarship, payment plan
- [ ] Payment allocation (one payment may cover multiple invoices)
- [ ] Cashier shift open/close with cash count
- [ ] Daily cashier report
- [ ] Outstanding balance per student
- [ ] Late-payment reminder schedule (Celery beat → notification dispatch)
- [ ] Currency: UZS as primary, USD secondary; per-Center config
- [ ] FX rate snapshot per invoice (so historical totals don't drift)
- [ ] Parent statement of account endpoint (PDF)

---

## 16. Payments (apps/payments)

- [ ] Replace placeholder with `Payment`, `PaymentAttempt`, `WebhookEvent` models
- [ ] Provider: Click — implement create_invoice, prepare, complete, signature verify
- [ ] Provider: Payme — implement JSON-RPC handlers (CheckPerformTransaction, CreateTransaction, PerformTransaction, CancelTransaction, CheckTransaction, GetStatement)
- [ ] Provider: Uzum — implement webhooks
- [ ] Idempotency key on every Payment creation
- [ ] Webhook signature verification (provider-specific)
- [ ] Webhook replay protection (store nonce, reject duplicates)
- [ ] Payment → Invoice allocation (auto when amounts match exactly; manual review otherwise)
- [ ] Refund flow (provider-specific; store refund attempts with state machine)
- [ ] Reconciliation report (daily): payments received vs invoices marked paid
- [ ] Payment receipt PDF generation
- [ ] Failed payment notification

---

## 17. Notifications (apps/notifications)

- [ ] Replace placeholder with `Notification`, `NotificationPreference`, `NotificationTemplate` models
- [ ] Channels: SMS (Eskiz), Email, Push (FCM/APNs), In-app
- [ ] Event types enum (long list; one per event the platform emits)
- [ ] Per-user × per-event-type × per-channel preferences (default sane)
- [ ] `dispatch(event)` central function — every other app calls this, never channels directly
- [ ] Templates with uz/en/ru variants
- [ ] Template variable substitution (Jinja-safe)
- [ ] Idempotency on dispatch (don't send same notification twice)
- [ ] Quiet hours per user (no SMS at 11pm–7am)
- [ ] Bulk notification (cohort-wide announcements) with rate limiting
- [ ] Notification history per user (in-app feed)
- [ ] Read receipts for in-app notifications
- [ ] Email open / click tracking (defer; design only)
- [ ] Bounce handling per channel (mark device push token dead after N failures)

---

## 18. AI (apps/ai)

- [ ] Replace placeholder with `TenantAIBudget`, `AIRequest`, `AIPrompt` models
- [ ] Per-Center daily/monthly token budget (defaults wired in settings)
- [ ] Pre-flight budget check before queueing any AI Celery task
- [ ] AI calls are Celery-only — no synchronous calls from request handlers
- [ ] Prompt caching via Anthropic + Redis (already wired in infrastructure/ai/anthropic_client.py)
- [ ] Use cases v1: assignment feedback, exam question generation, content summarization
- [ ] Per-feature cost cap (e.g. exam-gen costs N tokens — block if budget < N)
- [ ] AI usage report per Center per month
- [ ] Anonymize student data before sending to AI (no real names if avoidable)
- [ ] Redact PII from prompts (regex pass + LLM-based as fallback)
- [ ] Prompt registry (versioned, one place per use case)
- [ ] A/B prompt experiments (defer)

---

## 19. Audit (apps/audit)

- [ ] Replace placeholder with real `AuditLog` model: actor, action, resource_type, resource_id, before, after, ip, ua, ts
- [ ] Auto-record on save/delete via Django signals for sensitive models (User, RoleMembership, Invoice, Payment, Grade)
- [ ] Manual audit_log() helper for non-model events (login, logout, OTP request)
- [ ] Audit log is append-only (no DELETE permission)
- [ ] Retention policy: 7 years for finance/grades, 1 year for everything else
- [ ] Audit search UI (filter by actor, resource, time range)
- [ ] Audit export (CSV) for compliance requests

---

## 20. Reports (apps/reports)

- [ ] Replace placeholder with `Report`, `ReportRun`, `ReportSchedule` models
- [ ] Report library: enrollment, attendance, grades, finance, AI usage, storage usage
- [ ] One-shot generation via Celery (writes to S3, signed URL emailed)
- [ ] Scheduled reports (weekly/monthly) via django-celery-beat
- [ ] Per-role visibility: directors see all, accountants see finance, teachers see their cohorts
- [ ] PDF + Excel exports
- [ ] Cross-tenant analytics (platform admin only) — separate aggregation pipeline (see tenancy memory)

---

## 21. Channels / Realtime

- [ ] Replace demo PingConsumer with real consumers per app:
  - [ ] `attendance` — live attendance updates per cohort
  - [ ] `notifications` — in-app notification stream per user
  - [ ] `chat` (defer) — direct messaging between teacher and parent
- [ ] Tenant resolution from hostname (already wired in middleware)
- [ ] JWT auth on connect (already wired)
- [ ] Per-user group: `user.{id}` for direct push
- [ ] Per-cohort group: `cohort.{id}`
- [ ] Per-branch group: `branch.{id}`
- [ ] Disconnect cleanup (remove from groups)
- [ ] Heartbeat / ping-pong every 30s
- [ ] Reconnect-with-backoff guidance for clients (document)

---

## 22. Celery / background jobs

- [ ] Periodic tasks via django-celery-beat (defined in admin or in code via `setup_periodic_tasks`):
  - [ ] `purge_expired_otps` daily
  - [ ] `mark_absent_after_lesson` every 15 min
  - [ ] `late_payment_reminders` daily
  - [ ] `nightly_aggregations` for cross-tenant analytics
  - [ ] `archive_completed_terms` weekly
  - [ ] `cleanup_old_audit_logs` weekly (per retention policy)
- [ ] Idempotency: every task that calls Eskiz/Click/Payme/Uzum/Anthropic must store an idempotency key on the source row
- [ ] Retry policy: exponential backoff, max 3 by default, tunable per task
- [ ] Dead-letter queue for tasks that exhaust retries
- [ ] Task duration metrics
- [ ] Worker autoscaling (defer; design)

---

## 23. Storage

- [ ] MinIO bucket creation in `seed_dev.py` (`mc mb local/starforge-media`)
- [ ] Bucket lifecycle: expire objects under `tmp/` after 7 days
- [ ] Signed upload flow: client requests `POST /api/v1/content/upload-url/` → uploads directly to S3 → confirms via callback
- [ ] Signed download URL endpoints with short TTLs
- [ ] Per-tenant bucket prefix: `{schema_name}/...` so a shared bucket still isolates data
- [ ] CORS config for direct browser uploads
- [ ] Content-type allowlist enforced on upload-url issuance
- [ ] File metadata extraction on upload-complete callback (libmagic)
- [ ] Image thumbnail generation (Pillow, async via Celery)
- [ ] Video transcoding (defer; pluggable)
- [ ] Storage quota per Center

---

## 24. Internationalization

- [ ] Mark every user-facing string with `gettext_lazy`
- [ ] `python manage.py makemessages -l uz -l en -l ru`
- [ ] Translate strings (uz first)
- [ ] Compile `.mo` files in CI
- [ ] SMS templates per language
- [ ] Email templates per language
- [ ] Locale switcher in user profile
- [ ] Locale auto-detect from `Accept-Language` (already via LocaleMiddleware)
- [ ] Number / date / currency formatting per locale

---

## 25. Security hardening

- [ ] CSRF tokens for cookie-based endpoints (admin only)
- [ ] CORS allowlist tightened in production (no `CORS_ALLOW_ALL_ORIGINS`)
- [ ] HSTS preload registration after launch
- [ ] Rate limit on auth endpoints (already done via DRF throttle classes)
- [ ] Rate limit on AI endpoints (token-bucket per Center)
- [ ] Brute-force lockout on `/admin/` login (django-axes or equivalent)
- [ ] CSP headers via django-csp
- [ ] X-Frame-Options DENY (already set)
- [ ] X-Content-Type-Options nosniff
- [ ] Secrets rotation runbook
- [ ] Field-level encryption for `national_id`, `medical_notes` (django-cryptography or pgcrypto)
- [ ] Audit log for every admin action
- [ ] Penetration testing scope document

---

## 26. Tests

- [x] **Tenant isolation invariant** — JWT in tenant A fails on tenant B (`tests/test_tenant_isolation.py`)
- [x] OTP request → verify happy path (MockEskiz outbox)
- [~] OTP throttle: 4th request in a minute returns 429 (throttles wired; explicit test deferred)
- [x] OTP wrong code rejected (5x cap now persists; explicit 5x test deferred)
- [x] Refresh token rotation: old refresh blacklisted after rotation
- [x] Refresh reuse detection: blacklisted refresh reused → all revoked
- [x] User can log in with phone OR email
- [x] Permission matrix: parameterized over (role, endpoint, verb) — 22 cases + fail-closed
- [~] Object-scoped permission: teacher branch A vs branch B (object_scope wired; explicit test D2)
- [x] Channels: anonymous WS connection rejected (4401)
- [~] Channels: authenticated WS receives "hello" (anonymous-reject done; authed test D4-C)
- [x] Celery task isolation: eager `purge_expired_otps` under schema_context
- [~] Migration: `migrate_schemas --shared` on fresh DB (`makemigrations --check` clean; live run pending owner DB)
- [~] Migration: creating a new Center auto-runs tenant migrations (covered by conftest provisioning; pending owner DB)
- [x] OpenAPI schema generation succeeds (CI job exists)
- [~] Coverage threshold ≥ 70% (config + CI gate wired; % UNMEASURED — owner runs `pytest --cov`)

**Note (Day 1):** all tests are written and collect cleanly (44), but the suite has NOT been
executed — Postgres was unavailable during the build. The owner must run `pytest` once the DB
is up to confirm green + the 70% floor.

---

## 27. Frontends (out of v1 scope, but tracked)

- [ ] React admin scaffold (Vite + TanStack Query + drf-spectacular-generated TS client)
- [ ] Flutter mobile scaffold (Dio + drf-spectacular-generated Dart client)
- [ ] Auth flow on both
- [ ] Tenant subdomain detection (web)
- [ ] Tenant header injection (mobile)

---

## 28. Branch print agent (separate repo, tracked here)

- [ ] Bootstrap a separate `starforge-print-agent` repo (Go preferred; Python if forced)
- [ ] Long-poll or WS connection back to server
- [ ] CUPS integration (`pkg.go.dev/github.com/OpenPrinting/goipp` or python-cups)
- [ ] Job claim → print → status update loop
- [ ] Auto-update mechanism (the agent is on a printer-room PC, not a server)
- [ ] Telemetry: which printer printed what, when, errors
- [ ] One-line installer (Linux/Windows)

---

## 29. Deployment (post-v1)

- [ ] Pick a hosting target (Hetzner / DO / AWS / on-prem)
- [ ] Managed Postgres setup with daily backups
- [ ] Managed Redis (or self-hosted with persistence)
- [ ] Object storage (S3 / Backblaze / MinIO cluster)
- [ ] Reverse proxy with wildcard TLS (Caddy or Traefik with cert-manager DNS-01)
- [ ] Container registry
- [ ] CI → CD pipeline (deploy on `main` push)
- [ ] Blue/green or rolling deploy strategy
- [ ] DB migration safety (check for backwards-compatible changes; block deploys that aren't)
- [ ] Observability: logs aggregation, metrics, traces
- [ ] Alerting on error rate, latency, queue depth
- [ ] Incident response runbook
- [ ] Disaster recovery: RPO/RTO defined, restore drill quarterly

---

## 30. Documentation

- [ ] Per-app README explaining its domain and key models
- [ ] API user guide (separate from the auto-generated OpenAPI)
- [ ] Architecture decision records (ADR) for the big choices already made:
  - [ ] ADR-001: schema-per-tenant via django-tenants
  - [ ] ADR-002: JWT-everywhere auth
  - [ ] ADR-003: separate students/parents/teachers apps
  - [ ] ADR-004: branch print agent in a separate repo
  - [ ] ADR-005: drop repository/dto/interfaces layers from `core/`
  - [ ] ADR-006: uz primary, en secondary, ru tertiary
- [ ] Onboarding doc for new backend devs
- [ ] Tenant provisioning runbook
- [ ] Eskiz / Click / Payme / Uzum integration runbooks (one each)

---

## Progress tracking

Mark items off as you ship. When an entire section is done, move it to a CHANGELOG entry and consider removing it here so the file stays scannable.

The single most load-bearing test in this whole list: **§26 first item — tenant isolation**. Write it before any feature work touches a tenant-scoped model.
