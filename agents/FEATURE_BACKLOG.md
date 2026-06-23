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
| **A-1** | **Approvals + Ledger engine** (`apps.approvals`: ApprovalRequest + LedgerEntry): `request → approve/reject → cashier disburses → immutable ledger row` | Expenses, staff loans, procurement (#15), payment-delay (#5), discount requests (#5/#7), partial-pay, salary-prep (#7), event cost-split (#14), book cash-sales (#8), rewards/points payouts (#6/#7) — ALL one engine. The ledger is the anti-fraud moat ("money can't disappear"). | **CORE DONE** + **effect-at-approve kinds live**: `discount` (→ standing Discount, F15-3) and `payment_delay` (→ reversible invoice due-date extension). **Maker-checker enforced** (no self-approval) + **reject-after-approve reverses the effect** (adversarial-review hardening). **`DiscountViewSet` bypass closed**: discounts are read-only over CRUD (granted only via the approval `discount` KIND); direct create/edit/delete blocked, ended only via the `deactivate` action. TODO: notify-on-disburse, multi-step approval chains, fold in Expenses, build loans/procurement as kinds. |
| **A-2** | **Dynamic permission system** (CRITICAL/security): center-configurable custom roles + granular permissions, **enforced live server-side**, instant revocation | Replaces the static `ROLE_PERMISSION_MATRIX`. Born from a real breach (localStorage-only auth). Every gated endpoint depends on it. | TODO |
| **A-3** | **Intelligence/metrics pipeline**: one computed feed over attendance/grades/submissions/payments | Risk flags ⭐ (dropout = #1 revenue leak), family-health, branch ranking, teacher value-add, journey timeline — all views on it. Start as transparent RULES, not black-box AI. | TODO |
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
| D-6 | `Thread` + `Message` + `MessageAttachment` (student↔teacher) | F4 messaging | TODO |
| D-7 | `ContentLibrary`/`LessonFile` approval + `is_downloadable`/`view_only` flags | F4 library | TODO |
| D-8 | `CenterSettings` booleans for each dynamic on/off knob (group-acceptance, downloads, library-approval, ...) | all | PARTIAL |
| D-9 | `MeetingSlot`/`StaffMeeting` (teacher meetings, next-meeting) | F3 | TODO |

---

## Feature 1 — Reception onboarding + placement testing + AI group suggestion
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F1-1 | Department CRUD with job description + head | already exists (`org.Department` + `DepartmentViewSet`) | reuse | — | DONE(exists) |
| F1-2 | Placement test bank: create/edit tests + questions | `POST/PATCH /placement/tests/`; manager-owned | new (D-4) | — | TODO |
| F1-3 | AI-generate / AI-recreate a placement test (draft) | reuse `ai.ExamGeneration` plumbing; output is a DRAFT | reuse+new | F1-2 | TODO |
| F1-4 | Manager approval of an (AI-)changed test before it goes live | approval state machine: `draft→pending→approved`; only manager approves | new (D-4) | F1-2 | TODO |
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
| F3-2 | Teacher dashboard aggregate | `GET /teachers/dashboard/` → my students, groups, level-groups, next lesson(+type), upcoming exams, expected graduations, warnings, forms-to-fill | new selector | F3-1, F3-3 | TODO |
| F3-3 | Forms/surveys engine (anonymous optional) | manager/teacher builds form; recipients fill; `Form/FormResponse` | new (D-5) | — | TODO |
| F3-4 | Manager views + AI-analyzes form responses with charts | reuse `reports` generators; AI summary + chart data | reuse+new | F3-3 | TODO |
| F3-5 | Staff meetings / next-meeting for teachers | `StaffMeeting` + surfaced on dashboard | new (D-9) | F3-2 | TODO |

## Feature 4 — Student dashboard, homework, library, messaging
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F4-1 | Student dashboard aggregate | `GET /students/me/dashboard/` → group, next lessons, open homework, recent grades, outstanding balance, pending rule-acks | new selector | F3-3 | DONE |
| F4-2 | Homework: see / submit / mark done | mostly exists (`assignments`) — confirm "mark done" + own-feed | reuse | — | PARTIAL(exists) |
| F4-3 | Multiple teachers + assistants per group | already exists (`CohortCoTeacher`: co_teacher/assistant) | reuse | — | DONE(exists) |
| F4-4 | In-app messaging: student↔teacher(s) text + images | `Thread`/`Message`/attachment; many teachers per thread | new (D-6) | — | TODO |
| F4-5 | Library: dual approval (teacher+manager) + view-only / download toggle | `is_approved_teacher`/`is_approved_manager`, `is_downloadable`; toggles in CenterSettings | extend content (D-7,D-8) | — | TODO |

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
| F5-1 | `RoleGrade` — per-tenant ordered role hierarchy (e.g. assistant < teacher < manager < CEO), editable per center | manager configures order/level numbers; drives "can assign to lower grade" | new model + CenterSettings | TODO |
| F5-2 | `Task` + assignment: create/assign to a staff member or a whole department | `Task` (title, body, due, status, assignee, dept, created_by) | new app `apps.tasks` | TODO |
| F5-3 | Hierarchy-gated assignment: you may task only equal/lower grades (configurable) | enforced in service via RoleGrade; manager/CEO/permission-holder bypass | new | TODO |
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
| F10-1 | SMS campaign: send to a student filter/segment, scheduled (dynamic date) | reuse Eskiz client + `notifications`; Celery-scheduled | reuse+new | TODO |
| F10-2 | AI-assisted message templates with examples | low-cost AI drafts template variants | reuse ai | TODO |
| *related* | opt-out/consent, delivery-status tracking, cost estimate before send, Telegram/WhatsApp channels, segment by F2 filters | — | idea | — |

## Theme E — Finance & HR (#13 fairness, #14 expenses, #21 loans, #17 rewards, #23 absence-pay)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F14-1 | Expenses: create → approve → pay; dynamic payment methods (cash/card/…) admin-managed | `Expense` + `PaymentMethod` (dynamic) + approval state; permission-gated | new (finance) | DONE |
| F21-1 | Staff loan request → manager approve → cashier notified → disburse (cash/card) | `LoanRequest` state machine + notification to cashier | new (finance) | TODO |
| F13-1 | Fairness/salary engine: percentage-of-salary by performance/attendance, manager-set % | needs spec (docs/production-vision.md); compute payout | new | BLOCKED(spec) |
| F17-1 | Rewards: manager creates reward types (cash/holiday/…) and grants to teachers | `RewardType` + `RewardGrant` | new | TODO |
| F23-1 | Absence → payment deduction; manager toggles discount-for-absence (with/without reason) | per-center policy in CenterSettings; finance hook | new + CenterSettings | TODO |
| *related* | expense categories+receipts, multi-level approval chains, payslips/payroll runs, petty-cash reconcile, budgets per branch, reward leaderboards | — | idea | — |

## Theme F — Student engagement, attendance sheets, achievements, discounts, cards (#15, #12)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F15-1 | Student app attendance sheet + paid-status of the monthly invoice + classroom rank | reuse attendance/finance/academics; student-scoped | reuse | TODO |
| F15-2 | Custom achievements: manager global / teacher own-group; teacher→manager request for global | `Achievement` + grant + request-approve | new | TODO |
| F15-3 | Teacher-given discounts, manager-approved | `discount` KIND of A-1: request (payload: student/percent\|fixed) → approve materializes a standing `finance.Discount` (auto-applied as a negative invoice line at next issue); discount_id stamped back as audit link | extend approvals | DONE |
| F12-1 | Cards: student access/ID cards (QR/NFC), card↔attendance, stored-value wallet | `Card` + scan check-in; manager creates/names card types | new | TODO(confirm) |
| *related* | streaks, parent-visible progress, points/badges, card top-up wallet, lost-card reissue | — | idea | — |

## Theme G — Printing (#16, #19)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F19-1 | Printer job race-safety | already done (`claim_job` skip_locked) | reuse | DONE(exists) |
| F16-1 | Even job distribution to all available printers (round-robin) in a branch | extend `claim_job`/enqueue to balance across `Printer`s | extend printing | TODO |
| F16-2 | Desktop print-agent app (separate client repo) | out of this backend's scope; backend `BranchAgent` API exists | reuse | N/A(client) |

## Theme H — Cover system (#17, #18)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F18-1 | Cover request: teacher asks cover for a lesson/period → manager approves OR open to teacher pool | `CoverRequest` state machine on a `Lesson` | new | TODO |
| F18-2 | Cover "global chat" channel for teachers to claim covers | realtime channel (reuse `infrastructure/websocket`) | reuse+new | TODO |
| *related* | substitute pool, auto-suggest available teachers, cover-pay differential | — | idea | — |

## Theme I — Compliance (#24)
| # | Feature | Acceptance | New/Reuse | Status |
|---|---------|-----------|-----------|--------|
| F24-1 | Law/rule book uploaded by manager/CEO; penalties applied to staff/students on breach | `Rule` + `Penalty` (points/fine) + apply workflow | new | TODO |
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
