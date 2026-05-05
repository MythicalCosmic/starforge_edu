# starforge_edu — backend tasks (exhaustive)

Every feature, every detail, in dependency order. Check items off as you ship them.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 0. Bootstrap (do first thing next session)

- [ ] `docker compose -f docker/docker-compose.yml up -d postgres redis minio`
- [ ] Wait for `pg_isready` and `redis-cli ping` to succeed
- [ ] Create the `starforge` database if absent (`docker compose exec postgres psql -U starforge -c '\l'`)
- [ ] `uv run python manage.py makemigrations` — generate real `0001_initial.py` per app
- [ ] Inspect each generated migration before committing (especially `users`, `tenancy`, `org`)
- [ ] Commit migrations as a single commit: `chore(migrations): initial migration graph for v1 apps`
- [ ] `uv run python manage.py migrate_schemas --shared` — public schema
- [ ] `uv run python scripts/seed_dev.py` — creates Center `demo` at `demo.localhost` + superuser `+998901234567` / `starforge-dev`
- [ ] Verify `http://demo.localhost:8000/admin/` loads and login works
- [ ] Verify `http://demo.localhost:8000/api/schema/swagger-ui/` renders
- [ ] Hit `POST http://demo.localhost:8000/api/v1/auth/otp/request/ {"identifier":"+998901234567"}` and check stdout for the mock OTP
- [ ] Hit `POST /api/v1/auth/otp/verify/` with the OTP, get `{access, refresh}` back
- [ ] Hit `GET /api/v1/users/me/` with `Authorization: Bearer <access>`, get 200
- [ ] Verify tenant isolation: token from `demo` must NOT work against another tenant's hostname

---

## 1. Tooling, CI, infra polish

- [ ] Pre-commit: `uv run pre-commit install` to wire local hooks
- [ ] CI: push to GitHub, confirm `.github/workflows/ci.yml` runs lint + typecheck + test + schema jobs green
- [ ] Add `coverage` reporting to the test job (`pytest --cov=apps --cov=core --cov-fail-under=70`)
- [ ] Add a `dependabot.yml` for weekly Python + GitHub Actions updates
- [ ] Add a CODEOWNERS file once the team is more than one person
- [ ] Add a `Makefile` (or `justfile`) with shortcuts: `make up`, `make migrate`, `make test`, `make schema`, `make lint`
- [ ] Configure ruff to fail on warnings in CI (already does — verify)
- [ ] Configure mypy to actually run cleanly (currently lenient; tighten as types are added)
- [ ] Wire `drf-spectacular` schema diff in CI — fail PR if schema changed without updating clients
- [ ] Add Sentry or equivalent error tracking (config-only; defer real DSN)
- [ ] Add structured JSON logging for prod settings (currently human-readable)
- [ ] Add request ID middleware (`X-Request-ID` echoed back, surfaced in logs)
- [ ] Add health check endpoints: `/healthz/live` (process up), `/healthz/ready` (DB + Redis reachable)
- [ ] Add Prometheus metrics endpoint (django-prometheus) — defer scraping setup
- [ ] Document runbook for rotating SECRET_KEY and ESKIZ credentials

---

## 2. Tenancy (apps/tenancy + apps/org)

### Center lifecycle

- [ ] `provision_center` service: validate slug is Postgres-safe (alphanum + underscore, ≤63 chars)
- [ ] Reject duplicate slug with a clear error (currently raises IntegrityError)
- [ ] Reject reserved slugs: `public`, `admin`, `www`, `api`, `static`, `media`
- [ ] On Center delete, refuse if tenant has > 0 users (require explicit `--force` flag)
- [ ] Center deactivation flow: set `is_active=False`, all subsequent requests for that hostname return 503
- [ ] Trial expiration: scheduled task that flips `is_active=False` when `trial_ends_at < now()`
- [ ] Center "soft delete" with archival schema rename (`acme` → `_archived_acme_20260601`)

### Domain management

- [ ] Multiple domains per Center (already supported via DomainMixin) — add UI to set primary
- [ ] Domain ownership verification: TXT record check before activating a custom domain
- [ ] Wildcard fallback: `*.starforge.uz` resolves to apex with marketing site

### Branch / Department

- [ ] Branch schema: working hours, holidays, room list
- [ ] Department: budget, head-of-department FK
- [ ] Branch ↔ Department ↔ User membership table (already drafted as `RoleMembership`)
- [ ] Move/transfer student between branches: cascade attendance, schedule, finance correctly
- [ ] Soft-delete a Branch: refuse if it has active students; allow if archived

### Public-schema admin

- [ ] Restrict `/admin/` on apex domain to platform staff only
- [ ] Tenant impersonation tool: platform admin opens a tenant in a one-click read-only session
- [ ] Tenant usage dashboard (DAU, storage, AI tokens) per Center on apex admin

---

## 3. Users + Auth (apps/users + apps/auth)

### User model

- [ ] Add `avatar` ImageField (S3-backed via django-storages)
- [ ] Add `birthdate`, `gender`, `national_id` (passport / Uzbek ID — encrypted at rest)
- [ ] Add `address` (separate model: country/region/city/street/postal)
- [ ] Add `preferred_language` (one of uz/en/ru) — defaults from request locale
- [ ] Add `notification_preferences` per channel × event type (move to `apps.notifications`)
- [ ] Validate phone in E.164 (already wired in `core.validators.normalize_phone`)
- [ ] Validate email uniqueness case-insensitively
- [ ] Allow either phone OR email login but require BOTH for high-risk operations (TBD which)
- [ ] User merge tool: combine two users with the same person behind them (admin-only)
- [ ] User deactivation vs deletion (GDPR-style erasure with audit retention)

### OTP

- [ ] OTP code length is currently 6 — make it configurable per channel (SMS=6, email=8?)
- [ ] OTP cooldown: if last OTP for this identifier was sent < 60s ago, return 429
- [ ] OTP attempt limit: 5 wrong codes → invalidate the OTP, force a new request
- [ ] OTP audit log: who requested, who verified, IP, user agent, timestamp
- [ ] Detect OTP enumeration (same IP requesting OTPs for many identifiers) — global throttle exists; add per-IP-per-window distinct-identifier cap
- [ ] OTP via WhatsApp (cheaper than SMS in UZ) — separate channel
- [ ] OTP voice call fallback (Eskiz supports this)
- [ ] OTP for email needs a different template (HTML + plaintext)
- [ ] OTP cleanup: scheduled `purge_expired_otps` Celery task (already wired) — verify it runs daily

### JWT

- [ ] Issue JWT with extra claims: `tenant_schema`, `roles[]` (denormalized at issue time)
- [ ] Token versioning: bump `token_version` on User to invalidate all live tokens (e.g. password change)
- [ ] Refresh token reuse detection: if a blacklisted refresh is presented again, revoke ALL of that user's refreshes (signal of theft)
- [ ] Device-bound refresh: include device_id claim, validate against active Device on refresh
- [ ] Logout-everywhere endpoint: blacklist all of the user's refreshes
- [ ] JWT revocation list cleanup: scheduled task to drop blacklisted refreshes after expiry

### Devices

- [ ] Device registration on login (auto-create from User-Agent + a client-supplied device_id)
- [ ] Device list endpoint: `GET /api/v1/users/devices/`
- [ ] Device revocation: `DELETE /api/v1/users/devices/{id}/`
- [ ] Push token registration per device (FCM/APNs)
- [ ] Detect impossible travel: device A at IP from Tashkent, device B same user from another country within 5 min → flag for review

### Sessions / admin

- [ ] Force re-login when password changes
- [ ] Force re-login when role membership changes
- [ ] "Last seen at" updated on every authenticated request (already on User model — wire signal)
- [ ] "Login from new device" notification (push + email)

### Permissions

- [ ] Wire ROLE_PERMISSION_MATRIX into every ViewSet (currently most apps have placeholder `required_perm`)
- [ ] Object-level scoping: every ViewSet that returns tenant data sets `object_scope` if branch/department-scoped
- [ ] Permission cache: memoize `_user_roles(user)` per request to avoid N queries
- [ ] Add `RoleMembership` admin UI with bulk grant / bulk revoke
- [ ] Audit every permission grant (signal-driven, lands in `apps.audit`)
- [ ] Permission test matrix: parameterized pytest covering every (role, resource, verb) combo

---

## 4. Org structure (apps/org)

- [ ] Branch CRUD with permission gates (only director / IT)
- [ ] Department CRUD scoped to a Branch
- [ ] Branch operating hours by weekday
- [ ] Branch holidays (per-branch override on top of national holidays)
- [ ] Department head assignment (FK to User, validates user has a TeacherProfile)
- [ ] Department budget vs spent rollup (read-side, computed from `apps.finance`)
- [ ] Branch transfer history (audit trail when a student moves)
- [ ] Branch capacity tracking (max students, max teachers — soft caps)
- [ ] Room model under Branch: name, capacity, equipment, availability windows

---

## 5. Students (apps/students)

- [ ] Replace placeholder `StudentItem` with real `StudentProfile(OneToOne→User)`
- [ ] Fields: enrollment_date, academic_level, current_cohort (FK to cohorts), guardian links, medical_notes (encrypted), emergency_contacts (JSON)
- [ ] Student photo (S3 via django-storages)
- [ ] Student ID generation (auto, per-Center pattern — e.g. `DEMO-2026-00042`)
- [ ] Enrollment workflow: lead → application → accepted → enrolled → active → graduated/withdrawn (state machine)
- [ ] Drop / re-enroll history with reason codes
- [ ] Bulk import from CSV/Excel (pandas + transaction)
- [ ] Student dashboard endpoint: aggregated grades + attendance + assignments + finance
- [ ] Birthday list endpoint (filter by branch/cohort)
- [ ] Student search with full-text on name + phone + ID

---

## 6. Parents (apps/parents)

- [ ] Replace placeholder with real `ParentProfile(OneToOne→User)`
- [ ] `Guardian` link model: parent → student, with relationship type (mother, father, grandparent, legal_guardian)
- [ ] Primary guardian flag (one per student)
- [ ] Custody / visitation rules (text field, surfaced to school staff)
- [ ] Multiple students per parent (siblings) — list endpoint
- [ ] Parent → student visibility scope: parent only sees data for linked students
- [ ] Parent app endpoints: dashboard per linked student
- [ ] Pickup authorization list: who can pick up the child at the gate (separate from Guardian)
- [ ] Parent satisfaction survey (defer; outline only)

---

## 7. Teachers (apps/teachers)

- [ ] Replace placeholder with real `TeacherProfile(OneToOne→User)`
- [ ] Fields: hire_date, subjects[], qualifications, hourly_rate (or salary), department FK
- [ ] Teacher availability calendar (weekly windows)
- [ ] Substitute teacher pool
- [ ] Teacher load report: hours/week, classes count, students count
- [ ] Performance reviews (lifecycle: draft → submitted → acknowledged)
- [ ] Teacher payroll inputs (push to `apps.finance` once that's wired)

---

## 8. Cohorts (apps/cohorts) — class groups

- [ ] Replace placeholder with real `Cohort` model
- [ ] Fields: name, branch FK, department FK, level, start_date, end_date, capacity, primary_teacher FK
- [ ] Cohort membership: students in this cohort with start/end dates
- [ ] Co-teacher assignments
- [ ] Cohort rooms (a cohort can have a default room)
- [ ] Move student between cohorts mid-term (with audit)
- [ ] Cohort archive at end of term (read-only, retained for transcripts)
- [ ] Cohort messaging: bulk send to all parents/students in a cohort (via notifications)

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

- [ ] **Tenant isolation invariant** — JWT issued in tenant A must fail on tenant B (write FIRST)
- [ ] OTP request → verify happy path (with MockEskiz)
- [ ] OTP throttle: 4th request in a minute returns 429
- [ ] OTP wrong code 5 times invalidates the OTP
- [ ] Refresh token rotation: old refresh blacklisted after rotation
- [ ] Refresh reuse detection: blacklisted refresh reused → all refreshes for that user revoked
- [ ] User can log in with phone OR email
- [ ] Permission matrix: parameterized over (role, resource, verb) ⇒ allow/deny
- [ ] Object-scoped permission: teacher in branch A cannot grade student in branch B
- [ ] Channels: anonymous WS connection rejected
- [ ] Channels: authenticated WS receives "hello"
- [ ] Celery task isolation: task scheduled in tenant A actually runs under tenant A's schema
- [ ] Migration: `migrate_schemas --shared` succeeds on a fresh DB
- [ ] Migration: creating a new Center auto-runs all tenant migrations
- [ ] OpenAPI schema generation succeeds (already a CI job)
- [ ] Coverage threshold ≥ 70%

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
