# starforge_edu — 14-day plan to the FULL production-ready platform

**Supersedes `PLAN_5DAY.md`.** Decided 2026-06-02. We are NOT building an MVP — we're
building the whole production-ready product in 14 days: the operational core, the
money rails, the printing wedge, the AI suite, the camera analysis, the intelligence
layer, the student-engagement layer, supervised comms, and a per-center dedicated
deployment. Context: **3 real centers ready to buy (5k+ students, ~10 branches)**;
premium managed/dedicated-server/AI positioning (see `docs/PRODUCT_VISION.md`,
`docs/RESEARCH_UZ_MARKET.md`, and memory).

## Honesty contract (read once)
- "Production-ready" = **functioning, tested, safe, metered, deployable** — not
  "perfect." The heavy AI/CV pieces (camera analysis, speaking AI, CBT engine) ship at
  **real v1 depth and deepen with data**; we will NOT ship vapor (no "International"
  flex). Where a piece can't be fully done in its day, it ships as a working, honest
  v1 with the deepening tracked.
- **Every day ends green:** ruff + mypy(no new errors) + pytest(+coverage) + `manage.py
  check` + schema gen. Each new ViewSet ships with serializer, filter, `required_perm`,
  and tests. Commit per day.
- **Cross-cutting rules enforced everywhere** (not a phase): live backend permission
  checks (never trust client); per-center AI budget metering; fiscal/OFD on payments;
  biometric/telecom data stays on the center's in-country server; copyright-safe content
  (licensed/open/BYO/AI-generated only); child-safety on all comms.

## The leverage: build each ENGINE once, configure the rest
1. **Ledger** (double-entry money truth) → tuition, salary, rewards/points, book sales,
   procurement, refunds are all entries. Auto-reconciled vs Click/Payme/Uzum.
2. **Approvals engine** (`request → N approvals → cashier disburses → notify → ledger`)
   → payment-delay, discounts, partial-pay, salary-prep, procurement, event cost-split.
3. **Notifications dispatch** (one `dispatch(event)` → in-app/email/SMS/Telegram/push).
4. **Intelligence layer** (metric pipeline over attendance/grades/submissions/payments)
   → risk flags, family health, teacher value-added, branch ranking, reputation, journey.
5. **AI gateway** (Opus/Sonnet/Haiku tiering, Celery-only, prompt-cache, per-center
   budget) → feedback, summaries, mock gen + scoring, speaking examiner, moderation, games.
6. **Marketplace** (one store, two currencies: UZS + points) → books/materials + rewards.
7. **Edge agent** pattern (print agent + camera analyzer) → talk back to the center server.

---

## Phase 1 — Operational core (Days 1–5)
- **Day 1 ✅** Foundation lockdown: tenant-isolation invariant, OTP+JWT (tenant-bound),
  admin-in-tenant fix, test harness, CI coverage gate. (Done.)
- **Day 2 ✅** Reception (Student/Parent/Guardian/Teacher profiles) + org.Room + Audit
  trail (append-only, actor-attributed). (Done.)
- **Day 3 ✅** Cohorts (+ membership + co-teachers) + Schedule (lessons, holidays,
  recurring, room/teacher/cohort conflict detection). (Done.)
- **Day 4** Attendance (mark single + bulk-by-cohort, term summary, auto-absent Celery,
  guardian notify) + **Notifications dispatch** (in-app/email/SMS-Eskiz/Telegram/push,
  templates uz/ru/en, quiet hours, idempotency) + **i18n** (gettext, uz/ru/en) +
  basic **Reports** (enrollment, attendance, roster; Celery→S3).
- **Day 5** **Finance + Ledger + Approvals engine** — invoices/lines/discounts/refunds,
  the double-entry ledger, cashier shifts, outstanding balances, and the GENERIC
  approval workflow that powers delay/discount/partial-pay/salary/procurement/events.

## Phase 2 — Money rails, payroll, printing wedge (Days 6–8)
- **Day 6** **Payments**: Click (Prepare/Complete), Payme (JSON-RPC handler set), Uzum
  webhooks; idempotency + signature verify + replay protection; **fiscal/OFD receipt**
  hook; daily reconciliation; receipts. **Dignity flows** (delay/partial/discount) wired
  to the approvals engine. **Points** as a ledger currency + **redemption store** +
  **book/material marketplace** (one market, two currencies).
- **Day 7** **Fair payroll engine** (configurable rules: % of a teacher's student
  tuition, base+bonus, caps, per-cohort overrides, dry-run preview; salary-prep
  accept/reject) + **HR/contracts** (multi-year, equity/salary, raises) + **Departments
  + task distribution** (even-split / private tasks; open/closed/pending) + procurement.
- **Day 8** **Printing service** (the wedge): PrintJob/Printer/BranchAgent + job claim/
  status API for the edge agent, n-up/duplex paper-saving layouts, **paper-usage
  accounting** + per-cohort quotas, and the **content library** (copyright-safe:
  licensed/open/BYO-upload + AI-generated; signed S3; libmagic; file-type allowlist).

## Phase 3 — Academics + AI suite (Days 9–11)
- **Day 9** **Academics** (subjects, exams, grades, weighted term grades, transcripts
  PDF, grade audit, honor-roll/warning) + **Assignments** (create/submit/rubric/late/
  resubmit) + **Content** hierarchy & visibility scoping.
- **Day 10** **AI gateway** (per-center budget metering, Opus/Sonnet/Haiku tiering,
  Celery-only, prompt-cache, PII redaction) + **assignment feedback** + **content
  summarization** + **mock exams** (AI-generated, copyright-clean) + **AI band scoring +
  feedback** for writing.
- **Day 11** **AI speaking partner / IELTS simulator** (ASR→Opus examiner→TTS, full
  3-part test, instant band scores, voice-recording + progress graph; honest on
  pronunciation) + **CBT/typing simulator** (faithful test UI: timer, listening-once,
  highlighter, word counter).

## Phase 4 — Intelligence + engagement + comms (Days 12–13)
- **Day 12** **Intelligence layer** (one metric pipeline → many views): **risk
  prediction** (rules-based first), **family health** ("needs attention", neutral),
  **teacher value-added** performance (not raw scores; visibility voted), **branch
  ranking**, **student journey timeline**, **reputation dashboard** (internal score +
  moderated public reviews), **referral system**, **equipment tracking**, **smart group
  matching** (reuses the Day-3 schedule/availability engine).
- **Day 13** **Student engagement + communication**: gamified competition
  (Blooket-style, AI-generated content, points/badges), **podcasts** (TTS, graded),
  **focus board**, living yearbook; **supervised in-app chat + groups** (AI moderation,
  uz/ru/en profanity filter, weekly audit, center-provisioned logins) + **Telegram
  notify**; **co-watch** (short approved YouTube clips). **Camera analysis edge agent**
  (separate repo/agent): **audio-first** pipeline (ASR→LLM lesson summary) + presence
  detection scaffold; data stays on the center's box; teacher-sees-own; consent.

## Phase 5 — Dynamic permissions, harden, ship (Day 14)
- **Day 14** **Dynamic permissions** (center-configurable roles + granular perms, still
  enforced live server-side) + **security** (CORS/axes/CSP, field-encryption for PII +
  biometric, no-trust-client audit) + **observability** (Sentry, health checks,
  request-ID, JSON logs) + **per-center dedicated deployment** (provisioning automation,
  wildcard TLS, daily backups, migrate-on-deploy, biometric/telecom stays in-country,
  per-center AI budget enforcement) + **E2E smoke** + tag **v1.0.0** + onboard the 3
  real centers.

---

## Sequencing logic
- The 3 centers **pay** for ops + payments + the camera that actually works → Phases 1–3
  + camera are the revenue spine, front-loaded.
- The **engines** (ledger, approvals, dispatch, intelligence, AI gateway, marketplace,
  edge agent) are built once early and reused — that's what makes 14 days feasible.
- The **student-joy + intelligence + reputation** layers (Phase 4) are the retention
  moat, layered on the spine.
- **Day 14 hardens everything and deploys** to the dedicated per-center model.

## What stays explicitly "v1 depth, deepen with data" (honest)
Camera video understanding (audio-first at launch), speaking-AI pronunciation band,
group-matching optimization (suggestions first), risk-prediction ML (rules first),
public-review anti-gaming. All ship working + safe; precision improves post-launch.

## Top risks
Tenant isolation (proven D1) · payment + fiscal/OFD correctness (money — test hard) ·
copyright on library/mocks (licensed/open/AI-only) · child-safety on comms ·
biometric data localization · AI cost blowout (per-center budget metering) · scope:
hold the engine-first discipline or the 14 days slip.
