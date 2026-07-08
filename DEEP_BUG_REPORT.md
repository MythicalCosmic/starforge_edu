# Starforge EDU — Deep Bug Report

**Status:** 🔄 In progress — round 1 hunting
**Date:** 2026-07-08 · **Branch:** `day1-build` · **Base commit:** `dce7b83`

---

## What this report is

A second, independent bug hunt over the whole project, run **after** and **disjoint from** `DEEP_AUDIT_REPORT.md`.

`DEEP_AUDIT_REPORT.md` (2026-07-03) already logged **346 issues** — 100 confirmed, 246 unverified leads, 4 dismissed. Everything in that file is **out of scope here**. Every hunter in this pass is handed an exclusion index built from it (346 titles + `file:line`) and is instructed to refute-and-drop any finding that restates one.

### Why a second pass finds anything at all

The prior audit fanned out **one reader per app** (48 agents, ~1 app each). That method is strong on *intra-app* defects and structurally blind to:

| Blind spot | Why per-app readers miss it |
|---|---|
| Cross-app signal graphs | Sender in app A, receiver in app B — neither reader sees both halves |
| Tenant/cache-key collisions | The bug is the *absence* of a schema namespace, visible only across apps |
| Celery ↔ web races | The task and the view live in different files, owned by different readers |
| ORM aggregation fan-out | Needs the query *and* the model graph together |
| Migration ↔ model drift | Needs a diff of two directories, not a read of one |
| Admin / management commands | Not part of any app's request path |
| Regressions in the fix commit | `dce7b83` postdates the audit entirely |

So this pass hunts **by lens, not by app**.

## Method

- **Hunt:** cross-cutting hunter agents, each owning one lens, each required to cite `file:line` and quote the offending code.
- **Verify:** every candidate finding is attacked by **two independent adversarial refuters** with disjoint mandates:
  - *Lens A — factual correctness:* does the quoted code exist and does it really misbehave? Is there an upstream guard?
  - *Lens B — reachability & novelty:* is it reachable by a real actor? Is it a duplicate of a prior finding, or already fixed in `dce7b83`?
- A finding is **CONFIRMED** only if **both** refuters fail to break it. One refuter → **PLAUSIBLE**. Both → dropped (and listed, with the reason, so the ground isn't re-walked).
- Refuters default to `refuted=true` when they cannot positively confirm the defect from the code. This biases the report toward **fewer, harder** findings.

## Scope

Every app (38), plus `core/`, `config/`, `celery_tasks/`, `infrastructure/`, `docker/`, `scripts/`, top-level `tests/`.

## Exclusions (already covered — do not re-report)

Prior-audit finding classes, all considered closed for this report:
`PUT-behaves-as-PATCH` · `HEAD 405 divergence` · pure test-gaps · pure dead code · the four bugs fixed in `dce7b83`
(core `?ordering=--field`, `allocate_manual` per-line allocation, `due_day_of_month=0`, Payme non-dict `params`).

---

## Ground truth: the suite is no longer green on a fresh DB

The prior audit's headline was "**fresh DB, `--create-db`: 1542 passed, 0 failed**." I re-ran the same gate today and got **7 failed, 1537 passed, 6 skipped**. All 7 are in `apps/schedule/tests/test_schedule.py`:

```
test_materialize_counts_and_holiday_skip
test_materialize_idempotent
test_conflict_overlap_raises_409[teacher|cohort|room]
test_bulk_reschedule_emits_one_rescheduled_per_moved_lesson
test_deactivating_rule_clears_future_lessons_and_stops_regeneration
```

### Finding G-1 · [MEDIUM][test-quality] Schedule tests are wall-clock-date-fragile — the suite silently rots and now fails on a clean DB

- **Where:** [apps/schedule/tests/test_schedule.py:41](apps/schedule/tests/test_schedule.py#L41), `:59`, `:63`, `:116`, `:129` — and the mechanism at [apps/schedule/services/__init__.py:95](apps/schedule/services/__init__.py#L95),`:107`.
- **Root cause:** The tests pin the rule window to `start=date(2026, 7, 6)` (a Monday) with `BYDAY=MO`. `test_conflict_overlap_raises_409` uses a **single-day** window `end=date(2026, 7, 6)`. `materialize_rule` correctly skips any occurrence at/before `now`:
  ```python
  now = timezone.now()
  kept = [lf for lf in existing if ... or lf.starts_at <= now]
  for starts_at, ends_at in _rule_occurrences(rule):
      if starts_at <= now or starts_at in kept_starts:
          continue
  ```
  On the audit date (2026-07-03) `2026-07-06` was in the **future**, so lessons materialized, overlapped, and the tests passed. Today (2026-07-08) that Monday is in the **past**, so the single-day rule materializes **zero** lessons → no overlap → `DID NOT RAISE`. The count/idempotent/reschedule/deactivate tests fail for the same reason (fewer future occurrences than the hardcoded expectation).
- **Why it matters:** This is not a product defect — `materialize_rule` is behaving correctly. It is a **suite-integrity** defect: the "0 failures on fresh DB" ground truth the whole audit rests on is now false purely from calendar drift, and it will keep drifting. A genuinely broken overlap constraint would now be **indistinguishable** from this calendar rot — the safety net that should catch a real schedule regression is dead. Fix: make the window relative to `timezone.now()` (e.g. `today + 7d … + 60d`) or freeze time.
- **Verified:** `date(2026,7,6).weekday() == 0` (Monday); `date.today() == 2026-07-08`; reproduced all 3 `test_conflict_overlap_raises_409` params failing with "DID NOT RAISE".

---

## Round 1 — cross-cutting lens hunt (14 lenses)

13 raw candidates → **11 CONFIRMED, 2 PLAUSIBLE, 0 refuted** (both refuters passed all that survived). None duplicate the prior 346. Ordered by severity. **Status** tracks fix state in this session.

### R1-01 · [HIGH][money] Click/Uzum checkout sends the Payment PK as the merchant reference, but the webhook resolves the invoice by `Invoice.number` → real online payments are ACKed to the provider yet never credited ✅ FIXED

- **Where:** [apps/payments/services/__init__.py:355](apps/payments/services/__init__.py#L355),`:367` (checkout) vs [apps/payments/webhook_views.py:99](apps/payments/webhook_views.py#L99),`:190` (webhook).
- **Root cause:** `_build_provider_checkout` passed `merchant_trans_id=str(payment.pk)` (Click) / `order_id=str(payment.pk)` (Uzum). The provider echoes that reference back on the completion callback, where `click_webhook_view`/`uzum_webhook_view` do `Invoice.objects.filter(number=<ref>).first()`. Since `Invoice.number` is a formatted string (`INV-2026-…`), `filter(number="42")` returns `None` → the `if invoice is not None:` body is skipped → `mark_webhook_processed` still runs → the provider gets `ERROR_SUCCESS`. **Every real Click/Uzum payment is lost.** Payme (the sibling) correctly uses `invoice.number`; the existing tests never caught it because they call `process_click_complete(invoice=inv)` directly, bypassing checkout.
- **Fix:** checkout now emits `account["invoice"]` (= `invoice.number`), matching the webhook resolution and Payme. Regression test asserts the checkout payload's `merchant_trans_id`/`order_id` equals `invoice.number` and not the payment PK (round-trip contract).
- **Verified:** 2 refuters passed; my own read of checkout + both webhooks + `process_*` confirmed; new parametrized test green.

### R1-02 · [HIGH][money] Click/Uzum amount check compares the callback exactly against a fractional `total_uzs`, but checkout rounds to whole soum → any fractional-total invoice is permanently unpayable online ✅ FIXED

- **Where:** [apps/payments/services/__init__.py:350](apps/payments/services/__init__.py#L350) (checkout round) vs `_assert_provider_amount` at `:682`.
- **Root cause:** checkout charges `int(total_uzs.quantize(1, ROUND_HALF_UP))` (whole soum — Click/Uzum transmit soum), so a 149999.99 invoice is charged 150000. The callback reports 150000, but `_assert_provider_amount` did `if reported != invoice.total_uzs` — `Decimal("150000") != Decimal("149999.99")` → `amount_mismatch` → the payment is rejected forever. Fractional totals arise from percentage discounts.
- **Fix:** `_assert_provider_amount` now compares against `total_uzs.quantize(1, ROUND_HALF_UP)` — the same rounding checkout applied. Whole-soum totals are unaffected (quantize is a no-op) and under-payment is still rejected (the provider must report the rounded charge). Added an `is_finite()` guard (NaN/Inf → 400, not a silent pass). Payme carries exact tiyin and guards in its own client, so it never reaches here. Two regression tests: fractional invoice now payable at the rounded soum; a one-soum-short callback still rejected.
- **Verified:** 2 refuters passed; my own read confirmed; both new tests green.

### R1-03 · [MEDIUM][money] AI task budget reconciliation (`record_usage`) re-charges the tenant token budget and re-calls the paid model on any `acks_late` re-execution ⏳ TODO

- **Where:** [apps/ai/services/__init__.py:237](apps/ai/services/__init__.py#L237) (guard) with [celery_tasks/ai_tasks.py:79](celery_tasks/ai_tasks.py#L79) (caller).
- **Root cause:** the idempotency guard keys off a status transition committed in a *separate, later* save, so a Celery re-delivery (at-least-once + `acks_late`) between the model call and the status commit re-reserves budget and re-invokes the paid model. Duplicate AI spend.
- **Status:** to fix — needs a durable per-AIRequest idempotency key checked+committed atomically before the model call.

### R1-04 · [MEDIUM][bug] Stacked/uncapped invoice discounts drive the sum of persisted `InvoiceLine` rows below zero while `Invoice.total_uzs` is clamped to 0 → `sum(lines) == total_uzs` invariant broken, student silently zero-billed ⏳ TODO

- **Where:** [apps/finance/services/__init__.py:257](apps/finance/services/__init__.py#L257) (clamp), root cause `:321`–`:333` (sibling per-item cap but no aggregate cap).
- **Status:** to fix — cap aggregate discount at the invoice subtotal so persisted lines can't sum below the clamped total.

### R1-05 · [MEDIUM][security] WebSocket consumers authorize only at connect; session-revocation (force-logout / password-reset / `token_version` bump) and role-revocation never terminate a live socket ⏳ TODO

- **Where:** [infrastructure/websocket/consumers.py:85](infrastructure/websocket/consumers.py#L85), also `apps/notifications/consumers.py:49`, `apps/attendance/consumers.py:63`.
- **Status:** to fix — periodic re-validation or a revocation broadcast that closes affected sockets. (Sibling of prior finding on logout not bumping `token_version` for iCal, but this is the live-socket vector, not the URL feed.)

### R1-06 · [MEDIUM][bug] A Redis/channel-layer error inside the `student_marked_absent` receiver propagates out of the post-commit hook → a committed attendance mark 500s and every remaining absent student in the batch loses their guardian notification ⏳ TODO

- **Where:** [apps/notifications/receivers.py:138](apps/notifications/receivers.py#L138) → `push_cohort_attendance` → `infrastructure/websocket/channel_layer.py:11` `group_send`.
- **Status:** to fix — isolate the push in a best-effort try/except so a realtime-layer outage can't fail a committed mark or drop the rest of the batch.

### R1-07 · [MEDIUM][security] Django admin login is exempt from all rate limiting → unlimited password brute-force / credential-stuffing against staff & superuser accounts on every tenant subdomain and the apex ⏳ TODO

- **Where:** [core/middleware.py:157](core/middleware.py#L157) — `ApiRateLimitMiddleware` only guards `/api/`, so `/admin/login/` is unthrottled.
- **Status:** to fix — extend the blanket limiter (or a dedicated one) to the admin login POST.

### R1-08 · [MEDIUM][bug] Offset pagination applies no unique pk tiebreaker → paging any list ordered on a non-unique column silently drops and duplicates rows across page boundaries ⏳ TODO

- **Where:** [core/listing.py:83](core/listing.py#L83) (`apply_filters` ordering) + `paginate`.
- **Status:** to fix — append `pk` as a deterministic final sort key whenever ordering is applied; add a cross-page no-drop/no-dup test. High blast radius (every list endpoint) so it gets its own batch + tests.

### R1-09 · [LOW][race] `transition_task` mutates an unlocked, pre-fetched `Task` row (check-then-act, no `select_for_update`) → concurrent transitions can bypass the state-machine graph (e.g. land a CANCELLED task in DONE) ⏳ TODO

- **Where:** [apps/tasks/services/__init__.py:127](apps/tasks/services/__init__.py#L127) — the only status-transition service that omits the row lock every sibling holds (approvals/covers/meetings/sales/loans/finance/achievements/printing all re-fetch under `select_for_update`).
- **Note:** refuter corrected the reported "CANCELLED with completed_at set" — `completed_at` stays coherent (same `update_fields`). The real harm is a forbidden transition (`CANCELLED→DONE`) via two racers reading the same `OPEN` pre-image. LOW (internal to-do state, recoverable, both actors already authorized).
- **Status:** to fix — one line: re-fetch `Task.objects.select_for_update().get(pk=task.pk)` inside the atomic.

### R1-10 · [LOW][bug] `dispatch_notification`'s per-channel idempotency guard is check-then-act with no row lock and no unique constraint on `NotificationDelivery(notification, channel)` → a concurrent Celery redelivery double-sends SMS/email/push for one event ⏳ TODO

- **Where:** [celery_tasks/notification_tasks.py:64](celery_tasks/notification_tasks.py#L64).
- **Status:** to fix — add a unique constraint on `(notification, channel)` (DB-backed idempotency) + `get_or_create`.

### R1-P1 · [MEDIUM][bug] (PLAUSIBLE — 1 refuter dissent) Nightly billing metering fans out per-tenant synchronously in a bare loop with no isolation → one center's exception aborts usage snapshots **and** subscription state-flips (`past_due`/`suspended`) for every center after it

- **Where:** [celery_tasks/billing_tasks.py:41](celery_tasks/billing_tasks.py#L41). Needs re-verification (the prior audit reported a *similar* class for other tasks; confirm this is the billing instance and not a duplicate) before fixing.

### R1-P2 · [LOW][money] (PLAUSIBLE — 1 refuter dissent) Invoice admin leaves `total_uzs` writable and its editable `InvoiceLine` inline never recomputes it → admin line edits silently desync the stored total from its lines

- **Where:** [apps/finance/admin.py:23](apps/finance/admin.py#L23). Low urgency (admin-only, trusted actor); fix by making `total_uzs` readonly + recompute on inline save.

### Also fixed this batch (batch-1 `dce7b83` regressions found while fixing the above)

- **B1-mypy-1:** `apps/finance/services/__init__.py` used `list[dict[str, Any]]` in `allocate_payment_lines` (added by `dce7b83`) without importing `Any` — mypy error, masked at runtime only by `from __future__ import annotations`. **Fixed** (added the import). Contradicts the memory's "mypy clean baseline" — batch-1 shipped two mypy regressions.
- **B1-mypy-2:** `core/listing.py:85` passed `str | None` to `order_by` (batch-1's `--field` fix) — mypy `arg-type` error. **Fixed** behavior-equivalently by guarding on `if ordering:` (narrows to `str`).

---

## Findings (round 2+ land below)

_Round 1 fixes committed in batches; round 2 hunt queued next._

---

## Appendix A — Refuted candidates

_Populated on completion. Recorded so future passes don't re-investigate them._
