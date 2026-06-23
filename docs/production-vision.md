# Production Vision

> Referenced by `FEATURE_LIST.md` #13 (fairness/salary engine). This is a STUB —
> owner to fill the detailed rules. The engineering breakdown lives in
> `agents/FEATURE_BACKLOG.md`.

## Fairness / salary engine (#13) — needs the owner's rules
The engine should compute a teacher's payout as a base (existing
`TeacherProfile.salary_type` + `rate`) adjusted by a manager-set **percentage**
driven by performance factors. Open inputs the owner should specify:

- Which factors feed "fairness", and their weights? (e.g. attendance taken on time,
  student attendance %, student results/retention, hours taught, peer/manager rating)
- Is the percentage a bonus on top of base, or does it scale the base?
- Cadence: per lesson, per month, per term?
- Floor/ceiling on the adjustment?
- "fairly or without" (from #5/#13): when is distribution equal vs performance-weighted?

Until these are filled, F13-1 in the backlog is `BLOCKED(spec)`.

## (other production-vision sections — add as needed)
