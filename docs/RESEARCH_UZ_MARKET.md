# UZ Education-Center Market — Research Findings & Challenge to the Plan

> Synthesized from a deep-research run (25 adversarially-verified claims with
> sources; the auto-synthesis step was cut off by a session limit, so this
> write-up was assembled by Claude from the verified claims). Date: 2026-06-01.
> Citations point to the source the claim was verified against.

---

## ⚡ The three things that should change the plan

### 1. The market is CROWDED, and you're priced 2–5× above it
Multiple incumbents already serve UZ education centers, and they already do most
of the "management" features in the FEATURES.md plan:
- **EducationCRM.uz** — claims **500+ centers, 50,000+ students**; role panels for
  Director/Manager/Teacher/Marketing + AI Support + Lead Management; payment +
  debt/delinquency tracking. [8,20,21]
- **Modme.uz** — incumbent; built-in salary computation; **six tuition billing
  modes** (Monthly/Calendar, Daily, Module, Group-start, Course, Individual) —
  i.e. flexible/partial payment scheduling is **already solved**. [13,14,15]
- **Edulog.uz** — dashboard, schedule, attendance, student/staff mgmt, parent &
  student cabinets, auto salary calc; integrates **Click** + Eskiz/SMS + Freedompay
  (no Payme/Uzum). Priced **200k / 450k / 600k UZS per month** (~**$16–48/mo**) for
  up to 5k/8k/12k students. [9,10,11]
- **UstozCRM.uz** — multi-branch, attendance, salary calc, parent portal. [23]
- **CRM Edu (crm-edu.uz)** — **three teacher-comp models** (fixed / per-hour / % of
  tuition) auto-calculated — your "fair payroll" idea is **already a feature**;
  but its payments are manual debt-tracking with **no gateway integration**. [3,22]

**Implication:** FEATURES.md prices Starter/Pro/Premium at **$79/$125/$225 USD**.
The local incumbent charges **~$16–48** for *more* students. Your pricing is
**2–5× the market** and in the wrong currency framing (UZS, not USD). Either
reprice to local reality or justify a premium with the differentiators below.

### 2. Your real moat is the stuff NONE of them do
None of the five incumbents advertise **printing, a content library, or paper
accounting**. That is your genuine wedge. Reinforced by: commercial book-printing
shops explicitly target education centers [6], and per-page printing is cheap
(50–240 som/page) so centers print **a lot** [17] → paper cost & control is a real,
unaddressed pain. **Also under-served:** true online payment *collection* across
all rails (most competitors do manual debt-tracking; Edulog has Click only, CRM Edu
none [9,22]) and the **dignity/shame-reduction payment UX** (delay/partial/discount
requests) — nobody does this.

### 3. Two hard compliance constraints you must design around now
- **Fiscal / online cash register.** A 2022 Presidential decree requires payment
  system operators to connect to the **online cash register integrated with the
  tax authority** (anti-shadow-economy). [1] → Collecting tuition online almost
  certainly requires **fiscal-receipt (OFD) integration**, not just a payment
  gateway. This is a *must-have* for the payments module, not a nice-to-have.
- **Data localization — RELAXED in your favor (Mar 2026).** The strict 2021 rule
  (store Uzbek citizens' data domestically, DB registered with UzComNazorat
  [18,19,25]) was **amended in March 2026**: most personal data may now be stored
  **abroad** under conditions — **except biometric, genetic, and telecom data**,
  which must stay domestic. [2,16] → You can likely use foreign cloud (AWS/Hetzner)
  for most data, but must keep any **biometric** (e.g. face/fingerprint check-in)
  and telecom/call data in-country. Directly affects the Day-5 hosting decision and
  the call-recording idea.

---

## Idea-by-idea verdict

| Idea | Verdict | Why |
|------|---------|-----|
| Printing service + bundled book library | ✅ **Differentiator** — but ⚠️ copyright | No competitor does it [6,17]; BUT distributing copyrighted books is infringement (see below) |
| Connect Click + Payme + Uzum | ✅ **Validated gap** | Big-3 rails dominate (Click 5M MAU, Payme 3.3M, Uzum 1.4M) [4,5]; competitors integrate weakly/none [9,22] |
| Dignity payment flows (delay/partial/discount requests) | ✅ **Differentiator** | Not seen in any incumbent; flexible *scheduling* exists (Modme) but not the request/approval UX [15] |
| Fair payroll (% of tuition) | 🟡 **Table-stakes** | Already in CRM Edu & Modme [3,13] — keep it, don't market as innovation |
| Multi-branch, attendance, parent portal, lead mgmt, roles | 🟡 **Table-stakes** | All present in incumbents [8,10,21,23] — necessary to compete, not differentiating |
| Ledger / anti-fraud accountability | ✅ **Likely differentiator** | Not advertised by competitors; pairs with the fiscal-receipt requirement |
| Call recording ("Meta AI") | ⚠️ **Risky** | Consent + telecom data must stay domestic [16]; heavy build |
| $79–225 USD pricing | ❌ **Reprice** | 2–5× above local market (~$16–48) [11] |

---

## ⚠️ The biggest single risk: the library's copyright

Uzbekistan's copyright law (**LRU-42, 2006**) grants authors exclusive rights of
**reproduction, distribution, and adaptation**; as a Berne signatory, protection is
**automatic and covers foreign works**. [7,24] → A "bundled library of books"
(especially foreign English textbooks — Oxford/Cambridge/etc.) printed or
distributed without a licence is **infringement**. The wedge is real but must be
built on **licensed content, public-domain, or open-licence (CC) materials**, or as
a BYO-content tool (the center uploads what they're licensed to use). Do not ship a
default library of commercial textbooks.

---

## What I'd change about the 5-day / product plan
1. **Reprice to UZS reality** (~150k–600k UZS tiers), or hold USD pricing only if the
   printing/payments/ledger differentiators clearly justify it. Validate with the
   first customer.
2. **Lead the wedge:** printing + paper accounting + true multi-rail online payment
   collection + dignity UX — not the management features incumbents already ship.
3. **Treat fiscal-receipt (OFD) integration as part of the payments epic**, not an
   afterthought.
4. **Library = licensed/open content or BYO-upload**, never default commercial books.
5. **Hosting:** foreign cloud is now OK for most data (Mar 2026), but isolate
   biometric/telecom data domestically — fold into the Day-5 deployment decision.
6. **Telegram-first parent UX** still looks like an edge (incumbents use web cabinets);
   worth validating as a cheaper, higher-adoption channel.

---

## Verified claims (evidence base)
1. 2022 decree: payment operators must connect to online cash register integrated
   with tax authorities (anti-shadow-economy). — KPMG Fintech UZ 2024
2. Mar 2026: UZ relaxed data localization — most personal data may be stored abroad
   under conditions. — Dentons, 2026-03-31
3. CRM Edu: 3 teacher-comp models (fixed / per-hour / % tuition), auto payroll. — crm-edu.uz
4. Click >76k merchants / Payme 73.6k merchants (2023); Click >450M txns 2023. — KPMG
5. Click/Payme/Uzum lead non-cash; 2023 MAU 5M / 3.3M / 1.4M. — KPMG
6. Tashkent book-printing services target education centers/schools. — OLX listing
7. UZ copyright covers literary works; Berne auto-protection incl. foreign works. — Mondaq
8. EducationCRM.uz: CRM for UZ centers, claims 500+ centers / 50k+ students. — educationcrm.uz
9. Edulog integrates Click + Eskiz/SMS + Freedompay; no Payme/Uzum. — edulog.uz
10. Edulog modules: dashboard, schedule, attendance, student/staff mgmt, cabinets, auto salary. — edulog.uz
11. Edulog pricing: 200k/450k/600k UZS per month (5k/8k/12k students). — edulog.uz
12. Click integration = server-side Prepare + Complete endpoints (SHOP API). — docs.click.uz
13. Modme: built-in teacher salary computation. — modme.uz
14. Modme: learning-center management platform for UZ private centers. — modme.uz
15. Modme: six tuition billing modes (incl. flexible/partial scheduling). — modme.uz
16. Only biometric, genetic, telecom data must remain domestic. — Dentons 2026
17. Per-page print 50–240 som; printing full books is cheap per page. — OLX listing
18. UZ citizens' personal data must be processed/stored domestically, DB registered with UzComNazorat. — loc.gov
19. Localization applies to collection/systematization/storage; obligation on DB owner/operator. — loc.gov
20. EducationCRM bundles payment + debt/delinquency reports. — educationcrm.uz
21. EducationCRM role panels: Director/Manager/Teacher/Marketing + AI Support + Lead Mgmt. — educationcrm.uz
22. CRM Edu payments are manual debt-tracking; no Click/Payme/Uzum gateway advertised. — crm-edu.uz
23. UstozCRM: multi-branch, attendance, salary calc, parent portal. — ustozcrm.uz
24. UZ copyright governed by LRU-42 (2006): reproduction/distribution/adaptation rights. — Mondaq
25. UZ data localization law signed 2021-01-14, in force 2021-04-16. — loc.gov
