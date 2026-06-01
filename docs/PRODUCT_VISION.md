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
  payments from their own students. NOt favoritism
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

## 14. Team events + transparent cost-splitting
- A place to handle money for **team events** (e.g. the team goes somewhere to
  relax, paid by the center).
- **Configurable who pays**, set by a permission-holder: split evenly among
  attendees, fully covered by the center, or a mix — "some are greedy, some are
  generous; every center is different."
- **Event announcement + RSVP:** a fun notification to all staff — e.g.
  "[Center] we're going to X to relax — want to come? [Join]". One button to RSVP.
- **Full fair detail shown up front:** how much *you'll* be charged, how much
  you're expected to bring, what food there'll be, when we leave, when we're back.
  Accept or reject.

## 15. Procurement / purchase requests (automate "ask the manager for money")
- Today a worker who wants something (e.g. the media team wants a new camera)
  waits for the manager to show up, discuss, and release cash.
- Automate it: submit a **request for an item** → manager approves → **cashier is
  auto-notified to ready the money** (cashier can delay if the till is empty) →
  done.
- **[challenge — Claude's key insight]** This is the SAME shape as payment-delay
  requests, discount requests, salary preparation, book-sale cash logging, and
  event cost-splitting: **request → approve(s) → cashier disburses → notify →
  ledger entry.** Build ONE generic Approvals + Money-movement (ledger) engine and
  every one of these becomes a configured instance. This is probably the single
  biggest architectural simplification in the whole product. (See themes below.)

## 16. HR / hiring pipeline + Telegram bots
- HR bots on **Telegram** and in-app.
- **Customized application questions** in the app for new candidates.
- Candidates can be **accepted, scheduled for an interview** on a date, and
  **talk with the manager or HR/audit** inside the app. Calling supported.
- (Telegram is dominant in UZ — also a strong channel for the "extreme
  notifications" idea.)

## 17. Call recording + AI call analysis ("Meta AI")
- When staff call someone, route it through a recording/analysis layer that
  **records everything** and reports to the manager (or whoever has access): how
  the staff member talked to the customer, quality, etc. Call QA / analytics.
- **[challenge — highest legal/technical risk in the whole vision]** Recording
  calls implicates consent + personal-data-protection law (UZ has a personal-data
  localization law) and needs telephony integration + Uzbek/Russian transcription.
  Validate legality in the research pass; an MVP is likely call *logging* + manual
  notes + opt-in recording with disclosure, not blanket recording.
- Clarified: **"Meta AI" is genuinely Meta's AI** (founder saw "Meta sell AI") —
  likely WhatsApp Business / Meta Business AI for handling & summarizing calls/
  chats. Integration path + legality both need the research pass.

## Batch 3 — business model + the camera differentiator (2026-06-02)
This reframes the pricing/positioning challenge from the research: Starforge is
**NOT** a commodity shared-SaaS CRM. It's a **premium, managed, AI-heavy, dedicated-
infrastructure** product that "brings the education center to life."

- **Real demand, now:** 3 education centers ready to buy, combined **5,000+ students,
  ~10+ branches.** Founder has used the 3 big incumbents' demos — confirms they're
  slow/buggy. (Concentration risk: 3 logos — see notes.)
- **Dedicated server per center**, paid for out of the subscription. Want more
  programs / capacity? A server is granted. This is the premium justification — and
  it's why the "$79–225 is 2–5× too high" finding is **largely answered**: it's a
  different category (managed/dedicated/AI), not the commodity CRM price axis.
- **Premium AI tiering** (not "cheap shitty AI"): **Claude Opus 4.8 (high-effort)**
  for heavy reasoning, **Sonnet** for basic, **Haiku** for fast tasks. Cost control
  matters (Opus high-effort is real money — meter per-center, see TASKS §18 budgets).
- **AI camera system built in** — the product "looks into cameras." Headline
  differentiator; founder is confident no competitor has it. (This is the concrete
  form of the earlier "keep an eye" idea, §13.) Likely uses: presence/attendance,
  safety/monitoring, behavior insights.
  - **Architecture win:** camera/face = **biometric data**, which by UZ law MUST stay
    on **domestic servers** (see uz-market-research). The dedicated **in-country**
    server-per-center model handles this *perfectly* — the premium model and the law
    line up. Still need **consent + signage**; keep biometric/video data on the
    center's own server, never in foreign cloud.
  - django-tenants (schema-per-tenant) deploys cleanly onto a dedicated per-center
    server (one/few tenants per box) — **no architectural rework needed**; the same
    codebase is the managed deployment.

## Batch 4 — camera design, exams, and the student engagement layer (2026-06-02 night)

### AI camera analysis — design
- **Edge box in the center** (e.g. i5 7th-gen + GPU) or the center's own server; **data
  never leaves the building** (satisfies biometric-localization law + huge trust line).
- Replaces today's ritual where a manager/auditor drags a teacher into a room and
  watches camera footage together for ~2h/week → slow, resentment-breeding.
- **Pipeline reality:** "Llama" is a TEXT model — it can't watch video. Real stack =
  CV (YOLO-type detection/presence) + **ASR (Whisper) on lesson audio** → local LLM
  (Llama/Qwen) writes the analysis. **Lead with audio→transcript analysis** (cheap,
  covers "was the teacher on time / did they teach / cover material / tone") + light
  presence detection; add deep video understanding later.
- **Batch at end of lesson** (non-real-time) to survive a modest GPU; mind queue
  spikes when many classes end at once. Hardware floor is really **VRAM** — a used
  RTX 3060 12GB (~$250) beats a GTX 1650 4GB by a lot.
- **Who sees the analysis: DYNAMIC — let each center's teachers vote, then configure.**
  Teacher sees their OWN report (= fairness/self-improvement), not just the manager
  (= surveillance). Same data, opposite soul. Consent + signage + short retention.

### Mock exams
- Centers currently BUY mock exams (recurring cost). Starforge provides them:
  **AI-generated (Opus)** + **government-licensed official sets** (bought by us,
  distributed to centers as a recurring promise, monthly / quarterly).
- **The real gold = AI auto-scoring + feedback** on writing/speaking (band score +
  criterion feedback in seconds; teacher reviews/overrides). Removes the slow,
  subjective weekend work; makes students feel measurably better.
- **AI-generated content dodges the copyright landmine** (your own content, not
  Cambridge/BC). Keep a quality bar early (human glance before students see a mock).

### Typing + computer-based-test (CBT) experience
- IELTS (and more) is now **computer-based**; many UZ students can't navigate the
  test UI / type fast → lose bands on mechanics, not English.
- Build a **faithful CBT simulator** (real timer, listening-plays-once, highlighter,
  word counter, navigation) + typing practice. Nobody in center-software does this.
  Open question: flagship for IELTS exam-prep centers vs universal digital-literacy
  on-ramp for every center.

### Voting / polls primitive
- Generic poll/vote in the platform (decide analysis visibility, rule-book changes,
  event adoption). A center that runs on **consent, not decree** — founder's DNA.

### Student engagement layer (the "daily attention" surface)
- **In-app podcasts** for students — clean UI, listening practice. (Use TTS-generated
  or licensed audio to stay copyright-clean; control difficulty.)
- **Focus / study board** — timer + calm widgets (Forest/Pomodoro-style) to study
  inside the app.
- **Gamified competition (Blooket/Kahoot/Gimkit-style)** — vocab/translation games
  ("pull a fish → find the translation → score"), live leaderboards, prizes. These
  tools are huge globally but **unknown/unadopted in UZ** → real gap. Founder is
  intensely competitive and wants study + games + social in ONE app.
  - AI can **generate the game content** from the lesson (vocab quizzes) → ties Opus
    back in. Digitize the "chocolate prize" into a **points/rewards + badges** system;
    the teacher can still hand out the real chocolate.

### Theme this batch crystallizes: TWO surfaces, one app
Starforge is becoming **(a) the ops platform the center OWNER pays for** (payments,
camera, attendance, payroll, accountability) **AND (b) the daily-attention surface the
STUDENT opens every day** (games, podcasts, focus, mocks, CBT). Owning the student's
daily attention is what makes the product **un-rip-out-able** — the ops tool wins the
sale, the engagement layer wins retention. Different build tracks + audiences; sequence
accordingly (owner-paid ops first, student delight layer as the retention flywheel).

## Themes Claude sees across the dump (to discuss)
1. **Accountability & anti-fraud** runs through everything (cash logging, live
   permission checks, paper accounting, fair payouts, audit). This is arguably the
   real product, not "school management."
2. **Dignity / shame-reduction** is a genuine differentiator (partial pay, delay
   requests, discount requests — all in-app, no in-person asking).
3. **Paper elimination** is the measurable promise — consider a per-center
   "paper/money saved" dashboard as a retention + sales hook.
4. **One Approvals + Ledger engine underlies most "money" features.** Payment
   delay, discounts, partial pay, salary prep, procurement, event cost-split,
   cash book sales — all are `request → N approvals → cashier disburses → notify
   → immutable ledger entry`. Build it once (generic, configurable approval
   chains + a money-movement ledger that ties to the audit trail) and the rest are
   configuration. Biggest leverage point in the codebase. Pair it with the
   accountability theme (#1): the ledger is what makes "money can't disappear" true.

## Claude's own ideas (founder asked to hear them — react to these)

**Top 3 (highest leverage):**
1. **Make the Ledger the product.** Every som is a double-entry row: tuition in,
   cashier float, salary out, book sale, event split, procurement, refund. A live
   "where is the money right now" view, auto-reconciled against Click/Payme/Uzum
   payouts. Anti-fraud by construction — this is the moat, and it's what makes
   "money can't disappear" literally true (ties to themes #1, #4).
2. **Telegram-first for parents/students; the app is for staff.** In UZ everyone
   lives in Telegram. Don't force parents to install an app — deliver attendance
   pings, payment reminders + pay-links, RSVPs, and report cards through a Telegram
   bot. Massively lower adoption friction; the polished app is the staff surface.
3. **Lead → trial → enrolled CRM funnel.** Centers live or die on enrollment, and
   most UZ "o'quv markazi" software is CRM-first, not LMS. A light sales funnel
   (lead capture → trial lesson → follow-up via Telegram → enroll) is probably the
   highest *commercial* ROI module. Reception/attendance/payments keep them; the
   funnel is what wins the sale.

**Strong supporting ideas:**
4. **Payment "trust score" (dignity, automated).** Reliable payers auto-earn larger
   delays/installments without asking a human — removes shame entirely and rewards
   good behavior. Managers set policy, not case-by-case approvals.
5. **Attendance kills the paper sheet, concretely.** One-tap roster / QR check-in;
   auto-absence → Telegram to parent; attendance feeds payroll (pay-per-lesson) and
   the fairness engine. Directly retires the founder's exact pain.
6. **"Paper & money saved" dashboard = the renewal hook.** "This month: saved N
   reams of paper, caught M missed payments, logged X cash sales." Makes the value
   undeniable at renewal and in sales demos.
7. **Print-cost attribution + quotas.** Every print job tagged to teacher/cohort/
   purpose with per-cohort quotas → the printing wedge becomes a cost-savings story.
8. **Offline-first attendance & cash logging.** Smaller-city internet is flaky;
   capture offline, sync later. Quietly differentiating.
9. **Substitute-teacher auto-coverage.** Teacher can't come → system finds a
   qualified sub from the pool, notifies, and adjusts payroll automatically.
10. **Onboarding templates by center type.** Pick "language / exam-prep / tutoring"
    → get sane default roles, permissions, and starter library; still fully
    customizable (honors the dynamic-permission rule). Fast time-to-value.
11. **Reframe call QA as consent-first.** Click-to-call with logged outcomes + AI
    summaries only on consented recordings (auto consent preamble). Manager gets QA
    without the legal landmine of blanket recording.

## Next step the founder requested
- Deep research on how Uzbek education centers actually operate (payments, payroll
  norms, Click/Payme flows, book-selling, staffing, regulations), then **challenge
  these ideas and propose better ones.** Run via the deep-research skill when ready.
- More ideas are coming ("I got so much more") — this file is append-only; keep adding.
