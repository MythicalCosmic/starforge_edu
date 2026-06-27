# Feature Backlog

This is the decomposition of `FEATURE_LIST.md` (the owner's raw idea inbox) +
`docs/PRODUCT_VISION.md` (the canonical strategy) into discrete, buildable
features. Each item has acceptance criteria + a STATUS.

Roles mapping (from `core/permissions.py`): **manager = `director`** (and `head_of_dept`
for dept-scoped), **receptionist = `registrar`**. New resources get matrix entries.

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED(reason)`.

---

## ★ ARCHITECTURE FOUNDATIONS (from PRODUCT_VISION — build these FIRST, they collapse dozens of features)
The vision's biggest leverage is that most "features" are instances of a few engines.
Build the engine once; the rest is configuration.

| # | Foundation | Why it collapses N features | Status |
|---|-----------|------------------------------|--------|
| **A-1** | **Approvals + Ledger engine** (`apps.approvals`: ApprovalRequest + LedgerEntry): `request → approve/reject → cashier disburses → immutable ledger row` | Expenses, staff loans, procurement (#15), payment-delay (#5), discount requests (#5/#7), partial-pay, salary-prep (#7), event cost-split (#14), book cash-sales (#8), rewards/points payouts (#6/#7) — ALL one engine. The ledger is the anti-fraud moat ("money can't disappear"). | **CORE DONE** + **effect-at-approve kinds live**: `discount` (→ standing Discount, F15-3) and `payment_delay` (→ reversible invoice due-date extension). **Maker-checker enforced** (no self-approval) + **reject-after-approve reverses the effect** (adversarial-review hardening). **`DiscountViewSet` bypass closed**: discounts are read-only over CRUD (granted only via the approval `discount` KIND); direct create/edit/delete blocked, ended only via the `deactivate` action. **Money kinds live:** `loan` (F21-1, `apps.loans` — repayment tracking + outstanding-to-zero, beneficiary SoD, staff-only borrower) and `procurement` (#15, `apps.procurement` — itemised purchase orders totalling the request, supplier named on the ledger). **Money-IN POS live:** `book_cash` (#8, `apps.sales` — a book/material cash sale writes an immutable money-IN LedgerEntry; a refund writes a compensating money-OUT row, append-only; sell vs refund are separate perms; branch-scoped to the till — though the ledger rows themselves are centre-wide to finance via `/approvals/ledger/`, by A-1 design). TODO: notify-on-disburse, multi-step approval chains, fold in Expenses, salary_prep/event_split kinds. |
| **A-2** | **Dynamic permission system** (CRITICAL/security): center-configurable custom roles + granular permissions, **enforced live server-side**, instant revocation | Replaces the static `ROLE_PERMISSION_MATRIX`. Born from a real breach (localStorage-only auth). Every gated endpoint depends on it. | **INCR 1 DONE** (`apps.access`): per-role grant/revoke overrides layered over the static matrix, read per-request (instant, no staleness), enforced in `has_permission_code` + `roles_with_permission`. Wildcard-aware revoke (carves a verb out of a `resource:*` grant). Invariants: `*:*` non-overridable (serializer+service+DB CheckConstraint), `access` resource non-delegable (director-only mgmt), superuser bypass intact. API `/api/v1/access/` (overrides CRUD, roles effective view, catalog). TODO: center-DEFINED custom roles (arbitrary names beyond `Role.ALL`) + RoleMembership migration; per-branch overrides. |
| **A-3** | **Intelligence/metrics pipeline**: one computed feed over attendance/grades/submissions/payments | Risk flags ⭐ (dropout = #1 revenue leak), family-health, branch ranking, teacher value-add, journey timeline — all views on it. Start as transparent RULES, not black-box AI. | **RISK-FLAGS DONE** (`apps.intelligence`, model-less compute-on-read): transparent rules (low_attendance/low_grades/overdue_payment, weighted → low/medium/high) over the data the center already has. `/api/v1/intelligence/risk/` (feed, `?cohort=`), `risk/<id>/` (per-student why), `rules/` (the rules verbatim — no black box). **BRANCH-RANKING DONE**: `/api/v1/intelligence/branches/` scores each in-scope branch 0-100 over attendance + published grades + dropout-risk (transparent weights exposed via `method`), branch-level only with **k-anonymity small-cell suppression** (branches < 3 active students suppressed → no per-student round-trip), no-academic-signal branches left unranked, overdue finance-gated (and gated out of the at-risk count + score), director sees all branches / managers their own. **FAMILY-HEALTH DONE**: `/api/v1/intelligence/families/` flags each family (guardian + their guarded children) good/watch/at_risk for the retention desk, worst-first; double-gated `intelligence:read` AND `parents:read` (director+reception only — not teachers, not parents); overdue finance-gated. **JOURNEY-TIMELINE DONE**: `/api/v1/intelligence/journey/<student_id>/` — one student's chronological story (enrollment moves, published grades, achievements, finance-gated invoices), newest-first; family-facing (student + guardians see their own incl. their bills) + staff with students:read (IT walled off); published-grades-only. TODO: teacher value-add view; thresholds → CenterSettings; materialize via beat task at scale. |
| **A-4** | **Two surfaces** framing: owner ops platform vs student engagement layer | Sequencing rule, not a feature: owner-paid ops (payments/camera/attendance/payroll) first; student delight (games/podcasts/mocks/CBT/speaking) as the retention flywheel. | NOTE |

**Reconciliation:** the standalone **Expenses (F14-1, already shipped)** is the first
instance of A-1 — it will be folded into the generic engine; new money features
(loans/procurement/discount-requests/salary-prep) are built ON A-1 directly.

**Cross-cutting DNA to honor in every feature:** anti-fraud/accountability · dignity/
shame-reduction · paper-elimination · dedicated-in-country-server (biometric law) ·
premium AI tiering (Opus/Sonnet/Haiku, metered).

**Re-sequenced top of the build order:**
1. **A-1 Approvals+Ledger engine** (spine) ← *in progress* → migrate Expenses, add loans/procurement.
2. **A-2 Dynamic permissions** (security-critical foundation).
3. Forms engine (F3-3) + **A-3 risk-flag rules** (cheap, killer).
4. Teacher/student dashboards (F3-2/F4-1) as views on the engines.
5. Telegram-first parent notifications; lead→trial→enrolled CRM funnel.
6. Engagement layer (games/podcasts/mocks/CBT/speaking) — later track.

---

## Data-model delta (foundations many features need)
| # | Change | For features | Status |
|---|--------|--------------|--------|
| D-1 | `StudentProfile.location`, `.previous_school` (free text) | F2 filters | DONE |
| D-2 | `StudentProfile.blocked_at` + `.block_reason` (soft block ≠ withdrawn) | F2 block | DONE |
| D-3 | `LessonType` model (dynamic, manager-created) + `Lesson.lesson_type` FK | F3 dashboard | TODO |
| D-4 | `PlacementTest` + `PlacementQuestion` + `PlacementAttempt` (+ AI gen + approval state) | F1 | TODO |
| D-5 | `Form` + `FormQuestion` + `FormResponse` + `FormAnswer` (anonymity flag) | F3/F4 forms | TODO |
| D-6 | `Thread` + `Message` + `ThreadParticipant` (attachments as JSON S3 keys on Message) | F4 messaging | DONE (`apps.messaging`) |
| D-7 | `ContentLibrary`/`LessonFile` approval + `is_downloadable`/`view_only` flags | F4 library | TODO |
| D-8 | `CenterSettings` booleans for each dynamic on/off knob (group-acceptance, downloads, library-approval, ...) | all | PARTIAL |
| D-9 | `MeetingSlot`/`StaffMeeting` (teacher meetings, next-meeting) | F3 | DONE (`apps.meetings`: `StaffMeeting` + `MeetingAttendee`/RSVP) |

---

## Feature 1 — Reception onboarding + placement testing + AI group suggestion
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F1-1 | Department CRUD with job description + head | already exists (`org.Department` + `DepartmentViewSet`) | reuse | — | DONE(exists) |
| F1-2 | Placement test bank: create/edit tests + questions | `apps.placement` (`PlacementTest`+`PlacementQuestion`); `POST/PATCH /placement/tests/` + `questions/` (single_choice/true_false/writing, answer-key staff-only); DRAFT-only edits; branch-scoped create + `get_queryset` isolation; builder=teacher/reception/HOD/director (`placement:write`); DRAFT-only delete (pending/approved frozen) | new (D-4) | — | DONE |
| F1-3 | AI-generate / AI-recreate a placement test (draft) | reuse `ai.ExamGeneration` plumbing; output is a DRAFT | reuse+new | F1-2 | TODO |
| F1-4 | Manager approval of an (AI-)changed test before it goes live | lifecycle `draft→(submit)→pending→(approve/reject)→approved/draft`; `placement:approve` (HOD/director) only; **maker-checker SoD** (builder≠approver, `self_approval` 403); approve/reject under `select_for_update`+`@transaction.atomic`; reject kicks back to DRAFT + reason | new (D-4) | F1-2 | DONE |
| FX-forms-delete | **Follow-up (review-found):** `apps.forms` FormViewSet exposes raw DELETE (inherited template gap) → a builder can hard-delete a PUBLISHED/CLOSED form + CASCADE its responses. Mirror placement: DRAFT-only destroy. Lower stakes than placement (not the anti-fraud surface) so deferred. | harden existing | forms | TODO |
| F1-5 | Assign/show a placement test to a prospective student (lead) | reception assigns; student solves; result stored | new (D-4) | F1-2 | TODO |
| F1-6 | Auto-grade + instant level | AI or rubric grades on submit → sets `academic_level` immediately | new | F1-5 | TODO |
| F1-7 | AI group suggestion from result | suggest cohort(s) by level/branch; student may stay groupless or leave | new | F1-6, cohorts | TODO |
| F1-8 | Reception proposes a group → manager acceptance (toggleable) | `CenterSettings.require_group_acceptance`; if off, reception assigns directly | new (D-8) | F1-7 | TODO |

## Feature 2 — Student list page: stats, filters, comparison, actions
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F2-1 | Student profile fields (location, previous school) | exposed on read/update + filterable | new (D-1) | — | DONE |
| F2-2 | Block / unblock a student (soft, ≠ withdrawn) | `POST /students/{id}/block` + `/unblock`; blocked excluded from active ops; audited | new (D-2) | — | DONE |
| F2-3 | Rich filters: status, branch, cohort(with/without), level, gender, age range, location, school, teacher, join-date range | `GET /students/?...`; type-checked → 400 not 500 | extend (django-filter) | F2-1 | DONE |
| F2-4 | Stats snapshot endpoint | `GET /students/stats/` → totals, with/without group, blocked, by status/branch/level, joined/left in window | new selector | F2-2 | DONE |
| F2-5 | Comparison/delta endpoint | `GET /students/comparison/?metric=joined\|left&unit=hour\|day\|week\|month\|year` → current vs previous + delta | new selector (uses `EnrollmentEvent.created_at`, a datetime → hourly works) | F2-4 | DONE |
| F2-6 | Race-safety: remove-from-group while attendance is being taken | `move_student`/unenroll under `select_for_update`; attendance write tolerates a mid-session membership change | harden existing | cohorts/attendance | TODO |

## Feature 3 — Teacher dashboard
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F3-1 | Dynamic lesson types (Video/Speaking/Main/Hangout…) | manager CRUD `/schedule/lesson-types/`; `Lesson.lesson_type` FK | new (D-3) | — | DONE |
| F3-2 | Teacher dashboard aggregate | `GET /teachers/dashboard/` → my students, groups, level-groups, next lesson(+type), upcoming exams, expected graduations, warnings, forms-to-fill | new selector | F3-1, F3-3 | DONE (`apps.teachers` `TeacherDashboardView` + `teacher_dashboard` selector) |
| F3-3 | Forms/surveys engine (anonymous optional) | `apps.forms`: build (`Form`+ordered `FormField`s, 8 field types) → publish → submit (`FormResponse`/`FormAnswer`, per-type+required validation) → `responses/` + aggregate `summary/`. Anonymous (drops respondent), one-per-respondent dedupe (partial unique on dedupe_token; `allow_multiple` opt-out). forms:read/write; responders see only published | new app | — | DONE |
| F3-4 | Manager views + AI-analyzes form responses with charts | reuse `reports` generators; AI summary + chart data | reuse+new | F3-3 | TODO |
| F3-5 | Staff meetings / next-meeting for teachers | `StaffMeeting` + surfaced on dashboard | new (D-9) | F3-2 | **DONE** (`apps.meetings`, `/api/v1/meetings/`): a manager (`meeting:write`) schedules a meeting + invites staff; invitees read + RSVP (accept/decline) without a separate read perm (IsAuthenticated + get_queryset row-scoping — managers see their branch, invitees see only their own); cancel (manager, scheduled-only); `upcoming/` lists the caller's upcoming; the teacher's `next_meeting` surfaces on `/teachers/dashboard/`. Branch-scoped; invitees are staff-only. |

## Feature 4 — Student dashboard, homework, library, messaging
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F4-1 | Student dashboard aggregate | `GET /students/me/dashboard/` → group, next lessons, open homework, recent grades, outstanding balance, pending rule-acks | new selector | F3-3 | DONE |
| F4-2 | Homework: see / submit / mark done | mostly exists (`assignments`) — confirm "mark done" + own-feed | reuse | — | PARTIAL(exists) |
| F4-3 | Multiple teachers + assistants per group | already exists (`CohortCoTeacher`: co_teacher/assistant) | reuse | — | DONE(exists) |
| F4-4 | In-app messaging: student↔teacher(s) text + images | `apps.messaging`: threads + participants + append-only messages (S3-key attachments), `/api/v1/messaging/threads/` (create/messages/read), strict participant isolation, unread counts, realtime via notifications dispatch, student↔staff safeguarding | new (D-6) | — | DONE |
| F4-5 | Library: dual approval (teacher+manager) + view-only / download toggle | `LessonFile.is_approved_teacher`/`is_approved_manager` (+`*_by`/`*_at` signers) + `is_downloadable`; maker-checker (teacher leg `content:approve` → manager leg `content:publish`, two **different** people, manager-role-gated, teacher-leg-first), `select_for_update` legs; `scoped_files` publishes to learners only when dual-approved; manager reaches its own scope ∪ pending files (least-privilege, not all-content); view-only blocks the learner download URL (staff bypass); `/files/{id}/approve-teacher` + `/approve-manager`. **Deviation (deliberate):** `is_downloadable` is **per-file** (set at manager approval), not a CenterSettings toggle — finer-grained (exam papers view-only while worksheets download). No data backfill in 0003: pre-existing CLEAN files start unapproved (greenfield; grandfathering would forge approvals). | extend content (D-7,D-8) | — | DONE |

---

## Build order (dependency-aware)
1. **F2 cluster** (student list/stats/filters/block) — self-contained, high value. ← *in progress*
2. D-3 + **F3-1** (lesson types) — small foundation.
3. D-5 + **F3-3/F3-4** (forms + AI analysis) — reused by F3 & F4.
4. **F3-2** teacher dashboard, then **F4-1** student dashboard.
5. **F4-5** library approval/download toggles.
6. **F4-4** messaging.
7. **F1** placement testing (largest; depends on AI + cohorts + acceptance toggle).
8. **F2-6** race-safety hardening.

## Open questions / assumptions (defaults chosen; override anytime in FEATURE_LIST.md)
- "month/level created by hand" → modeled as free-text `academic_level` + dynamic `LessonType`/cohort `level`; a "month" filter = join-date month bucket. Confirm if you meant named "level" + "month" lookup tables.
- Placement test vs `academics.Exam`: building placement as a SEPARATE entity (prospective students, no cohort) to avoid overloading the cohort-scoped Exam.
- "blocked" = soft bar (still enrolled), distinct from `withdrawn`.

---

# Round 2 ideas (FEATURE_LIST #5–24) — refined

**Reality checks (corrections to assumptions in the raw ideas):**
- There is NO `docs/Production Vision` doc yet (#13) — created as a stub `docs/production-vision.md` for the owner to fill; the fairness engine spec lives there.
- There is NO Cards implementation (#12) — net-new. Assumed meaning: physical **student access/ID cards** (QR/NFC) tied to attendance + a stored-value wallet. Confirm.
- "Fairness engine" (#13) is mostly NEW — only `TeacherProfile.salary_type`+`rate` (flat) exist today.
- Printer race-conditions (#19) are ALREADY solved (`claim_job` uses `select_for_update(skip_locked=True)`); #16 backend (per-branch `BranchAgent` job pull) exists — the desktop app is a separate client repo + even-distribution logic.

## Theme A — Dynamic org hierarchy, grades & tasks (#5, #6, #7, #20)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F5-1 | `RoleGrade` — per-tenant ordered role hierarchy (e.g. assistant < teacher < manager < CEO), editable per center | `apps.tasks.RoleGrade` (role unique, level); ungraded=0. `/api/v1/tasks/grades/` (read tasks:read; edit tasks:assign_any) | new app | DONE |
| F5-2 | `Task` + assignment: create/assign to a staff member or a whole department | `apps.tasks.Task` (title/desc/priority/status lifecycle/assignee/dept/branch/due/created_by). `/api/v1/tasks/` create + assign + transition + mine; scoped (assignee/dept/manager-branch) | new app `apps.tasks` | DONE |
| F5-3 | Hierarchy-gated assignment: you may task only equal/lower grades (configurable) | `can_assign` in service: actor_grade ≥ target_grade, else 403 cannot_assign_grade; `tasks:assign_any` (HOD) + superuser bypass. Enforced on create AND reassign | new | DONE |
| F5-4 | AI fair task auto-split across a department's staff | balance by current open-task load / capacity; "fair" vs "free" modes | reuse `ai` + new | TODO |
| F5-5 | CEO scope: all branches' data; manager scope: their 1–2 branches | extend RoleMembership/scoping to multi-branch CEO read | extend permissions | TODO |
| *related* | task templates, recurring tasks, SLA + escalation on overdue, task comments/attachments, Kanban board, dependencies | — | idea | — |

## Theme B — Assessment & mobile test-taking (#8) — extends F1 placement
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F8-1 | Dynamic answer types: multiple-choice, true/false (default), writing, reading, listening, speaking, vocabulary | per-question type; manager enables types | extend D-4 | TODO |
| F8-2 | Test session lockdown: timer, answer-only, **mobile-app only (web blocked by tenant flag)** | session token; `X-Client: mobile` gate + CenterSettings | new | TODO |
| F8-3 | Marking by AI / manager / permission-holder (default manager) | per-test grader policy | reuse ai | TODO |
| *related* | shared question bank, randomized order, anti-cheat (tab-switch/proctor photo), retake policy, pass certificate | — | idea | — |

## Theme C — AI usage-billing & content (#9)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F9-1 | AI library-material generation | manager requests; AI drafts a library item | reuse `ai` + `content` | TODO |
| F9-2 | Metered/usage billing for AI gen (NOT in plan; charged per use) | record cost per gen → platform invoice line; reuse `ai.AIRequest.cost_microusd` + `billing` | extend billing | TODO |
| *related* | per-tenant spend cap + alerts, prepaid AI credits, cost preview before generate | — | idea | — |

## Theme D — Communication / SMS campaigns (#10)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F10-1 | SMS campaign: send to a student filter/segment, scheduled (dynamic date) | reuse Eskiz client + `notifications`; Celery-scheduled | reuse+new | **DONE** (`apps.campaigns`): build a campaign against a student segment ({status?/cohort?} within a branch) → freeze every recipient + the phone it'll go to (primary guardian's, else student's own; phoneless = SKIPPED) → `send` once via the Eskiz client. Claim-then-send (DRAFT→SENDING in a locked txn, then SMS OUTSIDE the txn — no rollback-after-send, no double-blast); **resumable** (a crash-stranded SENDING campaign re-runs only its PENDING rows; counts recomputed from the rows); **deduped by phone** (siblings' shared guardian texted once); per-recipient send/save failures recorded, never abort the batch. Branch-scoped: reception/HOD run campaigns for their own branch only, director centre-wide. The campaign + recipients are the audit trail (who/what/landed). TODO: Celery async send for large blasts + scheduled send-at; **opt-out/consent (campaigns currently bypass NotificationPreference — wire a campaign do-not-contact before go-live)**; gateway-body failure detection (SENT = accepted, not delivered). |
| F10-2 | AI-assisted message templates with examples | low-cost AI drafts template variants | reuse ai | TODO |
| *related* | opt-out/consent, delivery-status tracking, cost estimate before send, Telegram/WhatsApp channels, segment by F2 filters | — | idea | — |

## Theme E — Finance & HR (#13 fairness, #14 expenses, #21 loans, #17 rewards, #23 absence-pay)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F14-1 | Expenses: create → approve → pay; dynamic payment methods (cash/card/…) admin-managed | `Expense` + `PaymentMethod` (dynamic) + approval state; permission-gated | new (finance) | DONE |
| F21-1 | Staff loan request → manager approve → cashier notified → disburse (cash/card) | `LoanRequest` state machine + notification to cashier | new (finance) | **DONE** (`apps.loans` + `loan` KIND of A-1): a loan is `kind="loan"` on the Approvals+Ledger engine — request → approve (maker-checker, no self-approval; segregation of duties extends to the **beneficiary** — the borrower can neither approve nor disburse their own loan) → cashier disburses (money OUT → immutable ledger row, named to the borrower). Borrower restricted to **staff** (no loans to students/parents, mirroring F17-1). Beyond a plain expense, a loan must be **repaid**: `LoanRepayment` records money IN against the disbursed loan (each its own ledger row), with an **outstanding balance** = disbursed − Σ repayments that must reach zero. Overpayment/repay-before-disburse blocked; repayments serialize under a row lock (no concurrent overpay); `loan:collect` gates recording. Decision lives in the unified `/api/v1/approvals/` queue; loan surface at `/api/v1/loans/`. |
| F13-1 | Fairness/salary engine: percentage-of-salary by performance/attendance, manager-set % | needs spec (docs/production-vision.md); compute payout | new | BLOCKED(spec) |
| F17-1 | Rewards: manager creates reward types (cash/holiday/…) and grants to teachers | `apps.rewards`: RewardType (cash/non-cash catalog) + RewardGrant (to staff). `/api/v1/rewards/types|grants/` + `mine`. CASH grant routes its payout through A-1 (a `reward`-kind ApprovalRequest → approve → cashier disburse → ledger); non-cash recorded. Recipient = staff only | new app | DONE |
| F23-1 | Absence → payment deduction; manager toggles discount-for-absence (with/without reason) | per-center policy in CenterSettings; finance hook | new + CenterSettings | TODO |
| *related* | expense categories+receipts, multi-level approval chains, payslips/payroll runs, petty-cash reconcile, budgets per branch, reward leaderboards | — | idea | — |

## Theme F — Student engagement, attendance sheets, achievements, discounts, cards (#15, #12)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F15-1 | Student app attendance sheet + paid-status of the monthly invoice + classroom rank | reuse attendance/finance/academics; student-scoped | reuse | **DONE** (`students.student_report`, `GET /api/v1/students/me/report/`): the signed-in student's per-lesson attendance sheet (+ rate), their bills paid-status (outstanding / has-overdue / latest invoice), and their OWN classroom rank — position + cohort size + own average only, NEVER a leaderboard (dignity DNA). Student-self (`me`, 404 not_a_student otherwise). TODO: parent view of children's report; opt-out of rank via CenterSettings. |
| F15-2 | Custom achievements: manager global / teacher own-group; teacher→manager request for global | `apps.achievements`: Achievement (scope global/group, status active/pending/rejected) + AchievementGrant (unique per student). `/api/v1/achievements/` create + approve/reject + grant + `mine` (student wall) + grants. Teacher group=active; teacher global=pending→manager approves. Grant guards (active-only, group-membership, dedupe 409) | new app | DONE |
| F15-3 | Teacher-given discounts, manager-approved | `discount` KIND of A-1: request (payload: student/percent\|fixed) → approve materializes a standing `finance.Discount` (auto-applied as a negative invoice line at next issue); discount_id stamped back as audit link | extend approvals | DONE |
| F12-1 | Cards: student access/ID cards (QR/NFC), card↔attendance, stored-value wallet | `Card` + scan check-in; manager creates/names card types | new | TODO(confirm) |
| *related* | streaks, parent-visible progress, points/badges, card top-up wallet, lost-card reissue | — | idea | — |

## Theme G — Printing (#16, #19)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F19-1 | Printer job race-safety | already done (`claim_job` skip_locked) | reuse | DONE(exists) |
| F16-1 | Even job distribution to all available printers (round-robin) in a branch | extend `claim_job`/enqueue to balance across `Printer`s | extend printing | **DONE** (`printing.claim_job`): on claim, a job is assigned to the LEAST-LOADED active printer in its branch (fewest in-flight picked/printing jobs, ties by id) — even round-robin distribution, no single printer swamped. No active printers → printer left unset (agent's default); inactive printers skipped. |
| F16-2 | Desktop print-agent app (separate client repo) | out of this backend's scope; backend `BranchAgent` API exists | reuse | N/A(client) |

## Theme H — Cover system (#17, #18)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F18-1 | Cover request: teacher asks cover for a lesson/period → manager approves OR open to teacher pool | `CoverRequest` state machine on a `Lesson` | new | **DONE** (`apps.covers`): request → assign / open-to-pool → claim, with the lesson's `teacher` actually reassigned on approval (the cover is real — new teacher takes attendance). Branch-scoped throughout; cover teacher must belong to the lesson's branch; busy-teacher reassignment caught by the schedule exclusion constraint → clean 409; lesson re-validated as still SCHEDULED at approve; one OPEN request per lesson (approved is historical → re-cover chain allowed). |
| F18-2 | Cover "global chat" channel for teachers to claim covers | realtime channel (reuse `infrastructure/websocket`) | reuse+new | TODO |
| *related* | substitute pool, auto-suggest available teachers, cover-pay differential | — | idea | — |

## Theme I — Compliance (#24)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F24-1 | Law/rule book uploaded by manager/CEO; penalties applied to staff/students on breach | `Rule` + `Penalty` (points/fine) + apply workflow | new | **PARTIAL** (`apps.compliance.Penalty`): student demerits tied to the rule book — a teacher/manager (`penalty:write`) issues a points penalty against a student (optionally citing a `Rule`); a manager (`penalty:waive`, a SEPARATE perm = segregation of duties) reverses it with a reason; waive is locked + active-only (no double-waive). Branch-scoped: a teacher can only penalise/see their own branch's students; the student + guardians read their OWN record (`/api/v1/rulebook/penalties/`). TODO: staff penalties; point-threshold auto-escalation; FINE penalties as an A-1 money kind. |
| *related* | incident reports, appeal workflow, penalty-point decay, audit trail (reuse `audit`) | — | idea | — |

## Cross-cutting (#22)
| # | Feature | Acceptance | Status |
|---|---------|-----------|--------|
| X-1 | Performance: every list/metric accurate + N+1-free | add `select_related`/`prefetch_related`, query-count tests (`django_assert_max_num_queries`) per list | ONGOING |

## Round-2 data-model additions
`RoleGrade`, `apps.tasks.Task`, `PaymentMethod`, `Expense`, `LoanRequest`, `RewardType`/`RewardGrant`,
`Achievement`(+grant/request), `Card`(+scan/wallet), `CoverRequest`, `Rule`/`Penalty`, SMS `Campaign`,
+ answer-type extension on placement questions, + CenterSettings toggles (absence-discount policy, web-test-block, AI-material-billing).

## Build order (round 2 inserted)
After F2: **F3-1 lesson types** → **Expenses (F14-1)** → **Staff loans (F21-1)** → forms engine (F3-3) →
dashboards (F3-2/F4-1) → tasks+hierarchy (F5) → assessment/mobile (F8) → the rest by value.
