# RISKS — Top 5 Ways This Venture Dies

Status: **Provisional**. Prepared by MARKET ANALYST agent, 2026-08-19.
Ranked by probability (highest first). Each risk includes a concrete test
costing under Rs 10,000, completable within 30 days, with named results that
would falsify vs. confirm the risk. Per instructions, Risk #1 extends the
cold-outbound-conversion risk already flagged in VENTURE-SELECTION.md's
steelman (point 1) with real research rather than restating it as opinion,
and Risk #4 covers the compliance-boundary-fragility risk (steelman point 2).

---

## Risk #1 (highest probability): Cold B2B outbound does not convert enough strangers into paid, upfront, no-call sales to hit 5 sales/month

**The claim, extended with real data (not restated opinion):**
VENTURE-SELECTION.md's steelman asserted this qualitatively. MARKET.md's
Section 2, Step 6 puts real, cited numbers behind it:

- General B2B cold email reply rates: **3–5.1%** average, **top quartile
  15–25%** (Instantly.ai, Belkins, thedigitalbloom — 2025/2026 aggregated
  benchmarks). **Final** as general benchmarks.
- Meeting-booked rate per email sent: **0.5–2.5%** (Instantly.ai/martal.ca).
  **Final** as general benchmarks.
- Cold-outbound-sequence close rate, contact → paid deal: **0.2–3%** blended
  across sources (tomba.io, martal.ca). **Final** as general benchmarks.

Applying the base case from MARKET.md (200 touches/month at a below-top-
decile close rate, adjusted down from the general benchmark because this
offer is a harder ask than a typical cold SaaS-demo benchmark — asking a
stranger for account access and upfront payment, zero case studies, no
social proof) yields **1–2 sales/month**, well under the 5-sale kill
threshold. Only the optimistic case (top-decile close rate applied despite
the harder ask) clears 5 sales/month. This is the single largest gap between
the venture's original "5–7 sales is a low absolute number, therefore
achievable" framing and what cited general-market benchmarks actually
support once the harder-than-average nature of this specific ask is
factored in.

**Why this is #1:** every other risk in this document is downstream of this
one. If outbound doesn't convert, nothing else (pricing, compliance,
competition) matters — there's no revenue to protect.

**The 30-day test — cost under Rs 10,000:**

- **Test:** Send **150 real, individually-researched, personalized cold
  outbound messages** (LinkedIn + email combined) to a hand-built list
  matching ICP.md's criteria, using the actual planned offer and price
  point (Rs 15,000–20,000, no call, async delivery) — before the report
  pipeline is even built. Track replies, "interested but wants a call"
  responses, and actual paid conversions (can be a manual/placeholder
  delivery process for this test — the point is testing the *sale*, not the
  *pipeline*).
- **Cost:** List-building via free LinkedIn search + free Meta Ad Library
  cross-checks (operator's own time, not counted in the Rs 10,000 cap) +
  optional Rs 3,000–5,000 for a cold email sending tool (e.g. Instantly.ai
  or similar, monthly plan) to manage deliverability and tracking. Well
  under Rs 10,000.
- **Falsifies the risk (green light):** ≥3 paid conversions from 150
  touches (2% close rate) — near the top of the general benchmark range,
  suggesting the offer/ICP combination beats the "harder ask" discount this
  model applied, and 5–7 sales/month is reachable at moderately higher
  volume.
- **Confirms the risk (red light / early kill signal):** 0–1 paid
  conversions from 150 touches (<0.7% close rate) — in line with or below
  the base-case model, meaning 5 sales/month would require 700+ touches/
  month, which is not sustainable inside the 7-hour/week ceiling once
  outreach *and* QA *and* delivery are all counted. This is a legitimate
  early-kill signal, not a "try harder" signal, precisely because it would
  be measured *before* the 3-week build phase, saving that time.

---

## Risk #2: Ticket price (Rs 15,000–20,000) is untested and may be wrong in either direction

**The claim:** Every revenue calculation in MARKET.md and VENTURE-SELECTION.md
depends on a price that has never been shown to a real buyer. If it's too
high, it adds to Risk #1's conversion problem. If it's too low, hitting
Rs 1L/month requires even more sales than the 5–7/month currently modeled,
worsening the QA-time math flagged in VENTURE-SELECTION.md's steelman point 3.
COMPETITORS.md found real anchor prices nearby: Fiverr Klaviyo-only audits
at $20–$160, FlowAudit's AI Klaviyo report at $75, and full-scope agency
audits at $510–$2,040 — this venture's Rs 15,000–20,000 (~$180–$240) sits
inside a price band where a buyer can find both much cheaper (automated,
Klaviyo-only) and comparably-priced fuller-service (with a call, with a
human relationship) alternatives in one search.

**The 30-day test — cost under Rs 10,000:**

- **Test:** Build a single one-page landing page describing the exact offer
  (scope, no-call structure, turnaround time) with a real Stripe/Razorpay
  payment link at Rs 17,500 (the midpoint of the assumed range). Drive the
  150 outbound touches from Risk #1's test directly to this page instead of
  a generic pitch, and separately show the same page/price to 5–10 people
  in the operator's extended professional network (not warm friends —
  people who fit the ICP but aren't being counted as "distribution" per
  VENTURE-SELECTION.md's zero-audience assumption) for direct price
  feedback.
- **Cost:** Landing page (can be built free on Carrd/a simple static page) +
  Stripe/Razorpair setup (free to set up, only transaction fees on an
  actual sale) — effectively Rs 0–2,000.
- **Falsifies the risk:** At least 1 real prepayment clears at Rs 17,500
  within 30 days, and informal price feedback doesn't concentrate around
  "too expensive vs. Fiverr/FlowAudit" or "too cheap vs. an agency
  engagement" — i.e. the price sits in a validated middle.
- **Confirms the risk:** Zero prepayments, and/or 3+ independent people
  reference a specific cheaper alternative (FlowAudit, Fiverr, a free
  agency audit) unprompted as a reason to hesitate — direct evidence the
  price is anchored against real, findable competition, not existing only
  as a Provisional planning number.

---

## Risk #3: The offer is not differentiated enough from existing free/cheap alternatives to justify cold trust

**The claim:** COMPETITORS.md's Section 3 verdict is the basis for this risk:
6,000+ Klaviyo agencies, at least two AI-automated point tools (AuditRoger,
FlowAudit) doing the automation mechanic this venture treats as its edge,
and a dominant free-audit-as-lead-magnet pattern across full-service
agencies all compete for the same buyer's attention. A cold prospect who
searches "Klaviyo audit" before replying to an unknown outbound message —
a very likely behavior for a skeptical buyer — will find a $75 self-serve
AI alternative or a free full-service offer within one search, both without
the specific commitment (pay upfront, no call, unknown solo operator) this
venture asks for.

**The 30-day test — cost under Rs 10,000:**

- **Test:** In the same outbound sequence as Risk #1's test, explicitly ask
  non-converting repliers who show initial interest but don't buy: "what
  made you hesitate?" Track how many cite a specific named or implied
  cheaper/free alternative unprompted.
- **Cost:** Rs 0 — folded into Risk #1's test, no additional spend.
- **Falsifies the risk:** Hesitation reasons cluster around trust/timing/
  budget-authority, not "I can get this cheaper/free elsewhere."
- **Confirms the risk:** 2+ repliers independently reference a cheaper or
  free alternative as their reason for not proceeding.

---

## Risk #4: Compliance-boundary fragility — buyers ask for "just a 15-minute call" before paying, and the venture quietly becomes a consulting practice

**The claim (per VENTURE-SELECTION.md steelman point 2, treated here as a
real operational risk, not restated as pure opinion):** the entire case
that this isn't "ongoing service work" (charter-banned) rests on zero calls
and zero bespoke follow-up, ever. A cold, trust-starved buyer being asked to
pay Rs 15–20k upfront to an unknown solo operator, with the same buyer able
to find agencies offering a **free** audit *with* a call (per COMPETITORS.md
Section 1, item 5) in the same search session, has a strong, rational reason
to ask this venture for the same courtesy before paying. The commercial
instinct of a recently-departed growth director — per the steelman — is to
take that call rather than lose the sale. No external benchmark exists for
"what fraction of cold B2B prospects request a pre-sale call" — this is
correctly treated as an internal process-discipline risk, not a market-data
question, and no number here is invented to fill that gap.

**The 30-day test — cost under Rs 10,000:**

- **Test:** During Risk #1's 150-touch outbound test, track and log every
  instance of a prospect requesting a call, a "quick chat first," a demo, or
  any synchronous interaction before payment — regardless of whether the
  operator grants it. Pre-commit, in writing, to a fixed script response
  ("we don't do calls — here's exactly what's in the report and how
  delivery works async") and track how many of those prospects proceed to
  pay anyway after the async-only boundary is held.
- **Cost:** Rs 0 — folded into Risk #1's test, no additional spend.
- **Falsifies the risk:** Call requests are rare (<10% of interested
  replies) and/or holding the async-only line doesn't kill the sale — most
  prospects proceed anyway once the boundary is stated clearly.
- **Confirms the risk:** Call requests are common (>30% of interested
  replies) and/or holding the line visibly kills most of those sales —
  direct evidence that the charter's "no calls" rule and "close 5–7 sales/
  month" target are in tension with each other for this specific offer,
  which is exactly the failure mode VENTURE-SELECTION.md's PHASE-0-GATE
  was told to watch for.

---

## Risk #5: QA time per report and delivery overhead don't actually fit inside the 7-hour/week ceiling once outbound is also running

**The claim:** VENTURE-SELECTION.md's steelman point 3 flags this at the
Rs 5L/month ambition level (25–33 hours of QA alone against a ~28–30
hour/month total budget). The same math applies, less dramatically but
still materially, at the Rs 1L/month kill-bar level: 5–7 reports/month ×
under-60-minutes QA = **5–7 hours/month on QA alone**, which is fine in
isolation, but Risk #1's own test above estimates **150–250 outbound
touches/month need roughly 15–20 hours/month** to execute at meaningful
personalization quality. QA + outbound + intake handling + report delivery
+ any pipeline maintenance, all inside a 30-hour/month (7 hr/week) ceiling,
leaves very little margin for the pipeline still being actively built and
debugged in the same weeks sales are supposed to be happening (per the
steelman's original framing) — this is a real time-budget risk independent
of whether the market/pricing/compliance risks above are resolved.

**The 30-day test — cost under Rs 10,000:**

- **Test:** During the Risk #1 outbound test month, have the operator
  **time-track every hour spent** (list-building, personalization, sending,
  replying, any manual "report mockup" QA-equivalent work) using a free
  time tracker (Toggl free tier or a manual spreadsheet), against the
  actual 30-hour/month budget, in real conditions rather than estimated
  ones.
- **Cost:** Rs 0 (Toggl free tier or a spreadsheet).
- **Falsifies the risk:** Total logged hours for 150 outbound touches +
  any sales-related admin stays comfortably under ~20 hours/month, leaving
  real margin for QA and pipeline work once sales exist.
- **Confirms the risk:** Total logged hours already exceed ~25 hours/month
  for outbound alone, before any report QA or pipeline-building time is
  added — direct evidence the 7-hour/week ceiling cannot support this
  venture's full operating loop even before Phase 2's build is finished.

---

## Summary table

| Rank | Risk | 30-day test | Cost |
|---|---|---|---|
| 1 | Cold outbound doesn't convert to 5 paid sales/month | 150 real outbound touches at real price, track close rate | ~Rs 3,000–5,000 |
| 2 | Rs 15,000–20,000 ticket price is wrong | Landing page + payment link tested against real outbound traffic | ~Rs 0–2,000 |
| 3 | Offer not differentiated from free/cheap alternatives | Exit-question repliers who don't convert, log cited alternatives | Rs 0 (folded into #1) |
| 4 | Compliance boundary breaks under call requests | Log and script-test every call request during outbound test | Rs 0 (folded into #1) |
| 5 | 7-hr/week ceiling doesn't fit outbound + QA + delivery | Real time-tracking during the same test month | Rs 0 |

All five tests can run **concurrently, inside the same 30-day, under-
Rs 10,000, single 150-touch outbound campaign** — this is a deliberate
design choice: one real-world test produces falsifying or confirming
evidence for all five risks at once, before any Phase 2 build spend.

## Sources

(Same benchmark sources as MARKET.md Section 2, Step 6, re-applied here —
not re-derived.)

- [Cold Email Response Rates: B2B Benchmarks — Instantly.ai](https://instantly.ai/blog/cold-email-reply-rate-benchmarks/)
- [B2B Cold Email Statistics 2026 — martal.ca](https://martal.ca/b2b-cold-email-statistics-lb/)
- [What are B2B Cold Email Response Rates? (2026 Study) — Belkins](https://belkins.io/blog/cold-email-response-rates)
- [Cold Email Reply-Rate Benchmarks 2025 — thedigitalbloom.com](https://thedigitalbloom.com/learn/cold-outbound-reply-rate-benchmarks/)
- [Average Close Rate for Sales — Tomba Blog](https://tomba.io/blog/average-close-rate-for-sales)
- [Sales Statistics 2026 — martal.ca](https://martal.ca/sales-statistics-lb/)
- Competitor pricing cited from `01-strategy/COMPETITORS.md` (this module)
