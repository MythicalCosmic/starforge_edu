# Starforge Edu — Product Vision & Idea Backlog

> Source: founder brain-dump (2026-06-01). The founder worked as a teacher at an
> Uzbek education center and was a student before that — **most ideas are born
> from real pain and joy.** Captured faithfully; lightly organized. Items marked
> **[challenge]** are Claude's notes/questions to validate via deep research on
> how Uzbek education centers actually operate — the founder explicitly asked to
> be challenged with better ideas.

## 0. Positioning (correction)
- This is for **education centers** (tutoring centers, language schools, exam-prep
  centers), **NOT K-12 schools.** Update all framing accordingly.
- Frontend design is going well (separate track).
- **North star: kill paper.** Going paperless is the single biggest problem in
  Uzbek education centers today. Even centers that *have* a system still run
  paper attendance sheets because the system is bad. Every feature should remove
  a sheet of paper or a manual ritual.

## 1. Printing service — the wedge (almost no competitor)
- **Built-in content library shipped with the app.** Based on the center's focus,
  pre-load a large default library. Example: an English-only center gets tons of
  English books by default — usable by printers (to print), students (to read),
  teachers (to teach from), and anyone studying at that center.
- **Custom print layouts to save paper** — e.g. 2-up (two students' pages on one
  sheet), n-up, duplex, etc. Paper-saving is a first-class feature, not an option
  buried in a driver.
- **Paper-usage accounting.** The printer operator records pages used per job; the
  center sees total spend on paper over time. A setting (toggleable by CEO/manager
  or whoever has permission) can *require* the operator to log pages per job.
- The branch print agent (separate repo) does the actual CUPS work; this app owns
  the queue, library, layouts, quotas, and accounting.
- **[challenge]** Library licensing/copyright for bundled books in UZ — what's
  legally distributable? Could be the biggest risk *and* the biggest moat.

## 2. Extreme notifications — "don't let anyone miss anything"
- No teacher, auditor, manager, or CEO should ever miss a notification.
- "Bait the user" — aggressive, persistent, multi-channel until acknowledged.
- **[challenge]** Persistent-until-ack + escalation (in-app → push → SMS → call)
  with read receipts and an audit trail of who saw what when. Risk: notification
  fatigue making people ignore everything. Propose per-event severity tiers and
  mandatory-ack only for the few that truly matter.

## 3. Departments + task management
- Someone with enough permission creates a department, adds people, assigns tasks.
- **Whole-department task → distributed evenly** so everyone does an equal share;
  nobody slacks or is missed. Everyone works equally.
- Can also assign a task to a **single person** (private tasks — very common in
  education centers).
- Department lifecycle: **open / closed / pending.**
- **[challenge]** "Distributed evenly" needs a concrete rule: round-robin? by
  current load? by skill? Define the fairness algorithm and make it visible.

## 4. Dynamic permission system — CRITICAL (security)
- **Permission-locked, not just role-locked.** Fully dynamic per center — every
  education center is different. Create custom roles (e.g. "assistant"), define
  their permissions, assign to one or many users.
- **HARD REQUIREMENT — backend checks live permissions on every request.**
  Horror story from the founder's old workplace: permissions were stored in
  **localStorage and checked only on the frontend**; logging in as a normal
  teacher, he had full admin control in **under a minute**. The backend never
  verified. This must never happen here: the server is the sole authority, checks
  permissions live (no client-trusted state), and revocation takes effect
  immediately.
- This extends the current static `ROLE_PERMISSION_MATRIX` toward
  center-configurable roles + granular permissions, still enforced server-side.

## 5. Payments (born from personal pain as a student)
- Connect **Click, Payme**, and other popular UZ rails (Uzum, etc.).
- **Payment-delay request:** a student requests a delay to the teacher / manager /
  CEO / whoever handles payments. If approved, the payment moves to a date the
  student chooses (within approved bounds). Built so shy students don't have to
  ask in person.
- **Discount requests:** a teacher can request a discount for a specific student
  from the manager; on approval it applies — **percentage or fixed amount.**
  (Founder studied hard while barely affording it; managers gave discounts.)
- **Partial / "pay what you can" online payments:** pay any portion (half, some
  %), not just the full amount. Attach a **note explaining your situation** to the
  manager/cashier. They review, accept, and **assign a pay-by date.**
- **Daily reminders** until the balance is paid (so you remember and pay).
- Whole flow is designed to remove shame and friction from paying tuition.

## 6. Branch management
- CEO / manager (with permission) can **create branches, view details, and assign
  workers and teachers** to a branch.

## 7. Fair salary / revenue-share engine (founder wants FULL fairness)
- **Configurable payout rules in-app.** Example: a teacher earns X% of the
  payments from their own students. Founder earned 15% while others got 25% and
  wants transparent, fair, auditable rules — no opaque favoritism.
- **Salary-preparation workflow:** a teacher can ask an assigned **cashier to
  prepare their salary**; the cashier can **accept or reject** (sometimes there's
  literally no money in the till — that case must be representable).
- **[challenge]** Rules engine vs. hardcoded formulas: design a small,
  center-editable rule DSL (per-student %, base + bonus, caps, per-cohort
  overrides) with a dry-run preview and full audit.

## 8. Book selling (centers sell books themselves)
- Buy a book in-app and **pay online** → get a **QR code or short code** → show/
  tell it to the seller → seller confirms and receives the money.
- **Cash option:** the seller (usually the printer operator, with permission)
  **records the cash sale in-app** so it's registered and visible to others — the
  money can't silently disappear. Accountability is the point.

## 9. Assistant role (concrete example of the dynamic-role system)
- Create an "assistant" role, assign to a teacher or teachers.
- Work is mostly during lesson time, but assistants also receive **private
  messages and private assignments** from teachers (e.g. "start the lesson",
  "print this" — via the app, so all paper info is captured too → more
  paper-spend visibility).
- **Calling absent students:** a setting to **auto-send a message from the
  assistant's phone to the parent**, or a **call button** using the student's
  stored numbers.

## 10. In-app chat
- Telegram-like messaging, but nicer — talk inside the app (DMs, likely groups).

## 11. HR & contracts
- An **HR department**.
- Hire workers on **contracts** (e.g. a 4-year contract) with **equity or salary**
  assigned; salary can **increase/decrease** over time.
- **[challenge]** "Equity" in an education center is unusual — clarify whether this
  means profit-share, bonus pool, or literal ownership.

## 12. Rule book / policy acknowledgment
- Each center has a **rule book**. **Everyone** (not only teachers) must be
  **forced to read and accept** it.
- **Role/permission-filtered content:** teachers' rules differ from printers'
  rules; a cashier shouldn't see teacher-only rules. Filter what each person must
  read by their role/permissions.
- Implies versioning + re-acknowledgment when rules change, with an audit trail.

## 13. "Keep an eye" / monitoring
- Some activity-monitoring/oversight feature "everyone uses these days."
  (Under-specified — needs definition. Possibly an activity dashboard / audit feed
  / live ops view.)

---

## Themes Claude sees across the dump (to discuss)
1. **Accountability & anti-fraud** runs through everything (cash logging, live
   permission checks, paper accounting, fair payouts, audit). This is arguably the
   real product, not "school management."
2. **Dignity / shame-reduction** is a genuine differentiator (partial pay, delay
   requests, discount requests — all in-app, no in-person asking).
3. **Paper elimination** is the measurable promise — consider a per-center
   "paper/money saved" dashboard as a retention + sales hook.

## Next step the founder requested
- Deep research on how Uzbek education centers actually operate (payments, payroll
  norms, Click/Payme flows, book-selling, staffing, regulations), then **challenge
  these ideas and propose better ones.** Run via the deep-research skill when ready.
- More ideas are coming ("I got so much more") — this file is append-only; keep adding.
