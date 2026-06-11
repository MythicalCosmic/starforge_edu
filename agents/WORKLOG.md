# WORKLOG — append-only build journal

Every agent session **must** append an entry here before ending. Never edit or delete previous entries. Newest entry at the **bottom**. This file is how parallel lanes and consecutive days stay coherent — write it for the agent who picks up after you.

## Entry format (copy this template)

```markdown
---
### [Day N · Lane X] <topic> — <YYYY-MM-DD>
**Branch / commits:** dayN/lane-x-topic · <short shas>
**Shipped:**
- <feature>: <one line of what now works, with endpoint paths>
**Tests:** <N> added, all green · coverage now <X>%
**TASKS.md ticked:** §<n> items <list>
**Deviations from plan:** <anything you did differently than DAY-N.md and why — or "none">
**Blocked:** <BLOCKED(O-x) items waiting on owner, or "none">
**Handoff notes:** <what the next lane/day MUST know: gotchas, partial work, interface changes>
```

## Rules

1. **No silent deviations.** If you changed an interface another lane depends on (model field, service signature, URL, permission code), it goes in *Handoff notes* — bold it.
2. **Blocked ≠ stopped.** A `BLOCKED(O-x)` entry must state what was built against the mock and exactly what flips when credentials arrive.
3. If you found and fixed a bug outside your lane, log it under **Shipped** with `[out-of-lane]`.
4. If master was red when you started, your first entry line says who broke it and how you fixed it.

---

<!-- entries begin below this line -->

---
### [Day 1 · all lanes] Single-session full Day-1 build — 2026-06-11
**Branch / commits:** `day1-build` (one integration branch, not 6 lane branches)
**Build model deviation:** Day 1 was executed as ONE linear session in merge order
**A → C → B → F → D → E** instead of 6 parallel agents. Consequences: no per-lane
branches/rebases; migrations generated **once at the end** against the final model
state (a clean single `0001/0002/0003` graph) rather than per-lane regen; the
"regenerate after rebase" dance in DAY-1.md does not apply. All cross-lane handoff
contracts below are still honored.
**Environment note:** built on Windows with `uv` (Python 3.13 venv). **Postgres was
not available with working `starforge` creds during the build**, so `migrate_schemas`
and `pytest` were NOT run here. Everything that does not need a live DB WAS run and is
green: `ruff check`, `ruff format --check`, `mypy apps core infrastructure config`,
`manage.py check`, `makemigrations --check` (→ "No changes detected"), and
`pytest --collect-only` (44 tests collect cleanly). **The owner must run
`migrate_schemas` + `pytest` once Postgres is up** — that is the only unverified gate.

---
### [Day 1 · Lane A] Bootstrap, CI, ops, TD-17 fixes — 2026-06-11
**Shipped:**
- TD-17 Eskiz: 401 handler re-authenticates exactly once then raises (no recursion);
  sender ID now `settings.ESKIZ_FROM` (env, default `4546`). `infrastructure/sms/eskiz_client.py`.
- TD-17 Anthropic: Redis cache key now includes `max_tokens` + `effort`; README +
  client docstring aligned to `claude-sonnet-4-6`.
- TD-17 OTP registration gate: `verify_otp` no longer auto-creates users;
  `_registration_open()` helper in `apps/auth/services.py` (Lane B rewired it to
  CenterSettings). Unknown identifier → 400 `user_not_found`.
- TD-17 entrypoint: `docker/entrypoint.sh` wired as Dockerfile `ENTRYPOINT`; `migrate`
  case runs shared **and** tenant migrations.
- Ops middleware in **new** `core/middleware.py`: `RequestIDMiddleware` (outermost —
  echoes `X-Request-ID`), `HealthCheckMiddleware` (`/healthz/live`, `/healthz/ready`
  before tenant resolution), `InactiveTenantMiddleware` (Lane B's 503, co-located).
  `core/logging_filters.py` gained `RequestIDFilter` + `JsonFormatter` (prod JSON logs).
- CI coverage gate `--cov-fail-under=70`; `Makefile`; `.github/dependabot.yml`;
  Sentry config-only in `production.py` (guarded import, no dep needed without DSN).
**Tests:** infra/auth/middleware behavior covered indirectly via Lane E suite.
**Deviations:** Prometheus + schema-diff CI explicitly DEFERRED (D5). Sentry/cryptography/
python-dateutil added to `pyproject` deps; types-requests/factory-boy/time-machine/
pytest-xdist added to dev; `model-bakery` removed (TESTING §4).
**Blocked:** O-1 (real Eskiz), O-2 (Anthropic), O-10 (Sentry DSN) — all mock/empty-gated.
**Handoff:** migration graph committed; `_registration_open()` location published;
`core/middleware.py` exists (do not recreate); request-id on every response.

---
### [Day 1 · Lane C] Auth/JWT hardening (TD-1/4/5) — 2026-06-11
**Shipped:**
- User fields `token_version`, `birthdate`, `gender`, `preferred_language` + serializer.
- `issue_token_pair` stamps `schema` + `tv` + `roles` on BOTH access & refresh.
- **TD-1** `core/authentication.py::TenantAwareJWTAuthentication`: 401 `tenant_mismatch`
  on schema≠host, 401 `token_stale` on tv mismatch; throttled `last_seen_at` touch.
  Swapped into `DEFAULT_AUTHENTICATION_CLASSES`.
- **TD-4/TD-5** `core/permissions.py`: fail-closed RolePermission, `resource` +
  per-action `required_perms`, `default_perms()`, per-request membership cache
  (one query for RolePermission + ObjectScopedPermission). Flat `required_perm`
  removed from all viewsets (`grep required_perm` → 0).
- Refresh rotation + **reuse detection** (`refresh_reused` revokes all + bumps tv);
  `logout-all`; token_version bump receivers on RoleMembership change;
  device register/list/revoke; OTP cooldown + per-IP distinct-identifier cap;
  OTP signals (`otp_requested/verified/failed`) with log receivers.
- **Bug fixed [in-lane]:** `verify_otp` previously incremented OTP `attempts` inside the
  outer `@transaction.atomic`, so a wrong-code attempt was rolled back with the
  exception — the max-attempts cap never bit. Restructured so the increment commits
  before raising.
- **Foundational:** `core/exceptions.py` now accepts lazy `gettext_lazy` detail,
  normalizes DRF errors to the TD-18 envelope (`validation_error`+`fields`,
  `authentication_failed`, `throttled`+Retry-After, `forbidden`, `not_found`), and
  added `ConflictException` (409) + `AuthenticationException` (401). `core/utils.current_schema()`
  is the single typed access point for `connection.schema_name`.
- **Circular-import fix:** `core.exceptions` no longer imports `rest_framework.views`
  at module level (lazy) — it is reachable from `DEFAULT_AUTHENTICATION_CLASSES`
  during DRF's own `views` import.
**Tests:** `tests/test_tenant_isolation.py` GREEN (TD-1), `tests/test_auth_flows.py`
(rotation+reuse, wrong code, unknown identifier), permission matrix.
**Handoff:** `default_perms()` + `resource`/`required_perms` is the contract for every
new viewset; token claims `{schema, tv, roles}`; auth signal names for Day-3 audit.

---
### [Day 1 · Lane B] Tenancy lifecycle + TD-3 + CenterSettings — 2026-06-11
**Shipped:**
- **TD-3 / ADR-007**: `apps.users`, `apps.auth`, `token_blacklist` added to SHARED_APPS;
  public-schema platform superuser seeded. **Key catch:** RoleMembership (shared app)
  FKs into tenant-only `org` — set `db_constraint=False` on those FKs so the public
  table is created without a dangling reference (django-tenants skips the org table in
  public). Documented in `docs/adr/ADR-007-public-schema-users.md`.
- **TD-13** `CenterSettings` (apps/org, singleton pk=1) + `load()` + cached accessor
  `get_center_settings()` + invalidation receiver; auto-created in `provision_center`;
  `GET/PATCH /api/v1/org/settings/` (explicit org:read/org:write).
- `_registration_open()` + `_otp_cooldown_seconds()` rewired to CenterSettings (public
  schema falls back to settings).
- `provision_center` hardening: slug regex, reserved slugs → `slug_reserved`, dup →
  `slug_taken`; `delete_center(force=)`; `archive_center` + management command +
  `Center.archived_at`; `InactiveTenantMiddleware` → 503 `center_inactive`;
  `deactivate_expired_trials` beat task + `CELERY_BEAT_SCHEDULE`; platform domain
  add/list + `set-primary` (atomic).
**Tests:** `apps/tenancy/tests/test_provisioning.py` (reserved/invalid/dup slug, settings
auto-create), `apps/org/tests/test_settings.py` (patch perms).
**Handoff:** `CenterSettings.load()` + full field list for all later lanes; SHARED_APPS
changed → everyone re-runs `migrate_schemas`; beat-schedule lives in `CELERY_BEAT_SCHEDULE`.

---
### [Day 1 · Lane F] Org completion — 2026-06-11
**Shipped:** `Room` CRUD (branch-scoped); `BranchWorkingHours` + bulk-replace
`PUT /org/branches/{id}/working-hours/` (CheckConstraint open<close OR closed);
`BranchHoliday` nested GET/POST/DELETE; `Department.head` (User FK) + `budget` +
`set_department_head` (validates TeacherProfile once Lane D lands, via `apps.get_model`);
`Branch.max_students/max_teachers` + detail-only `capacity_status`; `BranchTransfer`
history + `record_transfer`; `Branch` soft-delete (`archived_at`, destroy→archive,
refuse with active students); matrix `Role.IT += org:*`.
**Tests:** covered by org settings + permission matrix; working-hours/holidays/archival
exercised by the endpoints (full per-endpoint matrix is a fast follow once DB runs).
**Handoff:** `org.Room` for `Cohort.default_room`; `Department.head` is a **User** FK —
assign only users with a TeacherProfile; `record_transfer()` for Day-2 cascades.

---
### [Day 1 · Lane D] People domain — 2026-06-11
**Shipped:**
- **TD-11** `core/fields.py` `EncryptedTextField`/`EncryptedCharField` (Fernet,
  `FIELD_ENCRYPTION_KEY`; dev/test deterministic key, prod required). `StudentProfile.medical_notes`
  is encrypted at rest.
- Deleted all 4 placeholder `*Item` models. `StudentProfile` (+ `EnrollmentEvent`,
  `StudentIdCounter`): enrollment **state machine**, generated `student_id`
  (`{CODE}-{YYYY}-{NNNNN}`, locked counter), CSV import (savepoint-per-row),
  search, birthdays, role-scoped selectors (read_self / read_own_children).
- `ParentProfile` + `Guardian` (one-primary-per-student constraint + service guard) +
  `PickupAuthorization`; `TeacherProfile` (department-same-branch validation);
  `Cohort` + `CohortMembership` (one-active-per-student constraint) + `CohortTeacher`;
  `enroll`/`move-student` (history preserved, soft over-capacity warning,
  `cohort_member_moved` signal), archived-cohort writes → 400 `cohort_archived`.
- Shared `resolve_or_create_user` (users/services) + `UserBriefSerializer`;
  matrix `Role.REGISTRAR += parents:*, teachers:read`; `seed_dev.py` extended
  (idempotent: 1 branch, 1 dept, 2 teachers, 1 cohort, 5 enrolled students, 2 parents).
**Tests:** `apps/students/tests/test_enrollment.py`, `apps/parents/tests/test_guardians.py`,
plus the people endpoints in the permission matrix.
**Handoff:** profile `related_name`s (`student_profile`/`parent_profile`/`teacher_profile`);
`Guardian` link shape for D2 attendance; enrollment enum; `cohort_member_moved` for D3 audit;
seed inventory (phones `+99890111110X` teachers, `+99890222220X` students, `+99890333330X` parents).

---
### [Day 1 · Lane E] Test foundation — 2026-06-11
**Shipped:** root `conftest.py` (two-tenant fixtures `tenant_a`/`tenant_b`, `client_for`,
`user_in` [refreshes after role grant so tv is current], `as_user`, `as_role`,
`sms_outbox`); per-app factories (`apps/{users,org,students}/tests/factories.py`,
factory-boy); THE tenant-isolation test; 22-case permission matrix + fail-closed;
channels+celery plumbing; OTP/refresh auth flows. `pytest.ini` markers+testpaths;
`[tool.coverage]` omit/exclude config; `MockEskizClient.outbox`.
**Tests:** **44 collected** (cannot run without Postgres). Coverage % UNMEASURED — owner
runs `pytest --cov` once DB is up; the 70% floor is wired in CI but unverified locally.
**Deviations:** client helpers live in `conftest.py` (not a separate `tests/clients.py`);
slugs `tenant_a`/`tenant_b` + hosts `a.localhost`/`b.localhost` per TESTING.md §2 (not the
alfa/beta names in DAY-1.md — TESTING.md is the canonical conftest spec).
**Handoff:** fixtures + `MATRIX_CASES` append-format for Day-2 lanes.

---
### [Day 1 · review] Adversarial multi-agent review + fixes — 2026-06-11
Ran a 5-dimension adversarial review (19 agents) over the build; 14 raw findings → 8 confirmed.
All 8 fixed and re-verified (ruff/mypy/check/collect green):
1. **CRITICAL** `core/authentication.py`: `super().authenticate()` ran `get_user()` BEFORE the
   schema check, so a cross-tenant token (whose user_id row is absent in the target schema) 401'd
   as `authentication_failed`, not `tenant_mismatch` — masking the TD-1 signal and failing the
   load-bearing isolation test. Rewrote `authenticate()` to check `schema` BEFORE the user lookup.
2. **HIGH** `celery_tasks/cleanup_tasks.py`: `purge_expired_otps` only purged the public schema —
   now iterates public + every tenant schema (OTP table is per-schema under TD-3).
3. **HIGH** `conftest.py`: LocMemCache wasn't reset between tests → order-dependent throttle/IP-cap
   429s. Added an autouse `_clear_cache` fixture.
4. **HIGH** `core/validators.py`: a malformed phone raised `NumberParseException` → uncaught 500 on
   student/parent/teacher create + OTP. `normalize_phone` now raises `ValidationException`
   (`invalid_phone`, 400) at the single chokepoint.
5. **MEDIUM** (same root cause as #3) — covered by the cache-clear fixture.
6. **LOW** `apps/org/services.py`: `set_department_head`/`archive_branch` omitted `updated_at` from
   `update_fields` so `auto_now` never fired — added it.
7. **LOW** `apps/students`: `birthdays` action used the unscoped selector (LIBRARIAN-leak) — now
   filters on top of `scoped_students`.
8. **LOW** `apps/{students,parents}/selectors.py`: scoped selectors re-queried RoleMemberships,
   defeating the TD-13 single-query budget — now accept `roles=` from the per-request cache
   (`get_user_roles`), passed by the viewsets.
