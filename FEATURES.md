# Starforge Edu — Subscription Features

Multi-tenant education management platform for tutoring centers, language schools, and K–12 institutions in Uzbekistan.

All plans are billed **monthly per Center** (one school / one organization = one Center). Each plan includes one isolated tenant on its own `*.starforge.uz` subdomain, OTP login (phone or email), and the full role-permission model (Director, Manager, Accountant, Teacher, Parent, Student, Reception, IT).

---

## Plan summary

| Plan          | Price (USD / month) | Best for                                            |
|---------------|---------------------|-----------------------------------------------------|
| **Starter**   | **$79**             | Single-branch tutoring centers, < 75 students       |
| **Pro**       | **$125**            | Multi-branch schools, payment processing, light AI  |
| **Premium**   | **$225**            | Large institutions, full AI suite, branch printing  |

---

## Starter — $79 / month

For small tutoring centers running one branch that need reception, scheduling, attendance, and parent communication — without payment processing or AI.

**Capacity**
- 1 Branch
- Up to 75 active students
- Up to 8 staff accounts
- 5 GB file storage
- 1 subdomain (e.g. `acme.starforge.uz`)

**Included**
- Tenant isolation (dedicated Postgres schema, no data leakage between centers)
- OTP login via **email** (phone-OTP/SMS not included)
- JWT auth, refresh-token rotation, blacklist, logout-everywhere
- Reception module — Students, Parents, Teachers, Guardians
- Cohorts (class groups) with membership and primary teacher
- Schedule — recurring lessons, room booking, conflict detection
- Attendance — mark present/absent/late, summary per term
- Notifications — in-app + email only
- Basic Reports — enrollment list, attendance summary, cohort roster
- Multi-language UI — uz / en / ru
- Audit log — 1 year retention
- Web admin (`/admin/`) and OpenAPI / Swagger docs

**Not included**
- ❌ AI features of any kind
- ❌ Branch printing
- ❌ Finance / invoicing / cashier
- ❌ Payment gateways (Click / Payme / Uzum)
- ❌ SMS via Eskiz (OTP or notifications)
- ❌ Mobile push notifications (FCM / APNs)
- ❌ Realtime / WebSocket updates
- ❌ Academic transcripts and exam management
- ❌ Assignments / homework submission
- ❌ Content library uploads beyond 5 GB
- ❌ Custom domain
- ❌ Scheduled reports
- ❌ Field-level encryption for sensitive PII
- ❌ Bulk CSV imports

---

## Pro — $125 / month

For mid-size schools running multiple branches that need real payment processing, SMS, and light AI assistance.

**Capacity**
- Up to 3 Branches
- Up to 400 active students
- Up to 30 staff accounts
- 50 GB file storage
- 1 subdomain

**Everything in Starter, plus:**

**Communications**
- ✅ SMS OTP login via Eskiz (in addition to email)
- ✅ SMS notifications via Eskiz (Uzbek operators)
- ✅ Mobile push notifications (FCM / APNs)
- ✅ Notification preferences per user × event × channel
- ✅ Quiet hours, bulk announcements, in-app feed with read receipts

**Finance & Payments**
- ✅ Finance module — Invoices, Invoice Lines, Discounts, Refunds
- ✅ Cashier shifts (open/close, daily cash count, daily report)
- ✅ Tuition fee schedules per Center and per Cohort
- ✅ Sibling discounts, scholarships, payment plans
- ✅ Outstanding balance per student
- ✅ Late-payment reminder automation
- ✅ Parent statement of account (PDF)
- ✅ Payment gateway — **Click**
- ✅ Payment gateway — **Payme** (JSON-RPC, full handler set)
- ✅ Webhook signature verification + idempotency
- ✅ Reconciliation reports (daily)
- ✅ Receipt PDF generation

**Academics**
- ✅ Subjects, Exams (midterm / final / quiz / project / oral)
- ✅ Grade entry (per cohort, per exam) + bulk CSV grade entry
- ✅ Grading scheme (letter / GPA / percentage)
- ✅ Auto-calculated term grades from weighted exam results
- ✅ Transcript PDF per student
- ✅ Honor roll / academic warning detection
- ✅ Grade audit trail

**Assignments**
- ✅ Teacher creates assignment with attachments + due date
- ✅ Student submissions (file or text)
- ✅ Rubrics, late-submission flagging, resubmissions
- ✅ Notifications: created, due-soon, graded

**Content library**
- ✅ Hierarchy: Subject → Course → Module → Lesson → File
- ✅ Signed S3 upload/download URLs
- ✅ File-type allowlist + libmagic validation
- ✅ Versioning, view tracking, download counter
- ✅ Visibility scoping (department / cohort / role)

**AI — light tier**
- ✅ **500,000 tokens / month** of Claude (Anthropic) usage included
- ✅ Use cases enabled: **assignment feedback**, **content summarization**
- ✅ Prompt caching to keep cost low
- ✅ Per-Center monthly budget enforcement
- ❌ Exam question generation (Premium only)

**Operations**
- ✅ Realtime updates via Channels (live attendance, in-app notifications)
- ✅ Scheduled reports — up to 5 schedules (weekly/monthly)
- ✅ Bulk CSV student/parent import
- ✅ Audit log — 3 year retention
- ✅ Standard email support, response within 1 business day

**Not included on Pro**
- ❌ AI exam question generation
- ❌ Branch printing module + printer agent integration
- ❌ Uzum payment gateway
- ❌ Custom domain (e.g. `school.uz` instead of `school.starforge.uz`)
- ❌ Field-level encryption for `national_id` / `medical_notes`
- ❌ Cross-tenant analytics (multi-campus rollups)
- ❌ Storage above 50 GB
- ❌ More than 3 Branches

---

## Premium — $225 / month

For large multi-branch institutions that need the full AI suite, in-house **printer integration**, all payment rails, and compliance-grade audit.

**Capacity**
- **Unlimited Branches**
- **Unlimited active students**
- **Unlimited staff accounts**
- 500 GB file storage
- Custom domain (`yourschool.uz`) + automatic TXT-record verification
- Multiple subdomains supported

**Everything in Pro, plus:**

**Full AI Suite (`apps/ai`)**
- ✅ **5,000,000 tokens / month** of Claude (Anthropic) included
- ✅ **AI Exam Question Generation** — generate quizzes/midterms/finals scoped to a subject, level, and difficulty
- ✅ **AI Assignment Feedback** — Claude reviews student submissions and drafts teacher-style feedback
- ✅ **AI Content Summarization** — summarize uploaded PDFs / lesson files for students
- ✅ Versioned prompt registry, per-feature cost cap, per-Center usage report
- ✅ PII redaction before any prompt leaves the tenant (regex + LLM fallback)
- ✅ Anonymized student data in AI calls where possible

**Branch Printing (`apps/printing`)**
- ✅ Print job queue per Branch (queued → picked → printing → done / failed)
- ✅ **Branch print agent** integration (long-lived API token bound to a Branch)
- ✅ Multiple printers per branch (name, model, IP, capabilities)
- ✅ Job specs: pages, copies, color, duplex
- ✅ Retry policy on failure (exponential, max 3)
- ✅ Print quotas per cohort per term (paper-saving)
- ✅ Print audit (who printed what, when, how many pages)
- ✅ Sources: assignments, transcripts, reports, custom

**Payments — all three rails**
- ✅ Click
- ✅ Payme
- ✅ **Uzum** (in addition to Click + Payme)
- ✅ Refund flow with provider-specific state machines

**Compliance & Security**
- ✅ **Field-level encryption** for `national_id`, `medical_notes`, and other sensitive PII (django-cryptography / pgcrypto)
- ✅ Audit log — **7 year retention** for finance & grades, append-only, no DELETE permission
- ✅ Audit search UI + CSV export for compliance requests
- ✅ Impossible-travel detection (flag suspicious logins)
- ✅ Token-versioning to invalidate all live sessions
- ✅ Device-bound refresh tokens with revocation
- ✅ Penetration testing scope on request

**Advanced Org**
- ✅ Branch operating hours, holidays (per-branch overrides)
- ✅ Department budgets, head-of-department assignment
- ✅ Department budget vs spent rollup (live from Finance)
- ✅ Room model: capacity, equipment, availability windows
- ✅ Branch transfer history with audit trail
- ✅ Tenant impersonation tool (read-only) for support

**Reports & Analytics**
- ✅ Unlimited scheduled reports
- ✅ Cross-tenant / cross-campus analytics (for school chains with multiple Centers)
- ✅ PDF + Excel exports
- ✅ AI usage report per Center per month
- ✅ Storage usage report

**Internationalization & Localization**
- ✅ Full uz / en / ru language pack
- ✅ Localized SMS + email templates
- ✅ Per-locale number / date / currency formatting

**Operations**
- ✅ **Priority support** + named SLA (response < 4 business hours)
- ✅ Onboarding session + data migration assistance
- ✅ Sandbox tenant for staff training
- ✅ FX rate snapshots per invoice (historical totals don't drift)
- ✅ Quarterly disaster-recovery restore drill
- ✅ Sentry-equivalent error tracking on your tenant

**Not included on Premium**
- ❌ The actual physical printer + paper (you supply hardware)
- ❌ Click / Payme / Uzum transaction fees (pass-through from provider)
- ❌ Eskiz SMS credits beyond the included pool (see Add-ons)

---

## Add-ons (any plan)

| Add-on                          | Price                |
|---------------------------------|----------------------|
| Extra AI tokens                 | $25 per 1,000,000    |
| Extra storage                   | $15 per 100 GB       |
| Extra branch (above plan cap)   | $20 / branch / month |
| Extra SMS credits (Eskiz)       | Pass-through at cost |
| Custom onboarding & migration   | $250 one-time        |
| Dedicated training session (1h) | $80                  |
| Extended audit retention        | $40 / month          |

---

## Feature comparison matrix

| Feature                                          | Starter | Pro    | Premium |
|--------------------------------------------------|:-------:|:------:|:-------:|
| Branches                                         | 1       | 3      | Unlimited |
| Active students                                  | 75      | 400    | Unlimited |
| Staff accounts                                   | 8       | 30     | Unlimited |
| File storage                                     | 5 GB    | 50 GB  | 500 GB  |
| Custom domain                                    | ❌      | ❌     | ✅      |
| OTP login — email                                | ✅      | ✅     | ✅      |
| OTP login — SMS (Eskiz)                          | ❌      | ✅     | ✅      |
| Reception (students/parents/teachers)            | ✅      | ✅     | ✅      |
| Cohorts                                          | ✅      | ✅     | ✅      |
| Schedule + conflict detection                    | ✅      | ✅     | ✅      |
| Attendance                                       | ✅      | ✅     | ✅      |
| In-app + email notifications                     | ✅      | ✅     | ✅      |
| SMS notifications                                | ❌      | ✅     | ✅      |
| Mobile push (FCM/APNs)                           | ❌      | ✅     | ✅      |
| Realtime / WebSocket                             | ❌      | ✅     | ✅      |
| Finance (invoices, cashier)                      | ❌      | ✅     | ✅      |
| Payments — Click                                 | ❌      | ✅     | ✅      |
| Payments — Payme                                 | ❌      | ✅     | ✅      |
| Payments — Uzum                                  | ❌      | ❌     | ✅      |
| Academics (exams, grades, transcripts)           | ❌      | ✅     | ✅      |
| Assignments / homework                           | ❌      | ✅     | ✅      |
| Content library                                  | ❌      | ✅     | ✅      |
| AI — Assignment Feedback                         | ❌      | ✅     | ✅      |
| AI — Content Summarization                       | ❌      | ✅     | ✅      |
| AI — Exam Question Generation                    | ❌      | ❌     | ✅      |
| Monthly AI token allowance                       | 0       | 500K   | 5M      |
| Branch Printing module + agent                   | ❌      | ❌     | ✅      |
| Field-level encryption (PII)                     | ❌      | ❌     | ✅      |
| Audit log retention                              | 1 yr    | 3 yr   | 7 yr    |
| Scheduled reports                                | ❌      | 5      | Unlimited |
| Cross-tenant analytics                           | ❌      | ❌     | ✅      |
| Bulk CSV import                                  | ❌      | ✅     | ✅      |
| Priority support + SLA                           | ❌      | ❌     | ✅      |
| Sandbox tenant                                   | ❌      | ❌     | ✅      |

---

## Notes

- All plans are billed in USD, monthly. Annual prepay gets **2 months free** (save ~17%).
- AI usage is metered in tokens. Unused monthly tokens do **not** roll over.
- Eskiz SMS costs are pass-through — bundled pool covers OTP at expected volumes; bulk-announcement SMS may exceed and is charged as an add-on.
- Payment-gateway transaction fees (Click / Payme / Uzum) are charged by the provider, not by Starforge Edu.
- Tenants exceeding their plan caps (students, branches, storage, AI tokens) will be prompted to upgrade or add an add-on; soft-cap warnings start at 90% usage.
- Migration from a competing system (Mock SIS, custom Excel sheets, paper records) is included on Premium and available as a $250 add-on on Starter / Pro.
- All plans run on shared infrastructure but with isolated Postgres schemas — your data never mixes with another center's.
