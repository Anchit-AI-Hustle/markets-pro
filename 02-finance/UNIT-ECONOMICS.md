# UNIT ECONOMICS — Candidate A: Productized Async Growth Diagnostic Reports

Status: **Provisional**. Prepared by FINANCE agent, 2026-08-19 (Day 0 of build).
This document does not re-pick the venture or re-derive market sizing — it
takes `01-strategy/MARKET.md`'s three revenue scenarios (optimistic/base/
pessimistic) as given and builds the cost, CAC, and LTV layer on top, per
`CHARTER.md` standing rules: every number is labeled **Final**, **Provisional**,
or **Blocked**, every formula is shown, and nothing is invented.

All INR figures use **USD/INR ≈ 95.7** (spot rate, sourced 2026-08-19 — see
Sources). Flag: `VENTURE-SELECTION.md`'s own conversion of Rs 15,000–20,000 to
"$180–$240" implies an older/lower rate (~83) — that is now stale relative to
the live rate used here. Per charter rule 8 ("never rename or restructure
source data"), that source file is not corrected; this discrepancy is simply
flagged so it isn't silently propagated into new numbers.

---

## 1. Cost per report

### 1a. AI/LLM API cost per report

**Formula:**
`AI/LLM cost per report = (input tokens × input price/token) + (output tokens × output price/token)`

| Input | Value | Status | Source |
|---|---|---|---|
| Model assumed | Claude Sonnet 5 (`claude-sonnet-5`) | Provisional (design choice, not yet built) | Chosen as the cost/quality balance point for a high-volume production pipeline per Anthropic's own guidance ("use Sonnet for high-volume production workloads") |
| Input price | $3.00 / 1M tokens (standard rate; $2.00 intro rate applies only through 2026-08-31) | **Final** | Anthropic API pricing table, cached 2026-06-24, confirmed current as of 2026-08-19 |
| Output price | $15.00 / 1M tokens (standard rate; $10.00 intro through 2026-08-31) | **Final** | Same source |
| Estimated input tokens/report | ~200,000 | **Provisional** — reasoned estimate, not measured | Reasoning: the pipeline ingests a Klaviyo flow-performance export, a Meta/Google Ads account export, and landing-page content/screenshots per intake form (VENTURE-SELECTION.md's pipeline description: "intake form → data ingest → generated report"), plus agentic tool-call overhead for a multi-stage analysis. No real report has been generated yet — this is a planning estimate. |
| Estimated output tokens/report | ~12,000 | **Provisional** — reasoned estimate | A full diagnostic report with fix-priority templates across three audit areas is a long-form document; 12K tokens ≈ 15-20 pages of structured output. |
| **Cost per report (standard rate)** | (200,000/1,000,000 × $3.00) + (12,000/1,000,000 × $15.00) = $0.60 + $0.18 = **$0.78** ≈ **Rs 74.6** | Provisional (derived) | Formula above, using Final pricing and Provisional token estimate |
| **Buffer applied (retries, QA drafting passes, iteration)** | 3x | Provisional — no real usage data yet to size this precisely | Reasoned: an agentic pipeline rarely succeeds in exactly one pass during early operation |
| **AI/LLM cost per report, used in this model** | **Rs 250** (rounded) | **Provisional** | = Rs 74.6 × ~3.3, rounded for a clean planning number |

**What would make this Final:** Building the Phase 2 pipeline and running it against
10+ real sample reports, reading actual `usage.input_tokens` /
`usage.output_tokens` off the API responses (or `messages.count_tokens`
beforehand) rather than estimating.

### 1b. Payment processing fee

**Formula:**
`Payment processing cost = Ticket price × processing fee %`

The ICP (per `01-strategy/ICP.md` / `MARKET.md`) is US/UK D2C brand founders —
i.e. the buyer pays in a foreign currency from outside India, to an
India-based operator. This is the load-bearing assumption on this line and
**CHARTER.md requires it be confirmed with the operator in Phase 2** before
any real payment rail is built — it is not yet set up.

| Option | Fee | Status | Note |
|---|---|---|---|
| Razorpay — domestic (INR cards/UPI/netbanking) | 2% + 18% GST = 2.36% | Final (published rate) | Not the realistic case — buyer is foreign, not domestic |
| **Razorpay — international card** | 3% + 18% GST = **3.54%** | Final (published rate); **application to this venture is Provisional/Blocked** pending Phase 2 operator confirmation | Assumed rail: the realistic option for a solo India-based operator receiving foreign-card payment without a US entity |
| Stripe | 4.3% processing + 2% FX conversion + 18% GST on service fees ≈ 6%+ effective | Final (published rate) but **not usable** | Stripe has been invite-only in India since May 2024, general availability not resumed as of 2026 — ruled out, not modeled further |
| PayPal (not modeled) | Not researched this pass | Blocked | An alternative for foreign-currency receipt; not priced here — flagged as a Phase 2 option to compare against Razorpay international |

**Fee assumption used in this model:** **3.54%** (Razorpay international card),
labeled **Provisional / Blocked** — Blocked in the sense that no Razorpay
account, business-entity structure, or GST-on-export-services treatment has
been set up or confirmed with the operator; this is a planning placeholder,
not a live rate quote for this specific account.

At the recommended ticket price (see `PRICING.md`) of **Rs 17,500**:
Payment processing fee = Rs 17,500 × 3.54% = **Rs 619.50/report**.

**What would make this Final:** Operator opens/confirms the actual payment
rail in Phase 2 (Razorpay international, PayPal, or an alternative), and the
real fee schedule (plus any GST-on-export or FIRC/forex-documentation
requirement for receiving foreign payments as an India-based sole proprietor)
is confirmed — this is explicitly flagged for Phase 2 per the charter.

### 1c. Landing page / tooling hosting cost

**Formula:** `Hosting cost per report = Fixed monthly hosting cost / reports sold that month`

| Input | Value | Status | Source |
|---|---|---|---|
| Landing page hosting (Carrd Pro Standard) | $19/year ≈ Rs 1,818/year ≈ **Rs 152/month** | Provisional | Carrd's published Pro Standard tier (cheapest tier with custom domain + forms + analytics), converted at USD/INR 95.7 |
| Domain name | ~$12/year ≈ Rs 1,148/year ≈ **Rs 96/month** | Provisional | Typical annual domain-registration cost; no specific registrar quote obtained |
| **Total fixed monthly hosting/tooling cost** | **Rs 250/month** (rounded, 152+96≈248) | Provisional | Sum of above |

This is a **fixed monthly cost, not a true per-report variable cost** — it is
apportioned across however many reports actually sell that month (see the
live formula in `RUNWAY-MODEL.xlsx`, row "Fixed monthly costs"). At the
charter's kill-bar volume (5 reports/month), that's Rs 50/report; at the
base-case volume (1–2/month), that's Rs 125–250/report.

### 1d. Operator's own time (QA)

**Explicitly excluded from cash cost, included as a separate constraint.**
Per `VENTURE-SELECTION.md`'s compliance note, each report requires **under 60
minutes of operator QA** before async delivery. This time costs no cash (the
operator draws no salary from the venture) — so it is excluded from the cash
unit-economics below, consistent with the operator not being a paid line
item in a solo build.

**What would make a time-valued version of this model Final:** No operator
hourly opportunity-cost rate has been provided anywhere in `CHARTER.md` or
`VENTURE-SELECTION.md` — the operator's prior salary figure is not stated. Per
standing rule 2 ("never invent data"), no rate is assumed here. If the
operator wants a fully loaded (cash + time) unit-economics view, they need to
supply an explicit hourly rate; until then, QA time is tracked as a **capacity
constraint** (see `01-strategy/RISKS.md` Risk #5: 7 hrs/week ≈ 30 hrs/month
total, shared across outbound, QA, and delivery), not a cost line.

### 1e. Total cost per report and gross margin

**Formula:**
`Gross margin per report = Ticket price − (AI/LLM cost + payment processing fee + tooling cost per report)`

At the recommended ticket price of **Rs 17,500** and the charter's kill-bar
volume of **5 reports/month**:

| Cost line | Value | Status |
|---|---|---|
| AI/LLM cost | Rs 250 | Provisional |
| Payment processing fee | Rs 619.50 | Provisional/Blocked (rail unconfirmed) |
| Tooling/hosting (apportioned, 5 reports/month) | Rs 50 | Provisional |
| **Total cost per report** | **Rs 919.50** | Provisional |
| **Gross margin per report** | Rs 17,500 − Rs 919.50 = **Rs 16,580.50** | Provisional |
| **Gross margin %** | 16,580.50 / 17,500 = **94.7%** | Provisional (derived) |

**Reading this:** gross margin is not the binding constraint on this venture
at any plausible volume — the cost structure is dominated by the payment
processing fee (≈3.5% of ticket), with AI/API costs and hosting both
negligible. This is consistent with `MARKET.md`/`RISKS.md`'s own conclusion:
the real risk is **sales volume/conversion**, not per-unit profitability. See
`RUNWAY-MODEL.xlsx` for how this plays out across scenarios and months.

---

## 2. Customer Acquisition Cost (CAC)

**Formula:**
`CAC (tooling-only, cash) = Cost per touch × (1 / close rate)`
`Cost per touch = Monthly outbound-tool cost / touches per month`

| Input | Value | Status | Source |
|---|---|---|---|
| Cold-outbound tool cost | Rs 3,000–5,000/month (RISKS.md) ≈ Rs 4,500/month (Instantly.ai Growth plan, ~$47/mo at 95.7) | Provisional | `RISKS.md` Risk #1 test budget; Instantly.ai published pricing corroborates the same order of magnitude |
| Touches/month by scenario | 150 (pessimistic) / 200 (base) / 250 (optimistic) | Final as general benchmark inputs, Provisional as applied to this venture | `MARKET.md` Section 2, Step 6 |
| Close rate by scenario | 0.2% (pessimistic) / 0.8% (base) / 3% (optimistic) | Final as general benchmark, Provisional as applied | `MARKET.md` Section 2, Step 6 |

**Cost per touch** = Rs 4,500 / touches-that-month:

| Scenario | Touches/mo | Cost/touch | Close rate | Touches needed per sale (1/close rate) | **CAC (tooling only)** |
|---|---|---|---|---|---|
| Optimistic | 250 | Rs 18.00 | 3.0% | 33.3 | 33.3 × Rs 18.00 = **Rs 600** |
| Base | 200 | Rs 22.50 | 0.8% | 125.0 | 125.0 × Rs 22.50 = **Rs 2,813** |
| Pessimistic | 150 | Rs 30.00 | 0.2% | 500.0 | 500.0 × Rs 30.00 = **Rs 15,000** |

All rows: **Provisional** (derived from Provisional/Final inputs above).

**Important caveat on the pessimistic row:** at 150 touches/month and a 0.2%
close rate, expected sales are 0.3/month — i.e. it takes **>3 months of
sustained tool spend** to generate one real sale, not one month. The "CAC"
figure above is a per-sale unit cost, not a same-month-recoverable number at
that scenario — flagged explicitly so it isn't misread as "affordable."

**Operator's own unpaid time for outbound is not included above.** Per
`RISKS.md` Risk #5, 150–250 touches/month at meaningful personalization
quality costs the operator an estimated **15–20 hours/month** of unpaid time.
If a real hourly rate is ever supplied (see §1d), a fully loaded CAC would be
materially higher than the tooling-only figures above — this is flagged as
**Blocked** pending that rate, not silently ignored.

### CAC-to-revenue ratio vs. the charter's <30% bar

**Reasoning stated explicitly, per the task's instruction:** cold outbound
(manual list-building, personalized LinkedIn/email sends) is **not** "paid
acquisition" in the Meta/Google-ad-spend sense the charter's 30% bar is
normally applied to — there is no per-click or per-impression spend. However,
the **cold-outbound tool cost** (Instantly.ai or equivalent) is real cash
spend closely analogous to paid acquisition infrastructure, so it is checked
against the 30% bar here as the closest honest proxy, rather than exempted
by definitional technicality.

**Formula:** `Ratio = Monthly outbound-tool cost / Monthly revenue`

| Scenario | Monthly revenue (MARKET.md) | Outbound-tool cost | **Ratio** | Clears <30% bar? |
|---|---|---|---|---|
| Optimistic | Rs 1,05,000–1,60,000 | Rs 3,000–5,000 | 3,000/1,60,000 to 5,000/1,05,000 = **1.9%–4.8%** | Yes, comfortably |
| Base case | Rs 15,000–40,000 | Rs 3,000–5,000 (fixed regardless of close rate) | 3,000/40,000 to 5,000/15,000 = **7.5%–33.3%** | **Marginal — breaches 30% at the low end of the base case** |
| Pessimistic | Rs 0–20,000 | Rs 3,000–5,000 | 3,000/20,000 to 5,000/0 = **15% to undefined (÷0)** | **No — breaches or is undefined when revenue is near zero** |

**This is a real finding, not a rounding artifact:** because the outbound
tool cost is a *fixed monthly cost* (you pay for the Instantly.ai plan
whether or not it converts), the CAC-to-revenue ratio is only comfortably
inside the charter's 30% bar in the optimistic scenario — the same scenario
that MARKET.md already flagged as the only one that clears the Rs 1L/month
bar at all. In the base and pessimistic cases, tooling spend is at real risk
of exceeding 30% of the revenue it produces, reinforcing why RISKS.md's
30-day test (which pays for exactly one month of this tool, not an ongoing
commitment) is the correct next step before any recurring tooling spend is
locked in.

---

## 3. LTV (Lifetime Value)

**This is explicitly a single-purchase product as currently scoped.** The
diagnostic report is a one-time deliverable — `VENTURE-SELECTION.md` describes
no subscription, retainer, or repeat-purchase mechanism (and a retainer
model is charter-banned as "ongoing service work"). No repeat-purchase rate
exists in any source document, and none is invented here per standing rule 2.

**Formula (as scoped today):**
`LTV = Gross margin on a single report = Ticket price − Cost per report`

At Rs 17,500 ticket: **LTV = Rs 16,580.50** (identical to gross margin per
report in §1e, since there is exactly one purchase per customer).

**Why this materially changes the charter's "recurring" success bar:** the
charter's Rs 1L/month bar is described as "recurring" — but with a
single-purchase product and no repeat customers, "recurring" can only mean
**recurring new-customer acquisition every month**, not recurring revenue
from a retained customer base (the SaaS/subscription sense of "recurring").
This venture must close 5–7 *new* customers **every single month, indefinitely**,
with no compounding installed base to fall back on. This is a materially
harder bar than a subscription business hitting the same monthly number, and
should be read that way — flagged here explicitly so it isn't glossed over.

**Not modeled (Blocked, no data):** a plausible future lever is a follow-up
"90-day re-audit" or upsell offer to past customers, which would turn this
into a repeat-purchase business and improve LTV substantially. This does not
exist in the current offer per `VENTURE-SELECTION.md` and is not modeled here
— flagged as a possible Phase 3+ addition, not assumed into any number above.

### CAC vs. LTV

| Scenario | CAC (tooling only) | LTV (single purchase) | LTV:CAC |
|---|---|---|---|
| Optimistic | Rs 600 | Rs 16,580.50 | ~27.6:1 |
| Base | Rs 2,813 | Rs 16,580.50 | ~5.9:1 |
| Pessimistic | Rs 15,000 | Rs 16,580.50 | ~1.1:1 |

**Reading this:** on a pure cash-cost basis, LTV:CAC looks healthy even in
the pessimistic case. This is consistent with §1e's finding — **per-unit
economics are not the risk here.** The real risk, as MARKET.md and RISKS.md
both establish, is whether enough *volume* of sales can be closed at all
inside the 7-hour/week ceiling — a conversion/capacity problem this ratio
does not capture, because CAC here excludes the operator's own unpaid time
(§1d/§2) which is the actual scarce resource.

---

## 4. Number status summary

| Number | Status | What would make it Final |
|---|---|---|
| AI/LLM cost per report (Rs 250) | Provisional | Real token usage measured across 10+ sample reports in Phase 2 |
| Payment processing fee (3.54%) | Provisional / Blocked | Operator confirms actual payment rail (Razorpay international, PayPal, or other) in Phase 2 |
| Hosting/tooling cost (Rs 250/month) | Provisional | Actual Carrd + domain purchase receipts |
| Operator time value | Blocked | Operator supplies an explicit hourly opportunity-cost rate, or explicitly declines to value it |
| CAC by scenario | Provisional | Real 150-touch outbound test (RISKS.md) replaces MARKET.md's general-benchmark-derived close rates with venture-specific ones |
| LTV (single-purchase) | Provisional (structurally Final unless the offer changes) | Only changes if a repeat-purchase offer is designed and sold — not currently in scope |
| CAC-to-revenue ratio vs. 30% bar | Provisional (derived) | Follows directly from CAC and revenue-scenario inputs above becoming Final |

---

## Sources

- Anthropic API pricing table (Claude Sonnet 5: $3.00/$15.00 per 1M tokens standard rate) — `claude-api` skill, cached 2026-06-24, confirmed current 2026-08-19
- [Federal Reserve H.10 Foreign Exchange Rates, 17-Aug-2026](https://www.federalreserve.gov/releases/h10/hist/dat00_in.htm) and market spot data — USD/INR ≈ 95.7–95.7, 18-Aug-2026
- Razorpay payment gateway pricing: [Razorpay Payment Gateway Charges 2026 — SoftwareSuggest](https://www.softwaresuggest.com/blog/razorpay-payment-gateway-charges/); [Razorpay Payment Gateway Pricing Explained](https://razorpay.com/blog/razorpay-payment-gateway-pricing-explained/)
- Stripe India fees and invite-only status: [Stripe Fees in India (2026) — Skydo](https://www.skydo.com/compare/stripe-pricing); [Stripe Review India 2026 — infinityapp.in](https://www.infinityapp.in/blog/stripe-review)
- Carrd pricing: [Carrd Pricing 2026 — Landingi](https://landingi.com/carrd/pricing/); [Carrd Pricing 2026: The $9 Plan Has No Custom Domain — Linkero](https://linke.ro/blog/carrd-pricing-2026)
- Instantly.ai pricing: [Instantly.ai Pricing 2026: Plans and Costs Breakdown — Landbase](https://www.landbase.com/blog/instantly-ai-pricing); [Instantly.ai Review: Pricing 2026 — Woodpecker](https://woodpecker.co/blog/instantly-ai-pricing/)
- `01-strategy/MARKET.md`, `01-strategy/RISKS.md`, `01-strategy/COMPETITORS.md`, `00-decisions/VENTURE-SELECTION.md`, `CHARTER.md` (this venture's own ground-truth documents — not re-derived, only referenced)
