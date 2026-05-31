# starforge_edu — 5-day plan to a production-ready Starter tier

**Decided 2026-06-01.** Target: ship the **Starter tier** (per `FEATURES.md`), hardened
and deployable, in 5 focused days. A **real first customer is waiting**, so the bias is
reliability → data safety → the flows they touch daily, over breadth or demo polish.

Pro/Premium scope (finance, payments, academics, AI, printing, cross-tenant analytics)
is explicitly **post-v1** and not touched this week.

## Starter scope (the only features we build)
Reception (Student/Parent/Teacher profiles + Guardian links) · Cohorts (membership +
primary/co-teacher) · Schedule (recurring lessons + room/teacher/cohort conflict
detection) · Attendance (mark + term summary) · Notifications (in-app + email only) ·
Basic reports (enrollment list, attendance summary, cohort roster) · Audit (1yr) ·
Tenant isolation · i18n (uz/en/ru) · Admin + OpenAPI.

## Guiding rules
1. **Tenant isolation test is written before any tenant-scoped feature.** A schema leak
   is a company-ending bug. (`TASKS.md` §26 item 1.)
2. Every new ViewSet ships with: serializer, filter, `required_perm`, and a test.
3. Commit the migration graph as one reviewed commit before building on it.
4. Each day ends green: `ruff`, `mypy`, `pytest --cov`, `manage.py check`, schema gen.

---

## Day 1 — Foundation lockdown + the load-bearing tests
Goal: prove the platform is correct and isolated before adding features.
- Bring up `postgres/redis/minio`; run the full `TASKS.md §0` bootstrap checklist end-to-end.
- `makemigrations`, inspect, **commit the initial migration graph** (`users/tenancy/org` especially).
- `migrate_schemas --shared`; `seed_dev.py`; verify admin login, Swagger, OTP request→verify→`/users/me/`.
- **Write tests FIRST:** tenant isolation (JWT from tenant A rejected on tenant B), OTP
  happy path (MockEskiz), OTP throttle 429, OTP wrong-code lockout, JWT refresh rotation
  + reuse detection, phone-OR-email login.
- Wire `pytest --cov --cov-fail-under=70`; get all 4 CI jobs green with real tests.

## Day 2 — Reception domain (the heart of Starter) + Audit
- Replace placeholders with real models: `StudentProfile`, `ParentProfile`,
  `Guardian` (parent→student, relationship, primary flag), `TeacherProfile`, `org.Room`.
- Student ID generation (`DEMO-2026-00042`), enrollment state, name/phone/ID search.
- Parent→child visibility scoping; CRUD ViewSets + serializers + filters + perms + tests.
- **Audit app:** real `AuditLog` model (append-only) + signal recorder on sensitive models
  (User, RoleMembership, Guardian) + `audit_log()` helper for login/logout/OTP.

## Day 3 — Cohorts + Schedule
- `Cohort` (branch/department/level/dates/capacity/primary_teacher) + membership + co-teachers.
- Schedule: `Lesson`, `TimeSlot`, `Room`, `Holiday`; recurring lessons (RRULE-style).
- **Conflict detection** (room, teacher, cohort) — the highest-risk algorithmic code; test hard.
- One-off occurrence cancel/move; Asia/Tashkent holiday seed.

## Day 4 — Attendance + Notifications + Reports + i18n
- `AttendanceRecord` (present/absent/late/excused); mark endpoint (teacher), bulk-by-cohort,
  term summary %.
- Notifications: `Notification`/`NotificationTemplate`/`NotificationPreference`; central
  `dispatch(event)` (in-app + email channels only for Starter), idempotency, quiet hours.
- Celery beat: `purge_expired_otps` (daily), `mark_absent_after_lesson`, absence→guardian notify.
- Reports: enrollment list, attendance summary, cohort roster (sync now, Celery+S3 later).
- i18n: wrap user-facing strings in `gettext_lazy`; `makemessages` uz/en/ru.

## Day 5 — Hardening + ship
- Observability: Sentry (config), `/healthz/live` + `/healthz/ready` (DB+Redis), request-ID
  middleware, JSON logs in prod.
- Security: tighten CORS in prod, `django-axes` admin lockout, restrict apex `/admin/` to
  platform staff, X-Content-Type-Options nosniff. (Field encryption documented, deferred.)
- Permissions: wire `required_perm` on every new ViewSet; parameterized (role,resource,verb) test.
- Deploy: finalize prod Dockerfile/compose, Caddy/Traefik **wildcard TLS** for `*.starforge.uz`,
  managed Postgres daily backups, migrate-on-deploy, tenant-provisioning + secret-rotation runbooks.
- Final E2E smoke against a fresh tenant. Tag `v1.0.0-starter`.

---

## Explicitly deferred (post-v1, tracked in TASKS.md)
Finance/invoicing/cashier · Click/Payme/Uzum payments · Academics/exams/transcripts ·
Assignments · Content library uploads · AI suite · Branch printing · SMS notifications ·
Mobile push · Realtime WebSocket consumers · Cross-tenant analytics · Field-level encryption.

## Top risks
- **Tenant isolation** — mitigated by writing the test first (Day 1).
- **Schedule conflict detection** — subtle; budget real test time (Day 3).
- **Migration graph churn** once real models land — commit early, then only forward migrations.
- **Scope creep** — the customer will ask for finance/payments. Hold the Starter line; quote post-v1.
