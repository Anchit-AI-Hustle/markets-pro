# MARKET — Bottom-Up Sizing

Status: **Provisional**. Prepared by MARKET ANALYST agent, 2026-08-19. Adversarial
brief: stress-test Candidate A (productized async growth diagnostic reports),
not build a case for it. Per the charter's standing rules, this is bottom-up
sizing only — no global/top-down TAM figure appears anywhere in this document.
Every number below is labeled **Final**, **Provisional**, or **Blocked**.

---

## 1. Define the addressable universe (concretely)

The venture needs a buyer who is:
1. A D2C/e-commerce brand (not B2B SaaS, not services) — the operator's actual
   domain expertise.
2. Big enough to have live Meta/Google ad spend *and* a Klaviyo account *and*
   a landing page worth auditing — i.e. sophisticated enough that "flow
   sophistication," "ad account waste," and "CRO leaks" are real, fixable
   problems, not "you haven't started yet" problems.
3. Small/mid enough that Rs 15,000–20,000 is a real, self-funded, no-approval-
   chain purchase for a founder or solo marketer — not a rounding error an
   enterprise brand would route through procurement, and not below the size
   where an operator's Klaviyo/Meta review has anything real to say.
4. In a geography the operator can credibly serve async, with English-language
   outreach and no live-call requirement: **US, UK, India** (the operator's
   direct prior category experience is US+UK premium D2C tea/wellness;
   India is added here as a lower-friction, same-timezone secondary market,
   not because it was validated — flagged as an assumption, not a finding).

**Working definition of the addressable universe:** *Live Shopify Plus
stores, in the US or UK, with Klaviyo installed.* Shopify Plus is used as the
size/sophistication proxy (Plus historically required roughly $1M+/year GMV
to qualify, and Plus merchants skew toward brands running paid acquisition
and lifecycle marketing) — not a perfect proxy for "$1M–$20M revenue," but
the only proxy with real, citable data behind it. This likely **over-counts**
some enterprise brands too big/well-staffed to buy a cold Rs 15–20k audit,
and **under-counts** non-Plus Shopify stores and non-Shopify D2C stores
(Shopify Advanced/Basic, WooCommerce, custom stacks) that are also legitimate
ICP fits. Both distortions are named explicitly in ICP.md rather than
corrected for here, because no clean data source separates them.

## 2. The math chain (every step shown, every input labeled)

### Step 1 — Shopify Plus stores, US + UK

| Input | Value | Status | Source |
|---|---|---|---|
| Live Shopify Plus stores, US | 41,137 | Provisional | uptek.com "Shopify Plus Statistics 2026" (industry blog aggregating store-tracking data; not a primary Shopify disclosure) |
| Live Shopify Plus stores, UK | 5,534 | Provisional | Same source as above |
| **Sum, US+UK** | **46,671** | **Provisional** | Same source; single-source figure, not cross-verified |

Caveat, stated plainly: total worldwide Shopify Plus store counts vary
**2x across sources found in this research** — from ~47,000 to ~85,334
depending on methodology (live domains vs. distinct merchants vs. all-time
vs. currently-active). The US/UK breakdown above comes from one source only.
Treat 46,671 as an order-of-magnitude anchor, not a precise count. This
uncertainty is carried forward through every step below.

### Step 2 — Filter to Klaviyo-installed

| Input | Value | Status | Source |
|---|---|---|---|
| % of Shopify Plus stores with Klaviyo installed | 61.5% | Provisional | uptek.com, citing BuiltWith-style install-tracking data |
| **Shopify Plus stores, US+UK, running Klaviyo** | 46,671 × 0.615 ≈ **28,700** | Provisional | Derived |

### Step 3 — Filter to active Meta ad spend

| Input | Value | Status | Source |
|---|---|---|---|
| % of Shopify Plus stores with Facebook marketing channel installed | 60.7% | Provisional | Shopify Plus statistics aggregation (bootleads.com / trend-tracking sources) |

This is a **usage/install** figure (has the Facebook/Instagram sales channel
connected), not a **confirmed active-spend** figure (is currently running
paid ads today). No source found in this research separates "connected
Meta channel" from "actively spending on Meta ads right now." Applying the
install rate as an upper-bound proxy for active-spend is a deliberately
generous assumption that likely overstates the true number — flagged, not
hidden:

| Input | Value | Status |
|---|---|---|
| Shopify Plus, US+UK, Klaviyo + Meta-channel-connected (upper bound) | 28,700 × 0.607 ≈ **17,400** | Provisional (upper bound; true active-Meta-spend number is lower, exact fraction Blocked) |

**Blocked:** the fraction of that 17,400 actually spending meaningfully on
Meta ads *today* (vs. dormant channel connections) is not available from any
source found in this research. Unblocking it needs a paid data tool
(Storeleads Pro tier, ~$250/mo, or a Meta Ad Library scrape cross-referenced
against the Shopify Plus + Klaviyo list) — out of scope for this pass, named
here as a concrete next step rather than guessed.

### Step 4 — This is the addressable universe

**≈ 17,000–29,000 stores** (17,400 as the Meta-filtered estimate, 28,700 as
the Klaviyo-only estimate before the Meta filter is applied) — this range,
not a single number, is the honest output of Steps 1–3. **Provisional**,
built from real cited sources with real methodology gaps stated at each step.

### Step 5 — Realistic cold-outbound reach (solo operator, 7 hrs/week)

The operator is not reaching the full addressable universe — cold outbound
at charter time budget only reaches a hand-curated slice.

| Input | Value | Status | Reasoning |
|---|---|---|---|
| Outbound sending capacity, solo, 7 hrs/week, factoring in list-building, personalization, sending, replying, QA (per VENTURE-SELECTION.md steelman point 1) | ~150–250 quality touches/month | Provisional | Reasoned estimate: at ~5–8 minutes of researched, personalized touch (not mass-blast) per prospect, 7 hrs/week × 4.3 weeks ≈ 30 hrs/month, minus time needed for report QA and delivery once sales start, leaves roughly 15–20 hrs/month purely for outbound → 150–250 touches at that pace. No external benchmark exists for *this specific operator's* throughput; this is a time-budget-derived estimate, not a market number. |
| Addressable universe reachable per month as fraction of 17,400–28,700 | 150–250 / ~20,000 ≈ **0.75%–1.25% of the universe per month** | Provisional (derived) | At this reach rate, the operator could theoretically contact the *entire* addressable universe once across roughly 7–11 years — reach is not the binding constraint in month 1–3, targeting precision and message quality are. |

### Step 6 — Realistic close rate → revenue

| Input | Value | Status | Source |
|---|---|---|---|
| B2B cold email average reply rate | 3.43% (range 3–5.1%; top quartile 15–25%) | Final | Multiple 2025/2026 cold-email benchmark aggregators (Instantly.ai, Belkins, thedigitalbloom) — figures are marketing-industry self-reported benchmarks, not academic data, hence Final only in the "this is a real, citable, converging figure across independent sources" sense, not lab-verified |
| Meeting-booked rate per email sent | 0.5%–2.5% | Final (same caveat) | Instantly.ai / martal.ca cold email benchmarks 2026 |
| Cold-outbound-sequence close rate (contact → paid deal), blended | ~0.2%–3% (0.2% "average deal-close," 3% cited as a cold-sequence-specific figure) | Final (same caveat) | tomba.io / martal.ca sales statistics 2026 |

These are **general B2B cold-email benchmarks**, not specific to "asking a
stranger to hand over ad-account and Klaviyo access and pay upfront with zero
social proof" — the steelman in VENTURE-SELECTION.md is right to flag that
this specific ask (account access + upfront payment + zero case studies) is
harder than a typical cold-outbound SaaS-demo ask, which is what most of
these benchmarks measure. No source found decomposes cold-B2B-close-rate
specifically by "pay-upfront-no-call" offers — this decomposition is
**Blocked**; the general benchmark is used as a ceiling, with an explicit
downward adjustment applied because of the harder ask:

| Scenario | Close rate assumption | Touches/month | Sales/month | Revenue/month @ Rs 15,000–20,000/report |
|---|---|---|---|---|
| Optimistic (general B2B cold-outbound close rate, upper end) | 3% | 250 | 7.5 → **7–8** | Rs 1,05,000–1,60,000 |
| Base case (harder ask than typical benchmark; midpoint of 0.2–3% range, adjusted down for the account-access/upfront-pay friction) | 0.8% | 200 | 1.6 → **1–2** | Rs 15,000–40,000 |
| Pessimistic (bottom of general benchmark range, applied as-is to a harder-than-average ask) | 0.2% | 150 | 0.3 → **0–1** | Rs 0–20,000 |

All three rows: **Provisional** — the close-rate inputs are Final as *general
B2B benchmarks*, but their application to this specific offer is a reasoned
adjustment, not a verified number for this venture. The venture's own
kill number (5 sales/month = Rs 1,00,000+) sits **above the optimistic case
in this model and far above the base case** — i.e. bottom-up sizing using
real, cited general B2B cold-outbound benchmarks does not comfortably clear
the charter's Rs 1L/month bar; it requires performance in the top decile of
general cold-outbound benchmarks *while also carrying a harder-than-average
ask*, sustained for 3 straight months, inside a 7-hour/week ceiling that also
has to cover report QA and delivery once sales exist.

## 3. Bottom-up revenue estimate — summary

| | Monthly revenue | Clears Rs 1L/month bar? |
|---|---|---|
| Optimistic | Rs 1,05,000–1,60,000 | Barely, only at top-decile cold-outbound performance |
| Base case | Rs 15,000–40,000 | No |
| Pessimistic | Rs 0–20,000 | No |

**This is the single most important output of this document:** the bottom-up
model, built from real cited benchmarks rather than the "5–7 sales is a low
absolute number" framing in VENTURE-SELECTION.md, shows Rs 1L/month is
reachable **only in the optimistic case**, which requires closing at general-
B2B-benchmark top-tier rates on an offer that is structurally harder to close
cold than the benchmarks' underlying sample (which is dominated by SaaS
demo-booking and lower-commitment asks, not "pay Rs 15–20k upfront, no call,
to a stranger"). The base and pessimistic cases — arguably the more likely
ones given the harder ask — land at 15–40% and 0–20% of the charter's bar,
respectively.

## 4. What would upgrade these numbers from Provisional to Final

1. A paid Storeleads/BuiltWith export cross-tabbing Shopify Plus + Klaviyo +
   confirmed active Meta ad spend (via Meta Ad Library presence, not just
   channel-install) for US+UK — resolves Step 3's Blocked fraction. Cost:
   ~$250/mo (Storeleads Pro tier, per syncgtm.com review cited above).
2. The operator's own first 200–300 real outbound sends, tracked for reply
   rate, meeting-request-for-a-call rate, and close rate — this is the only
   way to convert Step 6 from a general-benchmark-derived range to a real,
   venture-specific number, and is exactly what RISKS.md's Risk #1 test is
   designed to produce inside 30 days.

## Sources

- [Shopify Plus Statistics 2026: Growth, Revenue & Top Brands](https://uptek.com/shopify-statistics/plus/)
- [Shopify Plus Statistics 2026 — Store Leads](https://storeleads.app/reports/shopify/list-of-shopify-plus-stores)
- [142.9K Shopify stores running Meta ads — bootleads.com](https://bootleads.com/stores/shopify/segments/meta-ads/)
- [Store Leads Review 2026: Pricing & Coverage — syncgtm.com](https://syncgtm.com/blog/store-leads-review-2026)
- [Cold Email Response Rates: B2B Benchmarks — Instantly.ai](https://instantly.ai/blog/cold-email-reply-rate-benchmarks/)
- [B2B Cold Email Statistics 2026 — martal.ca](https://martal.ca/b2b-cold-email-statistics-lb/)
- [What are B2B Cold Email Response Rates? (2026 Study) — Belkins](https://belkins.io/blog/cold-email-response-rates)
- [Cold Email Reply-Rate Benchmarks 2025 — thedigitalbloom.com](https://thedigitalbloom.com/learn/cold-outbound-reply-rate-benchmarks/)
- [Average Close Rate for Sales — Tomba Blog](https://tomba.io/blog/average-close-rate-for-sales)
- [Sales Statistics 2026: Outbound, Pipeline & Funnel Data — martal.ca](https://martal.ca/sales-statistics-lb/)
