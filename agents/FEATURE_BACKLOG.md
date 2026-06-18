# Feature Backlog

This is the decomposition of `FEATURE_LIST.md` (the owner's raw idea inbox) into
discrete, buildable features. **Owner adds ideas to `FEATURE_LIST.md`; this file
is the engineering breakdown.** Each item has acceptance criteria + a STATUS.

Roles mapping (from `core/permissions.py`): **manager = `director`** (and `head_of_dept`
for dept-scoped), **receptionist = `registrar`**. New resources get matrix entries.

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED(reason)`.

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
| F3-1 | Dynamic lesson types (Video/Speaking/Main/Hangout…) | manager CRUD `/schedule/lesson-types/`; `Lesson.lesson_type` FK | new (D-3) | — | TODO |
| F3-2 | Teacher dashboard aggregate | `GET /teachers/dashboard/` → my students, groups, level-groups, next lesson(+type), upcoming exams, expected graduations, warnings, forms-to-fill | new selector | F3-1, F3-3 | TODO |
| F3-3 | Forms/surveys engine (anonymous optional) | manager/teacher builds form; recipients fill; `Form/FormResponse` | new (D-5) | — | TODO |
| F3-4 | Manager views + AI-analyzes form responses with charts | reuse `reports` generators; AI summary + chart data | reuse+new | F3-3 | TODO |
| F3-5 | Staff meetings / next-meeting for teachers | `StaffMeeting` + surfaced on dashboard | new (D-9) | F3-2 | TODO |

## Feature 4 — Student dashboard, homework, library, messaging
| # | Feature | Acceptance | Reuse/New | Deps | Status |
|---|---------|-----------|-----------|------|--------|
| F4-1 | Student dashboard aggregate | `GET /students/me/dashboard/` → homework, next lesson, forms-to-fill, grades, library access | new selector | F3-3 | TODO |
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
