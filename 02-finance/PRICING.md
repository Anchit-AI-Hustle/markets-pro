# PRICING — Candidate A: Productized Async Growth Diagnostic Reports

Status: **Provisional**. Prepared by FINANCE agent, 2026-08-19 (Day 0 of build).
Three price points, anchored to `01-strategy/COMPETITORS.md`'s found market
range. No real willingness-to-pay (WTP) evidence exists yet for any of the
three — that is stated plainly under each, not hidden or assumed away.
All INR conversions use USD/INR ≈ 95.7 (see `UNIT-ECONOMICS.md` Sources).

---

## The 3 price points

### Price Point 1 — Low: Rs 9,900/report (~$103)

**Anchor:** Just above FlowAudit's $75 self-serve AI Klaviyo-only report and
inside the upper half of Fiverr's $20–$160 freelance-gig range
(`COMPETITORS.md` §1.3–1.4), but for a **combined** 3-part report (Klaviyo +
Meta/Google + CRO) rather than a single-component audit.

**WTP evidence:** **None. Blocked.** No prospect, real or informal, has ever
seen this price. `RISKS.md` Risk #2's landing-page-price test is written
around Rs 17,500 (Price Point 2), not this price — to get real WTP evidence
at Rs 9,900, the landing page and payment link would need to be re-pointed to
this price for a comparable test, which has not been done.

**Reasoning (Provisional):** this price directly competes with FlowAudit on
price while offering 3x the scope — but at 3x the AI-report price for
one-third of FlowAudit's self-serve automation convenience (no human
required on their side, instant delivery vs. this venture's async QA
turnaround), it is not obviously superior from the buyer's perspective per
`COMPETITORS.md`'s own verdict. **Required sales to clear Rs 1L/month: Rs
1,00,000 / Rs 9,900 = 10.1 → 11 sales/month** — more than double the
kill-bar's 5 sales, which stacks directly on top of `RISKS.md` Risk #5's
already-tight QA-time math (11 × 60 min = 11 hours/month of QA alone, before
outbound and delivery).

### Price Point 2 — Mid: Rs 17,500/report (~$183) — **RECOMMENDED**

**Anchor:** `VENTURE-SELECTION.md`'s own assumption midpoint (Rs
15,000–20,000), which sits between Fiverr/FlowAudit's sub-$200 automated
tier and Blend Commerce's $510 agency "Mini Audit" (`COMPETITORS.md` §1.1,
§1.3).

**WTP evidence:** **None yet. Blocked.** This is exactly the price
`RISKS.md` Risk #2 designed its 30-day test around: a one-page landing page
with a real Stripe/Razorpay payment link at Rs 17,500, driven by the same
150 outbound touches used for the conversion test (Risk #1), plus informal
price feedback from 5–10 ICP-fit contacts outside the "distribution" count.
**This is the unblocking mechanism** — it has not run yet as of this
document's date (Day 0).

**Reasoning (Provisional):** `COMPETITORS.md`'s own verdict flags this
price band as awkward — a skeptical cold prospect can find a $75 automated
Klaviyo-only alternative *and* a free full-service audit-with-a-call in one
search, both without this venture's specific commitment (pay upfront, no
call, unknown solo operator). That tension is real and unresolved by pricing
alone — it is a differentiation/trust problem, not a price-level problem
(see `RISKS.md` Risk #3).

### Price Point 3 — Premium: Rs 48,000/report (~$502)

**Anchor:** Closer to Blend Commerce's "Mini Audit" at £405 (~$510) —
`COMPETITORS.md` §1.1, **Final** (published agency pricing).

**WTP evidence:** **None. Blocked.** Same landing-page-test mechanism as
Price Point 2 would need to be re-run at this price point to get real
signal — not done.

**Reasoning (Provisional):** at this price, the venture directly competes
with an established agency audit product backed by Klaviyo's own referral
traffic and real client testimonials (`COMPETITORS.md` §1.1) — assets this
venture has zero of on day one. `RISKS.md` Risk #4's compliance-fragility
concern (buyers asking for "just a 15-minute call first") is **most acute at
this price point**: a buyer paying agency-comparable money from an unknown
solo operator has the strongest rational reason to expect an agency-comparable
sales process (i.e., a call) — directly in tension with the charter's
no-call structural requirement. **Required sales to clear Rs 1L/month: Rs
1,00,000 / Rs 48,000 = 2.1 → 3 sales/month** — the easiest volume target of
the three, but the hardest trust/compliance bar to clear cold.

---

## Recommendation

**Recommended price: Rs 17,500/report (Price Point 2, Mid).**

**Reasoning, tied explicitly to `UNIT-ECONOMICS.md`:**

1. **Gross margin is not the binding constraint at any of the three price
   points.** Per `UNIT-ECONOMICS.md` §1e, total cash cost per report is
   ≈Rs 920–1,050 (AI/LLM + payment processing + apportioned hosting) — even
   Price Point 1 (Rs 9,900) clears gross-margin-positive by a wide margin
   (≈89.5% gross margin at that floor price). **The minimum viable price for
   positive gross margin is trivially low (well under Rs 2,000) and is not
   the real decision variable here** — sales volume against the 7-hour/week
   QA + outbound ceiling is (per `RISKS.md` Risk #5), so price should be set
   to minimize the *required sales count*, not to protect margin.
2. **Rs 17,500 is the price the already-designed, already-costed 30-day
   test (`RISKS.md` Risk #2) is built around.** Changing the recommended
   price would mean re-designing that test rather than running the one
   already specified — the charter's "cheapest test before any build" rule
   favors using the existing, ready-to-run test over inventing a new one.
3. **It sits inside `MARKET.md`'s own revenue-scenario math**, which this
   document is instructed not to re-derive — MARKET.md's Rs 1,05,000–160,000
   (optimistic) / Rs 15,000–40,000 (base) / Rs 0–20,000 (pessimistic) figures
   are all built on the Rs 15,000–20,000 ticket assumption. Recommending a
   different price here would silently invalidate that already-completed
   analysis without new data to justify it.
4. **It requires 5–7 sales/month to clear Rs 1L** — squarely the number
   already used as the charter's kill threshold in `VENTURE-SELECTION.md` §6,
   keeping the kill criteria in `KILL-CRITERIA.md` internally consistent with
   this pricing choice.

**This recommendation is Provisional and is exactly what Risk #2's 30-day
test is designed to confirm or falsify** — a real Rs 17,500 payment link
converting at least once, and/or price feedback not clustering around "too
expensive vs. Fiverr/FlowAudit," would upgrade this to Final. Zero
conversions and/or repeated unprompted references to cheaper alternatives
would falsify it and should trigger a re-test at Price Point 1 before
concluding the venture itself is dead (see `KILL-CRITERIA.md`).

---

## Number status summary

| Number | Status | What would make it Final |
|---|---|---|
| Price Point 1 (Rs 9,900) | Provisional | A landing-page/payment-link test at this specific price |
| Price Point 2 (Rs 17,500) — recommended | Provisional | `RISKS.md` Risk #2's 30-day landing-page-price test (already designed, not yet run) |
| Price Point 3 (Rs 48,000) | Provisional | A landing-page/payment-link test at this specific price |
| Minimum viable price for positive gross margin (<Rs 2,000) | Provisional (derived from `UNIT-ECONOMICS.md`) | Becomes Final once AI/LLM and payment-processing cost lines in `UNIT-ECONOMICS.md` are Final |
| Required sales/month to hit Rs 1L, by price point (11 / 6 / 3) | Provisional (derived, simple division) | Becomes Final once the recommended ticket price itself is Final |

## Sources

Same as `01-strategy/COMPETITORS.md` (Blend Commerce, FlowAudit, Fiverr
pricing — not re-derived here) plus `UNIT-ECONOMICS.md` (cost-per-report
derivation) and `01-strategy/RISKS.md` (Risk #2 test design). USD/INR ≈ 95.7,
see `UNIT-ECONOMICS.md` Sources.
