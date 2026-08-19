# KILL CRITERIA — Candidate A: Productized Async Growth Diagnostic Reports

Status: **Provisional inputs, Final process.** Prepared by FINANCE agent,
2026-08-19 (Day 0 of build). This document exists so that a future
sunk-cost-biased operator cannot argue with the numbers or the dates —
every checkpoint below names a metric, a real number, and a real calendar
date. No checkpoint is worded as "if it's not going well."

Day 0 = **19 August 2026**. All dates below are calculated from Day 0 and
are calendar dates, not "N days in."

---

## Day 30 checkpoint — 2026-09-18

**This restates `01-strategy/RISKS.md` Risk #1's already-designed 30-day
outbound test as the formal Day-30 kill checkpoint** — nothing new is
invented here, per the charter's "cheapest test before any build" rule; this
is that test, given a hard decision date.

**The test:** 150 real, individually-researched, personalized cold outbound
messages (LinkedIn + email) sent to a hand-built ICP list at the actual
planned offer and price (Rs 17,500, no call, async delivery — per
`PRICING.md`'s recommendation), tracked for paid conversions. Test window:
2026-08-19 → 2026-09-18.

| Result | Metric | Decision | Action |
|---|---|---|---|
| **Green** | **≥3 paid conversions** from 150 touches (≥2.0% close rate) | Continue to Phase 2 build | Proceed — offer/ICP combination beats the "harder ask" discount RISKS.md's model applied |
| **Amber** | **Exactly 2 paid conversions** from 150 touches (1.33% close rate) | Inconclusive — do not commit to full Phase 2 build yet | Extend the same outbound motion by another 100 touches within the next 15 days (by 2026-10-03). Apply the cumulative test: **≥5 paid conversions from the cumulative 250 touches (2.0%)** → treat as Green and proceed; **<5 from 250** → treat as Red and kill |
| **Red** | **0–1 paid conversions** from 150 touches (<0.7% close rate) | **Kill Candidate A** | Do not proceed to Phase 2 build. Return to Phase 0 candidate re-evaluation per `VENTURE-SELECTION.md`'s other scored candidates (B/C/D) |

**Concurrently tracked at the same Day-30 checkpoint (folded into the same
test, per `RISKS.md`, all with the same 2026-09-18 decision date):**

- **Price (Risk #2):** ≥1 real prepayment clears at Rs 17,500 within the
  window, and informal price feedback from the 5–10 non-outbound ICP
  contacts does not concentrate on "too expensive vs. Fiverr/FlowAudit" →
  price treated as validated. Zero prepayments AND ≥3 people unprompted cite
  a specific cheaper alternative → price is a confirmed problem, feeds into
  the Red decision above even if conversions were otherwise Amber/Green.
- **Differentiation (Risk #3):** ≥2 non-converting repliers independently
  cite a cheaper/free alternative (FlowAudit, Fiverr, a free agency audit)
  as their stated reason for not proceeding → differentiation is a confirmed
  problem, logged for the Day-60 review even if it doesn't independently
  trigger a Day-30 kill.
- **Compliance boundary (Risk #4):** log every call/chat/demo request,
  regardless of outcome. **>30% of interested replies requesting a call** is
  a confirmed compliance-fragility signal — logged for Day-60/Day-90 review.
  **Any single instance where the operator grants a call or bespoke
  follow-up counts toward the cumulative "more than once" kill trigger in
  the Day-90 checkpoint below** — track the running count starting today.
- **Time budget (Risk #5):** total logged hours (Toggl or spreadsheet) for
  the 150–250 touches this month. **>25 hours logged for outbound alone**
  (before any QA/pipeline time) is a confirmed capacity problem, independent
  of the conversion result — logged for the Day-60 review.

---

## Day 60 checkpoint — 2026-10-18

**Purpose:** tests the charter's "first revenue by month 2" bar directly
(Month 2 = 2026-09-19 → 2026-10-18) and sets the bar to justify spending the
final 30-day block before the absolute kill date.

| Result | Metric | Decision |
|---|---|---|
| **Green** | Cumulative paid reports sold since Day 0 **≥3**, AND Month-2 (2026-09-19→2026-10-18) revenue run-rate **≥ Rs 40,000** | Continue unconditionally into the final 30-day block |
| **Amber** | Cumulative paid reports = **1–2**, AND Month-2 revenue between **Rs 15,000–39,999** | Conditional continue only: within 3 days (by 2026-10-21) produce a written, numbered pipeline — specific named prospects with a stated probability of closing — showing a credible path to the Day-90 bar below. No pipeline document, or a pipeline that mathematically cannot reach the Day-90 bar → treat as Red |
| **Red** | Cumulative paid reports = **0**, OR Month-2 revenue **< Rs 15,000** | **Kill Candidate A** on 2026-10-18. Rs 15,000 is not an arbitrary floor — it is the bottom of `MARKET.md`'s own base-case revenue range; falling below it means performance is at or below the pessimistic case MARKET.md already modeled |

**Why Rs 40,000 / Rs 15,000:** these are `MARKET.md` Section 2's own base-case
range bounds (Rs 15,000–40,000/month), not new numbers invented for this
document. Hitting the top of that range by Day 60 is the minimum signal that
the venture is tracking toward — not below — the scenario MARKET.md already
flagged as insufficient on its own, while leaving one more 30-day block to
close the gap to Rs 1,00,000.

---

## Day 90 / Absolute kill checkpoint — 2026-11-19

**This is `00-decisions/VENTURE-SELECTION.md` Section 6's kill date**
(19 November 2026, end of month 3 from Day 0) and `CHARTER.md`'s
"month 3 is the absolute latest" revenue deadline — restated here with the
exact sales count implied by the price this document's sibling,
`PRICING.md`, actually recommends.

**Precision correction to `VENTURE-SELECTION.md`'s original number:**
`VENTURE-SELECTION.md` §6 used a round "5 paid diagnostic reports" figure,
derived from its own Rs 15,000–20,000 ticket-price range. Now that
`PRICING.md` has picked a specific recommended price (**Rs 17,500**), the
exact number is:

`Reports needed for Rs 1,00,000/month = CEILING(100,000 / 17,500) = CEILING(5.71) = 6`

(5 reports at Rs 17,500 = Rs 87,500 — short of the Rs 1,00,000 bar. 6 reports
= Rs 1,05,000 — clears it. This tightens VENTURE-SELECTION.md's "5–7" range
to a single precise number now that the price is fixed, and should be
treated as the operative figure going forward.)

**Measurement window for "a single calendar month":** the most recently
completed calendar month as of the checkpoint date, i.e. Month 3 =
2026-10-19 → 2026-11-18.

| Result | Metric | Decision |
|---|---|---|
| **Green** | Month-3 (2026-10-19→2026-11-18) revenue **≥ Rs 1,00,000** (i.e. **≥6 paid reports** sold within that single calendar month at Rs 17,500), AND cumulative logged call/bespoke-follow-up exceptions (tracked since Day 0) **≤1** | Continue past month 3 into steady operations; re-baseline monthly targets in `00-decisions/` |
| **Red** | Month-3 revenue **< Rs 1,00,000** (fewer than 6 reports in that single calendar month), **OR** cumulative call/bespoke-follow-up exceptions **>1** | **Kill Candidate A.** Per `VENTURE-SELECTION.md` §6: return to Phase 0 and re-evaluate Candidates B/C/D rather than extending the timeline. No third state at this checkpoint — this is the charter's hard backstop, not a negotiable one |

**This checkpoint is final and binary by design** — Day 30 and Day 60 have
Amber states with defined remediation actions; Day 90 does not, because it
is the charter's own stated absolute limit ("month 3 is the absolute
latest... a candidate that cannot plausibly clear this is disqualified, not
carried forward 'to see'").

---

## What does NOT extend the kill date

Per charter standing rules, none of the following are valid reasons to move
any date above:

- "We're close" without a number that meets the stated bar.
- Revenue from a channel other than the productized async report (e.g. a
  one-off consulting engagement) — that would itself be an out-of-charter
  compliance breach (`VENTURE-SELECTION.md` compliance note), not a save.
- The operator's other income continuing to cover living expenses past
  9-Sep-2026 (`VENTURE-SELECTION.md` operator answer #1) — that changes the
  *consequence* of missing the bar, explicitly **not** the bar itself, per
  that same source document: "a miss is a strategy problem, not a solvency
  emergency... the bar itself is not [changed]."
- A pipeline of unclosed "interested" prospects at the Day-90 checkpoint —
  only *paid* reports count, consistent with the charter's "pre-sell over
  build" and "asset does the selling" rules; an interested-but-unpaid
  prospect is not revenue.

---

## Number status summary

| Number | Status | Source |
|---|---|---|
| Day 30 date (2026-09-18) | Final | Calculated: Day 0 + 30 days |
| Day-30 green/red thresholds (≥3 / 0–1 conversions from 150 touches) | Final (restated from RISKS.md, not altered) | `01-strategy/RISKS.md` Risk #1 |
| Day-30 amber definition (exactly 2) and its remediation rule | Provisional — newly defined here to close a gap RISKS.md left open | This document |
| Day 60 date (2026-10-18) | Final | Calculated: Day 0 + 60 days |
| Day-60 Rs 40,000 / Rs 15,000 thresholds | Provisional (derived) | `01-strategy/MARKET.md` Section 2 base-case range bounds |
| Day 90 / kill date (2026-11-19) | Final | `00-decisions/VENTURE-SELECTION.md` §6 |
| 6 reports needed for Rs 1L at Rs 17,500 ticket | Provisional (derived, exact arithmetic) | This document, correcting VENTURE-SELECTION.md's round "5–7" now that `PRICING.md` fixes the price |
| Call/bespoke-follow-up ">1" kill trigger | Final (restated from VENTURE-SELECTION.md, not altered) | `00-decisions/VENTURE-SELECTION.md` §6 |
