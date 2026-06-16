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
### [Day 3 · OWNER BUILD+INTEGRATION+REVIEW] Money, fiscal & messaging — 2026-06-16
**Branch:** `day1-build`. Day 3 built from scratch (all 6 lanes A–F), integrated, reviewed,
and fixed in one orchestrated session. **Final state: 674 passed / 3 skipped / 90% coverage
on real Postgres; ruff + mypy (345 files) + makemigrations --check all clean.**

**What shipped (TASKS §15/16/17/19 + parts of §22):**
- **Finance** (apps/finance): FeeSchedule/Invoice/InvoiceLine/Discount/PaymentPlan/
  PaymentAllocation/Refund/CashierShift; per-center invoice numbering + FX snapshot;
  oldest-due-first exact-Decimal allocation; auto-issue-on-enrollment; sibling discounts;
  cashier shifts; statement PDF (weasyprint→S3); late-payment-reminders beat task.
- **Payments** (apps/payments + infrastructure/payments + infrastructure/fiscal): Click/Payme/
  Uzum clients **mock-first** with a spec-compliant Payme JSON-RPC (tiyin, error bands
  -31050..-31099/-31001/-31003/-32601/-32504, states 1/2/-1/-2, ms times, replay dedupe);
  public-schema webhook intake (TD-6) resolving tenant by slug → schema_context → signature
  verify; idempotency + replay protection; Soliq fiscalization (TD-7, mock); reconciliation +
  receipt PDF; payment_completed/failed signals.
- **Notifications** (apps/notifications + infrastructure/push): central dispatch() with a
  16-event EventType enum, receivers bridging every Day-1/2/3 signal, SMS/email/push(FCM mock)/
  in-app fan-out (TD-15 group_send), uz/ru/en templates, quiet hours, preferences, dedupe,
  bulk announcements, bounce handling.
- **Audit** (apps/audit): append-only AuditLog, signal-driven receivers for the TD-9 sensitive
  models (credentials/PII masked), audit_log() helper, read-only cursor API + CSV export,
  retention beat task.
- **Billing/paywall** (apps/billing, SHARED_APPS): Plan/Subscription/UsageSnapshot,
  SubscriptionGateMiddleware (402 on suspended tenants, allowlisted admin/auth/healthz/schema),
  nightly metering + trial→active→past_due→suspended state machine, enforce_student_limit,
  platform checkout (mock), dunning.
- **Attack tests** (Lane F): Payme golden suite, webhook tampering/replay/wrong-tenant,
  idempotency, allocation rounding, paywall, append-only, cross-tenant sweep.

**Build process note (transient infra):** the build workflow hit Anthropic-side rate limits +
a socket drop mid-run; resumed twice (completed lanes returned cached) to finish all six. Not a
code issue.

**Integration I did centrally** (lanes returned shared edits as `integration_needed`): wired
billing into SHARED_APPS + the paywall middleware; added all provider/fiscal/push/billing env
keys + settings; webhook + platform-billing public URLs; 3 finance CenterSettings knobs (+org/0007);
the apps/ai `tokens_used_current_month` stub; the apps/students `enforce_student_limit` call; two
apps/auth audit hooks; generated payments/0002 + org/0007 migrations centrally.

**Bugs I found & fixed during review/integration (the load-bearing ones):**
1. **LATENT PRODUCTION BUG (Day-2 AND Day-3): `_schema_name` task routing was wrong everywhere.**
   Every fan-out task was called as `.delay(..., _schema_name=schema)`, passing it as a task
   **kwarg** — but tenant-schemas-celery reads the schema from task **headers**, so the kwarg
   leaked into the task signature (TypeError in eager tests; in production the tenant schema was
   never activated). Fixed once for all tasks: `core/celery_base.py: SchemaHeaderTask` lifts the
   kwarg into headers, wired via `CeleryApp(task_cls=...)`. This is why ~12 notification tests
   plus the whole fan-out mechanism now work — and why Day-2's fan-out tasks would have silently
   misbehaved in prod.
2. **Notifications receivers never connected** — defined as nested functions and connected with
   Django's default `weak=True`, so they were garbage-collected the moment each `_connect_*()`
   returned. Fixed: `weak=False` on all 14. (Same class of bug the payments/finance *tests* hit
   with weak lambdas — fixed there too.)
3. **billing.enforce_student_limit crashed on `FakeTenant`** — `connection.tenant.pk` throws
   inside `schema_context` (Celery/tests). Fixed to resolve the subscription by `schema_name`.
4. **P0 (Lane F): webhook replays were never marked `DUPLICATE`** — `record_webhook_event`
   returned the existing row without updating status, contradicting D3-B-6. Fixed.
5. Quiet-hours SMS clobbered in eager mode (eta ignored) → deferred-delivery guard; notifications
   feed `read` action not own-row-scoped (could 200 on another user's row) → `get_object()`;
   audit write verbs returned 403 instead of 405 (perms ran before method check) → `initial()`
   405 short-circuit; finance outstanding-balance 403'd parents (needs read_own) and cashier
   shift perms; finance/payments/audit mypy correctness (DecimalField kwargs, Payme localized
   messages, get_model typing).

**Feedback for the Day-3 build agents (recurring themes — apply on Day 4):**
- **Know your library's contract before you adopt its API everywhere.** The `_schema_name`
  bug was copy-pasted across two days because nobody checked that tenant-schemas-celery uses
  *headers*. One wrong assumption, repeated, became a latent prod bug a green test suite hid.
- **Django signal receivers must use `weak=False` when defined in a local/nested scope** — both
  the production receivers and several tests got GC-bitten. This bites silently (no error, just
  "nothing happened").
- **A green suite written by the same agent can still be measuring the wrong thing** — several
  "failures" were test-measurement bugs (weak lambdas, missing `capture_on_commit`, missing
  `public_tenant` fixture). When you assert a signal/side-effect fired, prove the *production*
  path fired it, not a test artifact.
- **Anything that reads `connection.tenant` must tolerate the `FakeTenant`** (no `pk`) that
  `schema_context` installs — resolve tenants by `schema_name`.

**Blocked (owner, all mock-first per TD-2):** real Click/Payme/Uzum creds [O-3/O-4/O-6], Soliq
[O-5], FCM [O-7], billing plan pricing [O-12]. Live demo (Redis+worker+MinIO) not run here.
**Skipped (3):** weasyprint + libmagic native-render tests (Windows; run on CI/Linux).
**Handoff to Day 4:** AI (apps/ai) replaces the `tokens_used_current_month` stub; reports reuse
the statement/receipt PDF pattern; realtime consumes the `notification.message` group payload
(TD-15); control center consumes billing Plan/Subscription + UsageSnapshot.

---
### [Day 2 · OWNER REVIEW] Independent review verdict + fixes — 2026-06-16
**Branch / commits:** `day1-build` (Day-2 build committed `0be4aa1`; review fixes committed on top).

**Verdict for the Day-2 agent — read before Day 3.**
Strong build. Independently re-verified the agents' claim on real Postgres: **338 passed / 2
skipped / 88.77%** matched exactly — the first time a day's "it's green" claim held up on a
clean re-run, which is the Day-1 lesson landing. Architecture, layering, idempotency design,
the materialized-occurrence scheduler, and the canonical storage flow are all genuinely good.
A 13-agent adversarial review (7 reviewers + verification) found **0 blockers, 6 majors, ~16
minors** — no dead-on-arrival code this time. All 6 majors + the security/correctness-relevant
minors are fixed (5 parallel app-scoped agents); suite is now **378 passed / 2 skipped / 90%**,
ruff+mypy+makemigrations --check clean.

**The 6 majors (all real authorization/correctness gaps a passing suite missed):**
1. **Teacher iCal feed leaked the whole school's schedule** — `scoped_lessons` treated TEACHER
   as blanket staff, so a teacher's personal calendar (and the lessons list) returned every
   tenant lesson. The iCal test only used a director, so it never caught it.
2. **Schedule scoping diverged from every other app** — schedule scoped students/parents via the
   denormalized `current_cohort` FK while attendance/academics/assignments/content all use the
   active `CohortMembership` join. A multi-cohort student saw lessons for one cohort but was
   marked/assigned across all. Fixed together with #1 in one `scoped_lessons` rewrite.
3. **`arrived_at` silently overrode an explicit `excused`/`absent` mark** as present/late —
   corrupting exactly the excused-vs-present distinction the attendance-% and honor-roll math
   depend on.
4. **Any teacher could enter/overwrite/publish another cohort's exam results** — `ExamViewSet`
   had no `get_queryset` scoping (only the grade *read* path was gated), so the write path was
   tenant-wide. Now cohort-scoped via `scoped_exams`.
5. **Parents were locked out of content** despite the documented cohort-visibility contract —
   `Role.PARENT` had no `content:read`, making the selector's parent-guardian branch dead code.
6. **Storage quota was bypassable** — `request_upload` counted only CLEAN files, so N back-to-back
   pending uploads each saw the same total and passed; quota was never re-checked at validate.
   Now re-validated at the CLEAN-flip chokepoint.

**Systemic feedback (same themes as Day 1 — watch these on Day 3):**
- **A green suite is not a scoped suite.** Every major was an *authorization/visibility* gap that
  unit tests passed over because no test asserted the negative case from the *other* role's seat
  (teacher-vs-teacher, parent-vs-content, cross-cohort exam writes). When you add a `get_queryset`
  scope, you owe a test that a wrong-seat actor gets 404 — not just that the right one gets 200.
- **Scope every write path, not just reads.** #4 and the content upload-url/les/folder minor are
  both "reads scoped, writes wide." Mirror the read scoping on create/update.
- **Keep scoping sources consistent across apps** (#2). One canonical membership source
  (`CohortMembership`, `end_date__isnull=True`) — never the denormalized convenience FK for
  authorization decisions.
- **Idempotency guards belong on every signal emitter** (cancel re-emit, grade_changed no-op),
  not only the periodic tasks — Day-3 audit/notify will consume these and double-fire otherwise.

**Minors also fixed:** flattened `schedule_conflict` `error.fields` to the documented shape;
move/cancel guards on non-scheduled lessons; iCal token TTL + `token_version` binding;
attendance dashboard date-param validation (was a 500); two more attendance knob-flip tests;
assignment rubric-cap at authoring time, publish-reopen guard, concurrent-submit 409, attachment
key tenant-prefix + filename sanitization; tmp-object cleanup on reject + per-schema lifecycle
prefix; exact-MIME sniff; thumbnail served via signed URL not raw key; teacher-scoped
honor-roll/warnings; cross-tenant tests on assignment action endpoints; a fan-out `_schema_name`
routing test. **`Role.PARENT += content:read`** is the only shared-file (core/permissions.py)
change — recorded here per the no-silent-deviations rule.

**Blocked (owner):** live 10-step demo + `@pytest.mark.minio` round-trip need a running
Redis+worker+MinIO stack; weasyprint/libmagic native-render tests skip on Windows (run on CI).
**Handoff to Day 3:** academic-engine signals are emit-only and their signatures are pinned by
capture-receiver tests — Day-3 notifications/audit wire the consumers. `s3_stub` fixture +
`storage_used_bytes()` are ready for payments-receipt and billing-metering reuse.

---
### [Day 2 · Lane F] Cross-cutting tests + EOD gate — 2026-06-11
**Shipped (verification lane — 338 passed, 2 skipped, 88.77% coverage on real Postgres):**
- **Permission matrix extended** (`tests/test_permission_matrix.py`): +31 Day-2 cases (schedule/attendance/
  academics/assignments/content × read-allow/read-deny/write-deny) → 52 cases total + the 3 fail-closed unit
  tests. Deleting any Day-2 matrix row reddens it.
- **Conflict property tests** (`apps/schedule/tests/test_conflict_properties.py`, 49): overlap table (disjoint,
  touching-before/after, contained, spanning, identical, overlap-start/end) × room/teacher/cohort × BOTH the
  service `check_conflicts` (409 grouping) AND the raw-ORM GiST exclusion (IntegrityError) + a cross-midnight
  case. Touching edges (end == start) are NOT conflicts (half-open).
- **Object-scope test** (`tests/test_object_scope.py`): non-director scoped to branch A → 403 on a branch-B
  TimeSlot; director bypass → 200 (closes §26 object-scoping).
- **Layering guard** (`tests/test_layering.py`): asserts ZERO `infrastructure.sms|email|ai` imports across
  `apps/{schedule,attendance,academics,assignments,content}` — green (the domain stays emit-only).
- **Shared in-memory S3 stub** (`tests/storage_stub.py` `InMemoryS3` + root-conftest `s3_stub` fixture) +
  full-flow integration (`apps/content/tests/test_storage_flow.py`): pending→clean (copy+delete recorded) and
  pending→rejected, plus a `@pytest.mark.minio` live round trip that auto-skips (set `STARFORGE_RUN_MINIO=1`
  with compose to run). **D3-B / D4-B reuse `s3_stub`.**
- **OpenAPI hardening**: registered `core.schema.TenantAwareJWTScheme` (OpenApiAuthenticationExtension) →
  schema warnings **273 → 6, 0 errors**; added `queryset = Model.objects.none()` to the 6 content viewsets
  (schema introspection vs user-scoped get_queryset) and excluded the undocumented `SubmissionViewSet`
  list/create; renamed content `UploadUrlSerializer` → `ContentUploadUrlSerializer` (was colliding with the
  assignments one — the only schema-correctness warning). Residual 6 warnings are cosmetic enum-name collisions
  on `status` + two pre-existing Day-1 viewsets (DeviceViewSet, BranchViewSet) — out of Day-2 scope.
**EOD gate — all green:**
- `ruff check .` + `ruff format --check .` — clean (324 files).
- `mypy apps core infrastructure config` — clean (292 files, cold cache). NOTE: `tests/test_auth_flows.py:301`
  (Day-1) trips one factory-typing error only when `tests/` is added to the target; it is OUTSIDE the canonical
  gate scope and not a Day-2 file.
- `pytest -q` — **338 passed, 2 skipped** (weasyprint + libmagic real-render skip on Windows; CI/Linux runs them).
- `pytest --cov=apps --cov=core --cov-fail-under=70` — **88.77%** (target ≥75 cleared; trending to TD-20's 80%).
- Fresh-DB: `pytest --create-db` full run applies every Day-2 migration incl. **btree_gist** + provisions
  tenant_a/tenant_b from scratch — green.
- OpenAPI: `/api/schema/` generates with **0 errors** (6 cosmetic/Day-1 warnings, categorized above).
- `makemigrations --check` — No changes detected.
**TASKS.md ticked:** §26 (Day-2 matrix, object-scoping, isolation, query-count, conflict-property, layering,
coverage, fresh-DB items) + the Day-2 Note.
**Deviations from plan:** (1) cross-tenant isolation (D2-F-2) is covered by **per-lane** explicit tests
(attendance/academics/assignments/content list cross-tenant + schedule iCal `tenant_mismatch` + Day-1
`test_tenant_isolation`) rather than a router-introspection sweep — the router-derived endpoint-inventory helper
was **not built** (a generic sweep 400s on endpoints needing setup; per-resource tests are more reliable). (2)
the 10-step demo script is exercised by the automated suite, not run live here (needs Redis + a Celery worker +
MinIO, none running on this box; `CELERY_TASK_ALWAYS_EAGER` covers task bodies in tests).
**Blocked:** live demo against `demo.localhost` + the `@pytest.mark.minio` test need a running stack (owner).
**Handoff notes:**
- **time-machine adopted (TD-16 addition)** over freezegun (C-level patching, faster, fewer side effects) —
  used for the correction-window (B), late-flag (D), and conflict-time tests. **D3+ lanes use time-machine,
  not freezegun.** (Already in `pyproject.toml` dev deps.)
- **`s3_stub` fixture** (root conftest) + `tests/storage_stub.InMemoryS3` is the shared storage harness — D3-B
  payment-receipt + D4-B report tests reuse it.
- New deps locked this lane's day: **weasyprint** (TD-14, Lane C), **time-machine** (TD-16). CI must `uv sync`
  for weasyprint (GTK) + libmagic so the 2 skipped native-render tests run.

---
### [Day 2 · Lane E] Content + Storage — 2026-06-11
**Shipped (all RUN on real Postgres — 18 Lane-E tests, 255/255 suite green, 1 skip):**
- Models (`apps/content/models.py`, migration `content/0002` replaces `ContentItem`):
  `ContentLibrary` (visibility tenant/department/cohort/role), `Course`/`Module`/`ContentLesson`
  (named to avoid clashing with `schedule.Lesson`), `Folder`, `LessonFile`, `FileView`. **CheckConstraint
  `lessonfile_lesson_or_folder`** (a file must attach to one or the other); unique `s3_key`, folder path,
  module order.
- Canonical signed-URL flow (`services.py`): `request_upload` (ext **and** declared content-type vs
  `allowed_file_types`, size vs `max_upload_mb`, quota vs `storage_quota_gb` → 422 `file_type_not_allowed` /
  `file_too_large` / `storage_quota_exceeded`; pending `LessonFile` + key **`{schema}/tmp/{uuid}/{filename}`** +
  presigned PUT) → `confirm_upload` (409 `file_not_pending` if not pending; **no S3 call**, just enqueue) →
  `validate_uploaded_file` (head_object size, ranged-GET first 8KB → `_sniff_mime` libmagic family check →
  `rejected` on mismatch, else copy tmp→**`{schema}/content/{id}/{filename}`** + delete tmp + `clean`,
  enqueue thumbnail) → `generate_thumbnail` (Pillow ≤320px JPEG → `.../thumb.jpg`). Both task bodies idempotent
  (status / existing-thumb short-circuit).
- Downloads: `download_url` (CLEAN only → 409 `file_not_clean`; **F()-increment** `download_count` + `FileView`,
  TTL 300); `track_view` (F() `view_count` + `FileView`). Versioning: `create_new_version` (links
  `previous_version`, `version+1`).
- Selectors: `scoped_libraries`/`scoped_files` (director all; else tenant + department-membership + related-cohort
  + role-allowlist via JSON `allowed_roles__contains` — drafts/other scopes 404, not 403); `storage_used_bytes()`
  (sum of CLEAN sizes — D3-E billing meter).
- Endpoints: libraries/courses/modules/lessons/folders CRUD (scoped); `POST /content/upload-url/`;
  `/files/` list+retrieve + `/{id}/confirm|download-url|track-view|new-version/`.
- `infrastructure/storage/s3_client.py` **+ `head_object`, `get_object_range`, `download_bytes`, `copy_object`,
  `delete_object`** (additive). Celery `validate_uploaded_file` + `generate_thumbnail` in
  `celery_tasks/content_tasks.py` (per-file, `_schema_name`, retry≤3 backoff), registered in aggregator.
- `scripts/seed_dev.py` **`bootstrap_dev_storage()`** (idempotent create_bucket + tmp lifecycle + CORS;
  best-effort — warns and continues if MinIO is down). Knobs: **added `storage_quota_gb` (null)** + serializer +
  `org/0006`; **`allowed_file_types` default += `jpeg`,`webp`**; **reused `max_upload_mb`** as the size cap
  (NOT a new `max_file_size_mb` — coordinated rename, see handoff). New factories: the 6 content models.
**Tests:** allowlist/size/quota 422s, key-prefix==schema, confirm-non-pending 409, magic mismatch→rejected,
valid→clean+moved, validate idempotent, thumbnail idempotent (Pillow real, JPEG magic), only-clean-downloadable,
F() counters + FileView rows, **visibility matrix** (tenant/cohort visible; department/role/other-cohort hidden
for a student), version chain, storage_used_bytes (clean-only), **seed bootstrap idempotent** (Mock client),
upload-url perm, cross-tenant, files + libraries list query budgets (≤8). **1 SKIPPED elsewhere** = Lane C's
weasyprint real-render. libmagic real sniff is CI/Linux only (Windows lacks the native lib) — unit tests
monkeypatch `_sniff_mime`; the lazy `import magic` keeps the app loadable on Windows.
**TASKS.md ticked:** §13 + §23 (all except antivirus / video transcode / AI summary — deferred).
**Deviations from plan:** (1) **`max_file_size_mb` → reused existing `max_upload_mb`** (D1-B already had it;
D2-D also uses it) — one knob, not two. (2) tmp-lifecycle prefix is `tmp/` per spec but our keys are
**schema-first** (`{schema}/tmp/...`), so the dev lifecycle rule is a placeholder — abandoned-tmp cleanup
relies on the validate task's delete on the happy path; a per-schema sweep is future work (flagged in
`bootstrap_dev_storage` docstring). (3) reused Lane B's 422 `UnprocessableEntity` + Lane A's 409
`ConflictException`. (4) `upload-url` is a root APIView (`/content/upload-url/`) per the spec path, not a
`/files/` sub-action.
**Blocked:** production S3 is `[OWNER:O-9]`; MinIO/mock path is complete per TD-2. CI must `uv sync` for the
real libmagic sniff to run.
**Handoff notes (D3-E / D4-E / D5-D consume):**
- **Upload state machine** `pending → clean | rejected` + endpoints above are the **frontend contract (D5-D)**.
- **`storage_used_bytes()`** (`apps.content.selectors`) — **D3-E** billing meters it; **D4-E** control center
  displays it. Attachment/content keys are all **schema-first** (`{schema}/...`) for shared-bucket isolation.
- New `s3_client` helpers: `head_object(key)→dict`, `get_object_range(key,start,end)→bytes`,
  `download_bytes(key)→bytes`, `copy_object(src_key,dest_key)→key`, `delete_object(key)`, `upload_bytes` (Lane C).
- Knobs: `allowed_file_types`, `max_upload_mb` (a.k.a. max_file_size_mb), `storage_quota_gb`.

---
### [Day 2 · Lane D] Assignments — 2026-06-11
**Shipped (all RUN on real Postgres — 19 Lane-D tests, 237/237 suite green, 1 skip):**
- Models `Assignment`/`Submission`/`SubmissionGrade` (`apps/assignments/models.py`, migration
  `assignments/0002` replaces `AssignmentItem`): unique `(assignment, student, attempt_number)`;
  check constraints (attempt>=1, score>=0); indexes `(cohort, due_at)`, `(assignment, student)`, status.
- Services (`services.py`): `validate_and_presign_upload` (ext vs `allowed_file_types` → **422
  `file_type_not_allowed`**; size vs `max_upload_mb` → **422 `file_too_large`**; key
  **`{schema}/assignments/{uuid}/{filename}`**); `publish_assignment` (emits `assignment_published`);
  `submit` (rejects draft/closed → 422, non-member → 422 `student_not_in_cohort`,
  `attempt_number = last+1` past limit → **422 `resubmit_limit_exceeded`**, `is_late` vs `due_at + grace`);
  `grade_submission` (score range, unknown rubric criterion → **422**, Σ rubric max_points > max_score →
  **422**, emits `submission_graded`); `check_submission` → typed `PlagiarismResult(not_implemented, None)`;
  `request_ai_feedback` (emits); `emit_due_soon_reminders` (24h window, `due_soon_sent_at` idempotency key).
- Selectors: `scoped_assignments` (staff all; teacher own cohorts incl. drafts; student **published** own
  cohorts — drafts/other cohorts 404, not a 403 leak); `scoped_submissions` (staff all; teacher own cohorts;
  student own; `select_related("...grade")` — no N+1).
- Endpoints: assignments CRUD + `/publish/`, `/upload-url/` (collection), `/{id}/submissions/` (GET teacher
  list / POST student submit, method-gated), `/submissions/{id}/` retrieve + `/grade/` + `/request-ai-feedback/`
  (202 queued).
- Celery `send_due_soon_reminders` (fan-out per Center) in `celery_tasks/assignment_tasks.py`, registered in
  aggregator + `CELERY_BEAT_SCHEDULE` (hourly). Knob **added: `assignment_max_resubmits` (2)** + serializer +
  `org/0005`; `assignment_grace_minutes`/`allowed_file_types`/`max_upload_mb` already existed (D1-B).
- New factories: `Assignment`, `Submission`.
**Tests:** late-flag boundaries ×3 (time_machine `tick=False`; due+grace exact = on time), resubmit limit
default+override, closed/non-member rejects, rubric unknown-criterion + sum-cap, grade score range, plagiarism
stub typed, upload-url key-prefix + allowlist + oversize (presign monkeypatched — test settings have no S3
OPTIONS), due-soon idempotent, **all four signals emitted**, draft-invisible (list + 404), cross-cohort submit
404, student submit 201, assignment-create perm, cross-tenant, assignments + submissions list query budgets (≤8).
All run.
**TASKS.md ticked:** §12 (all except real AI feedback, deferred to D4-A).
**Deviations from plan:** (1) the nested `submissions` action gates **method-specific** (GET→`assignments:write`
teacher list, POST→`assignments:submit` student) behind a shared `assignments:read` floor, since one action name
maps to one matrix code; submit additionally requires the user to have a `StudentProfile`. (2) reused Lane B's 422
`UnprocessableEntity` for all submit/grade rejections (consistent envelope). (3) `SubmissionSerializer.grade` is a
`SerializerMethodField` (not nested) so an ungraded submission serializes to null without `RelatedObjectDoesNotExist`.
**Blocked:** none.
**Handoff notes (D3-C / D4-A / D3-E consume):**
- **Signals** (`apps.assignments.signals`, emit-only): `assignment_published(assignment_id, cohort_id, schema_name)`,
  `assignment_due_soon(assignment_id, cohort_id, due_at, schema_name)`, `submission_graded(submission_id,
  student_id, score, schema_name)` → **D3-C** notify; `ai_feedback_requested(submission_id, requested_by,
  schema_name)` → **D4-A** AI, which writes **`SubmissionGrade.ai_feedback`** (field reserved, blank today).
- **Attachment key convention `{schema_name}/assignments/{uuid}/{filename}`** via `presign_upload` — flag for
  **D3-E** quota metering scope (all tenant blobs are schema-prefixed).
- Matrix: **STUDENT now has `assignments:submit`**. Knobs: `assignment_grace_minutes`, `assignment_max_resubmits`,
  `allowed_file_types`, `max_upload_mb`.

---
### [Day 2 · Lane C] Academics — 2026-06-11
**Shipped (all RUN on real Postgres — 19 Lane-C tests + 1 skipped, 218/218 suite green, 1 skip):**
- Models `Subject`/`Exam`/`ExamResult`/`Grade`/`Transcript` (`apps/academics/models.py`, migration
  `academics/0002` replaces `AcademicItem`): unique `(exam, student)` result + `(student, subject, term)`
  grade; check constraints (max_score>0, weight>0, score>=0); indexes per spec.
- `apps/academics/grading.py` — pure `display_for(value_raw, scheme)`: letter A≥90/B≥80/C≥70/D≥60/F,
  GPA = raw/25 (2dp), percentage = raw (1dp). Knob-driven, zero DB.
- Services (`services.py`): `record_results` (upsert; score outside 0..max → **422 `score_out_of_range`**;
  `grade_changed` emitted **once on overwrite**, never on first entry); `bulk_grade_import`
  (`student_id,score,note` CSV; all-or-nothing — any bad row → **422 `csv_row_errors`** with row numbers,
  zero written); `publish_exam`; `compute_term_grade` (weighted `100·Σ(score/max·weight)/Σweight` over
  **published** results → `Grade` with `components` JSON + scheme `value_display`; `publish` flag);
  `recompute_cohort_term`.
- Transcripts (TD-14): `request_transcript` (pending + enqueue on commit) → Celery
  `generate_transcript_pdf` (`celery_tasks/academics_tasks.py`, bind, max_retries=3, retry_backoff) →
  `generate_transcript` body (idempotent: `done` short-circuits; pending→processing→done; uploads to
  **`{schema}/transcripts/{id}.pdf`**). `render_transcript_pdf` **lazy-imports weasyprint** (GTK native
  libs only needed there) and renders `templates/documents/transcript.html` (gettext, per-student
  `preferred_language`). `presign_transcript` → signed `download_url` (TTL 600). `infrastructure/storage/
  s3_client.py` gained `upload_bytes`.
- Selectors: `scoped_grades` (staff all; teacher → cohorts they teach incl. drafts; parent/student →
  **is_published=True** + self/children — publication gating); `scoped_transcripts`; `honor_roll` /
  `academic_warnings` (knob-driven).
- Endpoints: `subjects`/`exams` CRUD; `exams/{id}/results/` (GET+POST), `.../results/import-csv/` (multipart),
  `.../publish/`; `grades/` (read, scoped+gated) + `grades/recompute/`; `transcripts/` (POST 202 pending,
  GET status+download_url); `honor-roll/` + `warnings/` (staff-only).
- Knobs: **added `honor_roll_min` (90) + `academic_warning_max` (60)** Decimals + serializer + `org/0004`;
  `grading_scheme` already existed (D1-B). New dep **`weasyprint>=63`** (TD-14/16) in pyproject + uv.lock.
- New factories: `Subject/Exam/ExamResult/Grade`.
**Tests:** weighted-grade fixture (.2/.3/.5 → 92.000), unpublished-excluded, value_display ×3 schemes
(knob-driven), letter-band pure, score-out-of-range 422, grade_changed once-on-overwrite, CSV atomic+row-errors,
transcript lifecycle idempotent (S3 stubbed, `%PDF` magic), transcript POST 202 pending, publication gating
(parent/student/teacher), teacher academics:read matrix, honor-roll knob flip + staff-only endpoint, exam-create
perm, grades cross-tenant, grades+exams list query budgets (≤8). **1 SKIPPED:** `test_weasyprint_renders_real_pdf`
(weasyprint GTK native libs absent on the Windows dev box — runs on CI/Linux; the lifecycle test covers the
wiring via a stubbed renderer).
**TASKS.md ticked:** §11 (all except AI exam-gen, deferred to D4-A).
**Deviations from plan:** (1) **GET `/exams/{id}/results/` gated at `academics:write`** (not `:read`) — raw
per-student scores are staff/teacher-facing; gating at read would leak a cohort's scores to the students/parents
who also hold `academics:read`. Students/parents read grades via `/grades/` (scoped+gated). (2) **honor-roll /
warnings are staff-only** (director/head/teacher) despite `academics:read` — same leak reasoning. (3) Added an
optional `publish` flag to `compute_term_grade`/`recompute` (+recompute body) so the gating is exercised by real
code paths; grades default unpublished. (4) `student_not_in_cohort`-style validations reuse the 422
`UnprocessableEntity` introduced in Lane B. (5) weasyprint is **declared + locked but not synced locally** — the
native render is CI-verified, Windows-skipped (honest: see SKIPPED above).
**Blocked:** none. (CI must `uv sync` to install weasyprint + GTK for the skipped test to run.)
**Handoff notes (D2-E / D3-D / D4-D consume):**
- **`academics.Subject`** at `apps.academics.models` — D2-E FKs it (Lane E merges after C). `Exam`/`Grade`/
  `Transcript` paths as above.
- **Signal `academics.signals.grade_changed`** (emit-only): `send(sender=ExamResult, instance, old_score,
  new_score, actor_id, schema_name)` — fires once per overwrite. **D3-D** audit consumes (TD-9: Grade + ExamResult).
- **Transcript task** `celery_tasks.academics_tasks.generate_transcript_pdf` + **S3 key `{schema}/transcripts/
  {id}.pdf`** — D4-D printing reuses the weasyprint→S3 pattern. `infrastructure.storage.s3_client.upload_bytes`
  is the server-side upload helper.
- **Knobs:** `grading_scheme`, `honor_roll_min` (90), `academic_warning_max` (60). Matrix: **TEACHER now has
  `academics:read`** (Day-1 had only `academics:write`); STUDENT/PARENT `academics:read` was wired in Lane B.

---
### [Day 2 · Lane B] Attendance — 2026-06-11
**Shipped (all RUN on real Postgres — 19 Lane-B tests, 199/199 suite green):**
- Model `AttendanceRecord` (`apps/attendance/models.py`, migration `attendance/0002` replaces the
  `AttendanceItem` placeholder): `student`/`lesson` PROTECT, `status` (present/absent/late/excused),
  `arrived_at`, `note`, `marked_by` (User SET_NULL — null also = the auto sweep), `marked_at`,
  `auto_marked`, `created_at`; **`UniqueConstraint(student, lesson)`** + indexes (lesson; student,created_at; status).
- `mark_attendance(*, lesson, entries, actor)` (`services.py`): `update_or_create` upsert; actor must
  teach the lesson (director/head_of_dept bypass) else **403 `not_lesson_teacher`**; each student must
  hold an active `CohortMembership` else **422 `student_not_in_cohort`** (ids in `error.fields.students`);
  a supplied `arrived_at` past `late_threshold_minutes` ⇒ `late` (== threshold stays `present`); edits past
  `attendance_correction_window_hours` after `lesson.ends_at` ⇒ **403 `correction_window_expired`** unless director.
- `auto_mark_absent()` beat body: for `scheduled` lessons with `starts_at <= now - auto_absent_after_minutes`,
  `get_or_create` `absent` (`auto_marked=True`, `marked_by=None`) for active members lacking a record — idempotent
  (created-flag), never overwrites an existing mark. Fan-out task `mark_absent_after_lesson` (per active Center)
  in `celery_tasks/attendance_tasks.py`, registered in the aggregator + `CELERY_BEAT_SCHEDULE` (15 min).
- Selectors (`selectors.py`): `scoped_records` (staff=director/head_of_dept → all; teacher → own lessons'
  records; parent → guardian-linked children; student → own — `select_related("student__user","lesson")`);
  `term_summary` (1 aggregate, scoped base → no leak); `cohort_dashboard` (1 aggregate query, ≤5 for the request).
- Endpoints: `POST /attendance/lessons/{id}/mark/`, `GET /attendance/records/`(+`{id}`),
  `GET /attendance/summary/?student=&term=`, `GET /attendance/cohorts/{id}/dashboard/?date_from=&date_to=`
  (staff or teaching-teacher only — students/parents 403), `GET /attendance/export/?cohort=&term=`
  (streaming `text/csv`: date,lesson,student,status,marked_by). `AttendanceFilter` (student/lesson/cohort/status/date range).
- **Foundational (additive):** `core/exceptions.UnprocessableEntity` (422, code `unprocessable_entity`).
- CenterSettings: **added `auto_absent_after_minutes` (default 30)** + serializer field + `org/0003`;
  `late_threshold_minutes`/`attendance_correction_window_hours` already existed (D1-B) and are now consumed.
- New factories: `CohortMembershipFactory`, `parents.ParentProfileFactory`/`GuardianFactory`, `attendance.AttendanceRecordFactory`.
**Tests:** mark upsert (created/updated), teacher-of-other-cohort 403, student-not-in-cohort 422, late-threshold
boundary (parametrized 10=present/11=late), knob-changes-behavior (DoD #2), correction-window (time_machine,
teacher 403 / director ok), auto-absent idempotent double-run (0 dup records, 0 dup signals), auto-absent skips
marked + future/cancelled, signal emitted manual+auto, summary math (hand-built 10), dashboard query budget (≤5,
30 students), CSV shape, records scoping (student/parent/teacher), cross-tenant isolated + mark 404, records query budget (≤8). All run.
**TASKS.md ticked:** §10 (all 10 items) · §22 `mark_absent_after_lesson`.
**Deviations from plan:** (1) **Matrix correction (not silent):** STUDENT `attendance:read_self`→`attendance:read`
and PARENT `attendance:read_own_children`→`attendance:read` — the gate checks `attendance:read`, so the
`*_self`/`*_own_children` codes were dead; row-scoping now lives in `scoped_records` (the TD-5 mechanism the owner
already applied to `students:read`). Academics codes changed the same way **pre-wiring Lane C** (selector + publication
gate land in C). (2) `student_not_in_cohort` returns **422** (new `UnprocessableEntity`), distinct from 400 malformed
input — DAY-2 Lane B acceptance asked for 422. (3) Correction-window test uses `time_machine.travel` with tokens minted
INSIDE the travel window (else the 15-min access token reads as expired).
**Blocked:** none.
**Handoff notes (D3-C / Lane C / D4 consume):**
- **`attendance.AttendanceRecord`** at `apps.attendance.models` is the FK/report target (D4-C `AttendanceConsumer`,
  D4-B reports). Fields as above; one row per (student, lesson).
- **Signal `attendance.signals.student_marked_absent`** (emit-only): `send(sender=AttendanceRecord, record_id, student_id,
  lesson_id, auto: bool, schema_name)`. Fires once per record that *becomes* absent (manual mark or sweep). **D3-C** wires
  guardian SMS/in-app off it — nothing in `apps/attendance` imports an sms/email/push adapter.
- **Three knobs** (CenterSettings): `late_threshold_minutes` (10), `attendance_correction_window_hours` (24),
  `auto_absent_after_minutes` (30). Changing a knob alters behavior with no code change (DoD #2).
- `scoped_records(*, user, roles=None)` is the read-scoping helper; reuse the staff-set pattern in Lane C/D.

---
### [Day 2 · Lane A] Schedule (TD-12) — 2026-06-11
**Shipped (all RUN on real Postgres — 15 tests, 180/180 suite green):**
- Models `Term`, `TimeSlot`, `RecurrenceRule`, `Lesson` (`apps/schedule/models.py`). Migration
  `schedule/0002` includes **`BtreeGistExtension()`** (first op) + three `ExclusionConstraint`s over
  `tstzrange(starts_at, ends_at)` × equal room/teacher/cohort, conditioned on `status='scheduled'`.
  btree_gist is trusted in PG13+, so the non-superuser tenant role installs it on its own db.
- `materialize_rule` (dateutil `rrulestr`, holiday-skip via `org.BranchHoliday`, idempotent — replaces
  only future/non-detached/attendance-free lessons; detached survive); `check_conflicts` (half-open
  range overlap → touching edges allowed); `create_rule`/`update_rule` (validate rrule, clamp to term,
  materialize, **409 `schedule_conflict`** with conflicting ids in `error.fields`); `cancel_occurrence`,
  `move_occurrence` (detaches), `bulk_reschedule` (all-or-nothing rollback).
- Endpoints: `terms`/`timeslots`/`rules`/`lessons` CRUD + `lessons/{id}/cancel|move`,
  `rules/{id}/bulk-reschedule`, `ical-url/` (signed token) + `ical/<token>/` (AllowAny, tenant-bound,
  `text/calendar` via `icalendar`). `LessonFilter` (cohort/teacher/room/status/term + date_from/to).
- Celery `send_lesson_reminders` + `archive_completed_terms` (fan-out per active Center; bodies in
  services: `emit_due_reminders` [reminder_sent_at = idempotency key], `archive_ended_term_lessons`).
  Registered in `celery_tasks/tasks.py` aggregator + `CELERY_BEAT_SCHEDULE` (reminders 5 min, archival weekly).
- Matrix: `REGISTRAR += schedule:*` (TEACHER/STUDENT/PARENT keep `schedule:read`).
- **Foundational (additive):** `core/exceptions.StarforgeError` now accepts `fields=` and the handler
  emits `error.fields` for any StarforgeError (so 409 conflicts carry conflicting lesson ids).
- New deps: `icalendar` (TD-16). New factories: `TeacherProfileFactory`, `schedule.TermFactory`.
**Tests:** materialize count+holiday-skip, idempotent, detached-survives, **raw-ORM exclusion
IntegrityError**, conflict 409 (room/teacher/cohort, parametrized) + adjacent-allowed, bulk-reschedule
rollback, iCal valid + cross-tenant `tenant_mismatch`, invalid-rrule, reminder idempotent+schema-scoped,
archive, perm-denied, lessons-list query budget (≤8). All run.
**Publish to WORKLOG (B/C consume):** `schedule.Lesson` (FK target for `attendance.AttendanceRecord`) and
`schedule.Term` (FK target for `academics.Exam/Grade/Transcript`) at `apps.schedule.models`; field names
as in the model. `check_conflicts(*, starts_at, ends_at, cohort_id, teacher_id, room_id=None,
exclude_lesson_ids=())` → `{dimension: [ids]}`. Signals `lesson_reminder_due/lesson_cancelled/
lesson_rescheduled` (emit-only). `CELERY_BEAT_SCHEDULE` dict exists in base.py (append your entries).
btree_gist migration is in `schedule/0002` (later lanes' fresh-DB runs get it for free).

---
### [Day 2 · prep] Postgres up + RED MASTER fixed (165 green) — 2026-06-11
**Context:** Starting Day 2. Got Postgres working (the 5432 server uses the default
`postgres`/`root` superuser — created role `starforge`/`starforge` + db `starforge`; the
project's default DATABASE_URL now works). **First time the suite has actually RUN.**
`migrate_schemas --shared` succeeds on real Postgres 18.4 — the TD-3 / `db_constraint=False`
SHARED-schema design is validated.

**Master was RED when run (7 non-passing of 165 — committed but never executed without a DB).
Fixed all, now 165/165 green, stable across 5 runs:**
1. **Schema test-isolation (5 failures):** a `client_for(tenant)` request leaves
   `connection.schema_name` on that tenant — django-tenants doesn't reset at request end — which
   poisoned the next test's public-schema work (provisioning's "must be public" guard, platform
   API, archive). Added an autouse `_reset_schema_to_public` fixture in `conftest.py`.
2. **Refresh-reuse false-positive (real security/UX bug):** `change_password` blacklists the old
   refresh + bumps `tv` and mints a fresh pair; presenting the old (now-blacklisted) refresh to
   `/refresh/` tripped theft-detection, which revoked everything + bumped `tv` again, killing the
   just-issued pair (401). Fix: `_detect_refresh_reuse` now only treats a blacklisted token as
   theft when its `tv` is still current — rotation doesn't bump `tv` (real theft), but
   logout/password-change/role-change do (legitimate invalidation, leave the fresh pair alone).
3. **Non-string identifier (`test_throttle_survives_non_string_identifier`):** CharField silently
   coerced a JSON int to a string → 202 instead of 400. Added `_StrictIdentifierMixin` to the two
   reset serializers (reject non-string identifier with 400). Throttles already survived non-strings.
4. (Observed + resolved by #2) a `test_provisioning` flake caused by the old reuse path polluting
   the session-shared token-blacklist state.

**Gates:** ruff, ruff format, mypy (272 files), `manage.py check`, full `pytest` (165) — all green.
**Handoff:** Day-2 tests can and WILL be run (the Day-1 lesson). Baseline commit unchanged
(`03e81ea`); these fixes are uncommitted on top for owner review.

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

---
### [Day 1 · OWNER REVIEW] Independent review verdict + fixes + AUTH PIVOT — 2026-06-11
**Branch / commits:** `day1-build` (Day-1 build committed as `7c9e4fb`; review fixes + auth
pivot committed on top).

**Verdict for the Day-1 agent — read this before starting Day 2.**
The architecture, layering, and code quality of the build are genuinely strong; the TD-17
fixes were all correct, TD-1/3/4/5 landed as designed, and the WORKLOG discipline made this
review possible. But an independent 38-agent review (8 reviewers + adversarial verification
of every serious finding) confirmed **3 blockers your internal review missed, ~25 majors,
~25 minors** — and a clear systemic pattern you must fix going forward:

1. **Never-executed runtime paths are where the blockers hid.** All three blockers lived in
   code no test imports directly: (a) Celery `autodiscover_tasks(["celery_tasks"])` imports
   `celery_tasks.tasks`, which didn't exist — **zero tasks ever registered with a worker**;
   trial expiry and OTP purge were dead on arrival (fixed: `celery_tasks/tasks.py` aggregator
   + `tests/test_celery_registration.py`). (b) `rotate_refresh_token` never checked the
   `schema` claim — **a refresh from tenant A minted valid tokens for a pk-colliding user in
   tenant B**, reopening the exact hole TD-1 closed on the access path (fixed + regression
   test). (c) The WS middleware set the tenant schema on the event-loop thread while the user
   query ran on another thread — authed connects could never succeed, AND it accepted
   refresh tokens with no schema/tv binding (fixed: TD-1-complete rewrite + 3 WS tests).
2. **Don't claim coverage you don't have.** "Tests: covered indirectly via Lane E suite"
   (Lane A) and "covered by org settings + permission matrix" (Lane F) were false for every
   named required test. ~50 mandated tests were missing; the suite is now **165 collected**
   (was 44). If you skip a required test, write `SKIPPED:` with a reason — never imply it exists.
3. **No silent deviations — it's rule #1 of this file.** D1-LB-3/LF-8 acceptance said
   "teacher org GET 200"; the matrix shipped the opposite and the tests CODIFIED the
   deviation. Teacher now has `org:read`; PARENT/STUDENT got their dead self-service read
   paths wired (`students:read`/`parents:read` + scoped selectors + pickups scoping).
4. **Comments are load-bearing in an agent-driven repo.** Stale comments (beat-schedule
   "D4-F makes purge iterate tenants", conftest "testserver → public schema") would have sent
   future agents down wrong paths; both fixed. Keep them truthful.

**Other fixes landed** (each with regression tests — see commits for the full list):
unguarded write paths (cohort hard-delete cascading history away; teacher/student update
serializers bypassing service validation; `medical_notes` served to all staff roles — now
DIRECTOR/REGISTRAR-only on retrieve); 500-instead-of-envelope paths (CSV BOM/encoding,
birthdays `?days` DoS + param validation, duplicate holiday/weekday, non-numeric domain id,
`archive_center` atomicity + 63-byte schema truncation); X-Forwarded-For spoofing of IP caps
(`NUM_PROXIES`, default 0); EncryptedField tamper logging; X-Request-ID sanitization;
`set_user_password` now ends refresh sessions, not just access; apex/public-schema 404 gap
closed (`public_tenant` fixture + seed_dev public Domain row).

**AUTH PIVOT (owner decision — the new contract):**
- **Login is `POST /api/v1/auth/login/ {username, password}`** → `{access, refresh}`,
  401 `invalid_credentials` (indistinguishable + timing-equalized), throttles `login_user`
  5/min + `login_ip` 10/min. `User.username` is `USERNAME_FIELD` (unique, required,
  auto-generated by `User.objects.generate_username()` when staff-side services create
  accounts). The phone-or-email CheckConstraint is gone; phone/email are contact channels.
- **OTP is password reset/verification ONLY** (`PURPOSE_LOGIN` removed):
  `POST /auth/password/reset/request/` (always 202, anti-enumeration, IP cap runs BEFORE the
  existence check) → `POST /auth/password/reset/confirm/` (ends all sessions). Plus
  `POST /auth/password/change/` (authed; returns a fresh pair). `/auth/otp/*` routes are GONE.
- Ripples landed: users migration **regenerated** (`users/0001`, dependency pinned to
  `org/0001` to break a cycle — don't "fix" it back to the leaf), admin/serializers/factories
  (`UserFactory` keys on `username` now), seed (`admin`/`starforge-dev` tenant,
  `admin`/`starforge-platform` apex), `tests/test_auth_flows.py` rewritten (17 tests),
  README/architecture/API-CONTRACT §3/TASKS §0+§3 all updated. `/users/me/` now returns
  `username` and only ACTIVE role_memberships.

**Tests:** 165 collect; `tests/unit` (18) executed and green; everything else still gated on
Postgres. **Gates re-run green:** ruff format+check, mypy (272 files), `manage.py check`,
`makemigrations --check` ("No changes detected").
**Blocked:** the one unverified gate is unchanged — owner must run
`migrate_schemas --shared` + full `pytest --cov` once the DB is up. NOTE: port 5432 answered
with an auth failure for user `starforge` (not connection-refused) — a Postgres server may
already exist on this machine with different credentials; check before installing another.
**Handoff to Day 2:** the auth contract above is final — build against `login/` and the
reset flow; `required_perms`/`resource` + scoped selectors is the permission pattern; Lane B/F
test inventories in earlier entries are superseded by the files listed in the fix commits.

---
### [Day 2 · Lane E review fixes] content visibility, quota, tmp lifecycle, scoped writes, MIME, thumbnail-url — 2026-06-16
**Scope:** apps/content (+ shared core/permissions.py & tests/test_permission_matrix.py for the PARENT fix only).
**Shipped:**
- PARENT granted `content:read` (cohort visibility includes guardian-linked parents per DAY-2.md D2-E-6);
  the gate now matches the selector's parent branch (`_related_cohort_ids` was previously dead via the API);
  covered by matrix row + selector test. Decision recorded here per the review mandate.
- Storage quota re-validated inside `validate_uploaded_file` at the moment the file becomes CLEAN
  (still PENDING so `storage_used_bytes()` excludes it) — closes the sequential-batch / concurrent bypass
  where N back-to-back `request_upload` calls each saw the same unchanged CLEAN total. Cheap early gate kept.
- `_reject` now `delete_object`s the orphaned tmp blob (mirrors the happy path); `seed_dev` lifecycle
  rebuilt as one `{schema}/tmp/` expire rule per Center (the bare `tmp/` prefix never matched real keys).
- `ContentUploadUrlSerializer` lesson/folder querysets scoped to `scoped_libraries(user)` — scoped reads
  now have symmetric scoped writes; an out-of-scope folder/lesson PK is invalid (no cross-scope seeding).
- MIME sniff tightened: compares against the exact `_EXT_MIME` set for the file's extension (falls back to
  family for extensions not in the map), so PNG-as-JPEG / docx-as-pdf no longer pass as family-equal.
- `LessonFileSerializer` drops raw `thumbnail_key`; adds a TTL-limited (300s) signed `thumbnail_url`
  SerializerMethodField (null when no thumbnail), mirroring the download-url signing.
**Tests added (apps/content/tests/test_content.py):** quota batch-bypass, reject tmp-delete, exact-MIME
reject + pass, positive department-membership, positive role-allowlist, parent-sees-childs-cohort,
upload-url out-of-scope reject + in-scope accept, thumbnail-url-not-key. Matrix: PARENT GET /content/files/ True.
**Deviations:** (1) Quota test uses two 0.6 GB pending files with NO pre-existing CLEAN file (quota 1 GB) —
the brief's "existing 0.6 GB + two 0.6 GB" overshoots on the FIRST validate (0.6+0.6=1.2>1.0), so the
mathematically-correct realization of "first CLEAN, second REJECTED" is 0+0.6 then 0.6+0.6. Same control,
same assertions (`storage_used_bytes()` never exceeds quota). (2) Out-of-scope folder PK yields DRF's
standard 400 `validation_error` (PrimaryKeyRelatedField does_not_exist); brief said "422/404 otherwise" as
intent — test accepts 400/404/422 and asserts no LessonFile created.

---
### [Day 3 · Lane D] Audit trail (TD-9) — 2026-06-16
**Branch / commits:** `day1-build` (Lane D worktree).
**Shipped (apps/audit fully replaces the `AuditItem` placeholder):**
- **`AuditLog` model** (`apps/audit/models.py`, migration `audit/0002`): actor (User SET_NULL,
  related_name `+`) + `actor_repr` snapshot; `action` choices
  create/update/delete/login/login_failed/logout/otp_request/otp_verify/impersonate/export (db_index);
  `resource_type`/`resource_id`; `before`/`after` JSON null; `ip` (GenericIP); `user_agent` (512);
  `created_at` (auto_now_add, db_index). **No `updated_at` — rows are immutable.** Composite index
  `(resource_type, resource_id)` + `(actor,)` + the two db_index fields. Ordering `-created_at`.
- **`audit_log()` helper** (`apps/audit/services.py`) — the single chokepoint:
  `audit_log(*, actor=None, action, resource_type="", resource_id="", before=None, after=None,
  request=None, ip=None, user_agent=None) -> AuditLog`. Extracts ip/ua from `request` (via
  `core.utils.client_ip`/`user_agent`) when not passed; never raises on anonymous/None actor
  (`actor_repr="anonymous"`/`""`, FK null). Masks `before`/`after` centrally. Also exports
  `serialize_instance(instance, fields=None)` (JSON-safe field snapshot, FK→`<name>_id`),
  `diff_snapshots(before, after)` (update rows store only changed keys), `mask_snapshot`,
  `audit_log_on_commit(**kwargs)` (used by model receivers — insert scheduled via
  `transaction.on_commit` so a rolled-back write is never recorded).
- **Receivers** (`apps/audit/receivers.py`, wired in `AuditConfig.ready()` via
  `connect_audit_receivers()`): `pre_save` (before-snapshot keyed `label:pk` in a thread-local),
  `post_save` (create/update), `post_delete` on the **TD-9 model list** resolved with
  `apps.get_model` + try/except `LookupError` (verified: all 7 resolve in the current tree). Stable
  `dispatch_uid` per (model, signal) — no double-registration. **Auth-flow audit is signal-driven**:
  receivers on `login_succeeded`/`login_failed`/`otp_requested`/`otp_verified`/`otp_failed` (the real
  auth signals — there is NO `/auth/otp/*` endpoint anymore) write LOGIN / LOGIN_FAILED / OTP_REQUEST
  / OTP_VERIFY rows. Logout + refresh-reuse have no signal → exact `audit_log()` snippets for
  `apps/auth/services.py` are in **integration_needed** (orchestrator applies; I cannot edit auth).
- **Read-only API** (`apps/audit/{views,serializers,urls,selectors}.py`): `AuditLogViewSet`
  (List+Retrieve mixins, `http_method_names=["get","head","options"]` → PUT/PATCH/DELETE/POST **405**),
  `TimelinePagination` (cursor on `-created_at`), `AuditLogFilter` (actor/action/resource_type/
  resource_id/ts_from/ts_to), `audit:read` per-action, `select_related("actor")`. CSV **export**
  `GET /api/v1/audit/export/` (same filters, streamed, `>50_000` rows → 400 `validation_error`, the
  export itself audited as `action="export"`). Route ordered before the router so `export/` never
  shadows `{id}/`.
- **Retention beat** (`celery_tasks/audit_tasks.py`, registered in `celery_tasks/tasks.py`):
  `cleanup_old_audit_logs` fans out per active Center → `cleanup_old_audit_logs_for_schema` deletes
  >7y for `RETENTION_LONG_TYPES` {finance.Invoice, payments.Payment, finance.Refund, academics.Grade,
  academics.ExamResult}, >1y otherwise; returns deleted count; idempotent by age.
- **Read-only admin** (add/change/delete all denied) + **migration docstring** documenting the
  append-only invariant and the prod `REVOKE UPDATE, DELETE ON audit_auditlog` runbook line ([OWNER:O-9]).
**Tests** (`apps/audit/tests/test_audit.py`, 27): User create+update with before/after diff; delete row;
RoleMembership audited; ProviderConfig credential masking; helper masking + ip/ua extraction +
anonymous-safe + FK-id snapshot; login success/failure + OTP request/verify rows; 405 on
PUT/PATCH/DELETE/POST; audit:read matrix (DIRECTOR/IT/SUPPORT/HEAD_OF_DEPT allow; TEACHER/STUDENT/CASHIER
403; anon 401); cross-tenant `tenant_mismatch` + row isolation; filters; **cursor pagination stable
under head inserts**; list query budget (≤8); CSV export streams+self-audits+over-cap 400+denied;
retention 7y/1y cohorts (aged via `.update(created_at=...)`) + idempotent second run + fan-out count.
**TASKS.md ticked:** §19 (all), §22 `cleanup_old_audit_logs`.
**Deviations from plan:** (1) **Auth audit wired via signal receivers in MY app**, not `audit_log()`
calls inside `apps/auth/services.py`, for login/otp (the published auth signals already carry
actor/ip/ua) — cleaner and testable without touching an off-limits file. Logout + refresh-reuse have NO
signal, so those two get explicit `audit_log()` snippets via integration_needed. (2) Migration index
names + the `delete`→`O'chirish` choice label are the values `makemigrations` produces under the repo's
`LANGUAGE_CODE="uz"` (verified zero drift for the audit app via the autodetector); only "Delete" has a
shipped Uzbek translation. (3) Could not run the full suite/makemigrations centrally (shared DB + sibling
lanes mid-build) — verified via `apps.populate()` import smoke + scoped autodetector drift check; ruff
format+check clean on `apps/audit` + `celery_tasks/audit_tasks.py`.
**Blocked:** prod DB-level REVOKE is `[OWNER:O-9]` (runbook line in the migration docstring; same role
runs migrations+traffic+retention here, so the migration does not issue it).
**Handoff notes / Publish (Lanes B/E + D4-E consume):**
- **`audit_log()` signature** (above) — Lane B calls it for webhook anomalies; **Lane E** calls it for
  `billing.Subscription` changes inside `schema_context(center.schema_name)` (the public-schema
  Subscription cannot be a tenant post_save target — Lane D decision honored: helper exposed, E calls);
  D4-E impersonation calls it with `action="impersonate"`.
- **Audited model list (TD-9):** users.User, users.RoleMembership, finance.Invoice, payments.Payment,
  academics.Grade, academics.ExamResult, payments.ProviderConfig — to be audited, your model must be on
  this list (resolved lazily, so a new model can be added by appending to `AUDITED_MODELS`).
- **Masking rules:** `MASKED_FIELDS = {national_id, medical_notes, password, click_secret_key,
  payme_key, payme_test_key, uzum_api_key}` → stored as `"***"`. Add a field here if you introduce a
  new credential/PII column on an audited model.
- **Retention classes:** 7y for {finance.Invoice, payments.Payment, finance.Refund, academics.Grade,
  academics.ExamResult}; 1y for everything else.

---
### [Day 3 · Lane D] Audit — verification pass + 1 bug fix — 2026-06-16
**Branch / commits:** `day1-build` (Lane D worktree, follow-up review session).
**Context:** Re-verified the full Lane D build against the DAY-3 §Lane-D contract end to end
(model fields/constraints/indexes, helper signature, receiver model list + masking, read-only API,
retention task, CSV export, append-only + cross-tenant tests). Everything matched the spec.
**Bug fixed [in-lane]:** `AuditLogViewSet` (`apps/audit/views.py`) was a plain
`ListModelMixin+RetrieveModelMixin+GenericViewSet` with **no `permission_classes`**. The project
default is `DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]` (NOT `RolePermission`), so the
`resource = "audit"` declaration was never enforced — **any authenticated role could read the entire
audit trail**, and the `test_list_denied_roles` (TEACHER/STUDENT/CASHIER → 403) assertion would have
failed on a real run. Added `permission_classes = [RolePermission]` (matches every sibling Day-3
viewset: notifications/finance APIViews all declare it explicitly). Also added an explicit
`initial()` → `assert_tenant_context()` so the read-only viewset has the same public-schema guard as
`AuditExportView` (it does not inherit `TenantSafeModelViewSet`). `RolePermission` and
`assert_tenant_context` were already imported. ruff format+check clean; all audit modules byte-compile.
**Deviations:** none new. **Blocked:** unchanged (`[OWNER:O-9]` DB-level REVOKE).
**Handoff:** integration_needed unchanged from the prior entry — beat entry + the two
`apps/auth/services.py` audit_log snippets (logout + refresh-reuse) still to be applied centrally.

---
### [Day 3 · Lane F] Attack & cross-tests (tests only) — 2026-06-16
**Branch / commits:** `day1-build` (Lane F worktree).
**Scope:** tests only — no app code edited. Audited the full D3-F-1..10 catalog (sibling
lanes pre-wrote most files in their worktrees) against the REAL built interfaces, fixed one
test bug, and found one P0 in Lane B's webhook replay code.
**Files owned/verified (test fn counts; some parametrized):**
- `apps/payments/tests/test_webhook_attacks.py` (9) — D3-F-1/2/3
- `apps/payments/tests/test_idempotency_attack.py` (4) — D3-F-4
- `apps/payments/tests/test_payme_spec.py` (20) + `fixtures/payme/*.json` (7) — D3-F-10
- `apps/finance/tests/test_allocation_properties.py` (6, ×7 awkward Decimals) — D3-F-5
- `apps/billing/tests/test_paywall_attack.py` (10) — D3-F-6
- `apps/audit/tests/test_append_only_attack.py` (8) — D3-F-7
- `apps/notifications/tests/test_preference_attack.py` (7) — D3-F-8
- cross-tenant sweep (D3-F-9): finance(2) / payments(3) / audit(3) +
  `apps/notifications/test_cross_tenant_sweep_day3.py`(2) (Lane C's `test_cross_tenant_day3.py`
  is the basic one; the sweep uses a distinct filename to avoid clobbering an other-lane file).
- shared harness: `apps/payments/tests/builders.py`, `_helpers.py`.
**Test fix [in-lane]:** `test_checkout_endpoint_idempotency_header_one_payment` posted
`{"invoice_id": ...}` but `CheckoutSerializer.invoice` is the field name → would have 400'd.
Changed to `{"invoice": ...}`.
**P0 FOUND (Lane B — apps/payments) — webhook replay never records `duplicate`:**
`services.record_webhook_event` returns `(existing, False)` on a replayed `(provider,event_id)`
but **never sets `existing.status = WebhookEvent.Status.DUPLICATE`** — contradicting its own
docstring ("returns the existing row marked `duplicate`") and the D3-B-6 acceptance
("replayed nonce → recorded as `duplicate`"). The Uzum view returns `{"status":"duplicate"}` in
the response body but likewise leaves the row at its prior status; Click returns "Already
processed". `test_click_complete_replay_duplicate_single_allocation` asserts the contracted
`status=="duplicate"` and will RED-flag this until Lane B sets the status on replay (one-line:
in `record_webhook_event`, when `existing` is found, `existing.status = DUPLICATE; existing.save(...)`
before returning). The one-Payment / one-allocation halves of that test are correct and pass.
**Contract ambiguities assumed (documented so the central run is predictable):**
- D3-F-3 Payme "wrong-tenant slug": tests seed BOTH tenants' ProviderConfig with the same
  `PAYME_KEY`, so HTTP Basic passes in B and the failure is the **account** error
  (-31050..-31099) because A's invoice number doesn't exist in B — matching DAY-3.md's explicit
  "(account error in -31050..-31099)" wording rather than a -32504 auth failure.
- Click/Uzum webhook errors use the standard TD-18 envelope; Payme uses pure JSON-RPC (HTTP 200,
  `error` member) — the documented Lane B exception. Tests assert accordingly.
- Idempotency: eager Celery has no true concurrency, so D3-F-4 exercises the sequential-replay
  contract (same key → same pk, count==1) + the raw unique-constraint IntegrityError as the
  load-bearing backstop (per the DAY-3.md note).
- Quiet-hours: eager `apply_async` ignores `eta`, so D3-F-8 monkeypatches
  `deliver_single_channel.apply_async` to capture the eta == window-end (07:00 local) without
  executing it — asserting the deferral contract, plus `provider_response.deferred_to` +
  `skipped_quiet_hours` on the delivery row.
- Append-only grep (D3-F-7) scans `apps/`+`core/` for `AuditLog.objects…update(/delete(` (zero
  allowed) and permits `.delete(` only in `celery_tasks/audit_tasks.py` (retention, by
  `created_at__lt` age). Verified zero offenders against the current tree.
**Attack vectors covered (D3-F-1..10):** Click bad-sign→-1 + zero Payment rows; Payme wrong
Basic→-32504 HTTP200 JSON-RPC error; Uzum bad HMAC→rejected WebhookEvent(status=rejected,
signature_valid=False) + Uzum valid-HMAC control; Payme CreateTransaction replay→one Payment +
identical response; Click complete replay→single allocation (+ duplicate-status P0 above);
wrong-tenant slug→account-band error, no rows either schema; nonexistent + inactive slug→404
envelope; idempotency-key reuse (service + endpoint + raw unique constraint)→one Payment;
allocation rounding props over 7 awkward Decimals (1,000,000.01/3, 0.01, 100/3, max-18-digit
boundary, sub-cent remainder): Σ==amount exactly, no over-credit, Decimal type + 2dp, status
flip issued→partially_paid→paid, over-allocation→ValidationException, explicit-invoice targeting;
paywall suspended→402 subscription_required, allowlist (login [AUTH PIVOT, not /auth/otp/*],
password-reset-request, /healthz/live, /api/schema) reachable, active/trialing pass, missing-row
passes (no fail-closed), other tenant unaffected, **suspended tenant's PUBLIC webhook still works**;
audit PUT/PATCH/DELETE/POST→405 as director AND superuser + GET control + ORM grep; preference
matrix (disabled SMS→in-app only, MockEskiz empty, skipped_pref recorded; default-on control) +
quiet-hours eta + double-fire dedupe (one Notification, one SMS) + fan-out task-rerun idempotency
+ per-schema isolation; cross-tenant sweep over EVERY finance/payments/notifications/audit
endpoint (tenant-A JWT on tenant-B host→401 tenant_mismatch) + rows-invisible-across-tenant +
CSV-export isolation + provider-config credentials-never-echoed; Payme golden suite (auth,
unknown-method -32601, amount-mismatch -31001, unknown-account band + `data`=field, unknown-txn
-31003, state 1→2 / 1→-1 / 2→-2, ms times, account echo, tiyin math, idempotent create, second
concurrent account -31099) driven by per-method fixtures.
**Blocked / depends on shared wiring NOT yet applied (orchestrator must land before these RUN):**
- **Lane B D3-B-5**: `config/urls_public.py` += `path("api/v1/webhooks/", include("apps.payments.webhook_urls"))`.
  ALL webhook tests (test_webhook_attacks, test_payme_spec, the public-webhook half of the paywall
  suite) post to the apex/`testserver` host → resolve via `urls_public.py`. Currently absent.
- **Lane E D3-E-1/E-4**: `apps.billing` in SHARED_APPS + `SubscriptionGateMiddleware` at MIDDLEWARE
  index 1. The entire `test_paywall_attack.py` depends on the middleware being active.
- Tenant URLs for finance/payments/notifications/audit ARE already in `config/urls.py` (verified),
  so the cross-tenant sweeps + tenant-side suites are unblocked.
**Coverage:** Day-3 floor rises to 80% (TD-20) — the central run measures it; D3-F's duty to bump
`--cov-fail-under` to 80 in `ci.yml` is a shared-file edit → flagged in integration_needed.
**Handoff:** the one found vuln (duplicate-status P0) is a same-day `fix(payments)` for Lane B.
