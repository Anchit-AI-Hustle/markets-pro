# ICP — Ideal Customer Profile

Status: **Provisional**. Prepared by MARKET ANALYST agent, 2026-08-19. Goal:
precise enough to generate 20 real named companies or an exact, reusable
ad-platform/data-tool filter set. Per research constraints hit in this pass
(no live access to Meta Ads Library UI, Sales Navigator, or a paid
Shopify-store-data tool from this environment), this document delivers the
**exact filter criteria** someone would run, plus a small number of
**illustrative real brand names** found via open search — labeled by
confidence — rather than a fabricated list of 20 companies with invented
qualifying details. Fabricating "20 companies match this profile" without
verifying each one against the actual criteria would violate the charter's
"never invent data" rule; that tradeoff is stated here explicitly.

---

## 1. Firmographic filters (concrete, usable as-is in a paid data tool)

| Dimension | Filter value | Status | Why |
|---|---|---|---|
| Platform | Shopify Plus, or Shopify (non-Plus) with $1M–$15M estimated annual revenue | Provisional | Plus is the size proxy used in MARKET.md; non-Plus stores in this revenue band are also legitimate but require a different data source (see below) |
| Geography | US, UK primary; India secondary | Final (from CHARTER.md operator background + VENTURE-SELECTION.md geography note) | Matches operator's actual US+UK premium D2C tea/wellness experience; India added for same-timezone reach, not validated |
| Tech stack — email/lifecycle | Klaviyo installed (not Mailchimp, not Omnisend, not "none") | Final (as a filterable signal — Klaviyo is BuiltWith/Storeleads-detectable) | Klaviyo-specific expertise is the operator's strongest differentiator; a brand not on Klaviyo isn't a fit for the flow-audit component as scoped |
| Tech stack — ads | Active Meta Pixel/Conversions API installed; ideally also visible in Meta Ad Library as a currently-active advertiser | Provisional (install signal is Final/detectable; "currently active" requires Ad Library cross-check, not done in this pass) | Confirms there's a live ad account worth auditing |
| Employee count | 5–50 employees (LinkedIn company size filter) | Provisional | Reasoned proxy for "big enough to have a growth function worth diagnosing, small enough to lack a senior in-house growth hire" |
| Revenue band | $1M–$15M/year estimated | Provisional | Below $1M: unlikely to have flow/ad sophistication worth auditing or budget for Rs 15–20k. Above $15–20M: more likely to have an in-house growth director or retained agency already doing this work, and Rs 15–20k reads as too small a purchase to route through their process |
| Category | Beauty/skincare, wellness/supplements, food & beverage, apparel — consumer packaged D2C, repeat-purchase model | Provisional | Matches operator's direct tea/wellness background; repeat-purchase categories are where Klaviyo flow sophistication (winback, replenishment, post-purchase) matters most, maximizing the audit's perceived value |

## 2. Behavioral / signal-based filters (the "good fit" tells)

These are the signals an operator would manually check per-prospect before
sending outreach — they cannot be fully automated without a paid tool, but
each is independently verifiable by hand (free, ~2–3 minutes per prospect):

1. **Visibly running Meta ads with generic/templated creative** — checkable
   free via Meta Ad Library (adlibrary.facebook.com) search by brand/domain;
   look for ads that have been running with little creative refresh (signal
   of "spray and pray" or under-optimized management, i.e. an audit would
   find real issues).
2. **Klaviyo installed but no visible sign of an in-house lifecycle hire** —
   checkable via LinkedIn company page: search the company for titles like
   "Lifecycle Marketing Manager," "CRM Manager," "Email Marketing Manager."
   Absence of any such title at a company with 10+ employees is a positive
   signal (nobody owns flows full-time, so audit findings are more likely
   to be real and unaddressed).
3. **No senior in-house growth/performance-marketing hire** — checkable via
   LinkedIn: absence of "Head of Growth," "Director of Growth," "VP
   Marketing," "Performance Marketing Manager" titles at the company.
   Presence of one is a negative signal — that person is a competitor-inside-
   the-deal, likely to either resent an outside audit or already know what
   it would find.
4. **Landing pages / PDPs that look templated or unoptimized** — checkable
   free by browsing the storefront directly: default theme, no visible
   social proof widgets, slow load, no apparent A/B testing tool (Intelligems,
   Kameleoon, VWO) installed. Absence of a CRO tool is itself a signal —
   checkable via BuiltWith's free single-URL lookup.
5. **Recent funding, founder LinkedIn post about "scaling," or a recent
   founder AMA/podcast appearance mentioning growth challenges** — a warmth
   signal that can justify a more personalized (higher-response) outbound
   message; checkable via LinkedIn search and a Google News search on the
   brand name.

## 3. Exact filter sets for real tools

### A. Meta Ads Library (free, no login required)

`adlibrary.facebook.com/ads/library` → filter by:
- Ad category: All ads
- Country: United States / United Kingdom (run separately)
- Search by keyword/category is limited on the free tool — the practical
  workflow is to search specific brand/domain names pulled from Step B or C
  below, not to browse Ad Library as a discovery tool from scratch (it isn't
  built for broad prospecting without an advertiser name to start from).

### B. LinkedIn Sales Navigator (paid, ~$99/month individual tier — cost not
independently re-verified in this pass, Blocked pending current LinkedIn
pricing page check)

Boolean / filter combination:
- **Job title:** ("Founder" OR "Co-Founder" OR "CEO" OR "Owner" OR "Head of
  Growth" OR "Head of Marketing" OR "Ecommerce Manager")
- **Company headcount:** 11–50
- **Company industry:** "Consumer Goods," "Retail," "Health, Wellness &
  Fitness," "Cosmetics"
- **Geography:** United States, United Kingdom
- **Keyword (company or profile):** "Shopify" OR "DTC" OR "D2C" OR
  "direct-to-consumer"

This matches the general filtering approach confirmed via search (title +
industry + geography + keyword combination is the standard Sales Navigator
workflow for this kind of prospecting) — cited below. Actual candidate names
require running this search inside a live Sales Navigator seat, which this
research pass does not have access to; **Blocked** for producing real names
this way without that access.

### C. Shopify-store data tools (paid)

**Storeleads.app** — Pro tier ~$250/month (per syncgtm.com review, cited in
MARKET.md) — supports exactly this compound filter: platform = Shopify Plus,
app installed = Klaviyo, country = US/UK, traffic or revenue band, app
installed = [CRO tool] absent. This is the single most direct way to
generate a real, verified list of 20+ named companies matching the ICP
precisely — **Blocked** in this research pass because it requires a paid
subscription not available to this agent; named here as the concrete next
step rather than substituted with guessed company names.

**BuiltWith** — free single-URL lookups can verify Klaviyo + Meta Pixel
presence one domain at a time once candidate brand names exist from another
source (e.g. a category-specific "best D2C wellness brands" listicle); not a
bulk-discovery tool on the free tier.

## 4. Illustrative real brands (confidence-labeled, not a verified ICP list)

The following are D2C brands in wellness/beauty/CPG categories that are
publicly known to run Shopify + Klaviyo + Meta ads at a plausible size for
this ICP, based on general industry familiarity and open search — **these
are named as illustrative examples of the category the ICP describes, not
as verified, individually-qualified leads**. Each would need the Section 2
behavioral checks run against it individually before outreach; none of that
verification was done in this pass. Labeled **Provisional (illustrative
only, unverified against filter criteria)**:

- Various mid-size independent skincare/supplement/tea brands in the
  $1M–$15M range are known to run on this exact stack (Shopify Plus +
  Klaviyo + Meta) as a matter of category norm — Klaviyo's own install base
  data (61.5% of Shopify Plus stores, per MARKET.md) confirms this is the
  *default* stack for the segment, not an exception.

Naming specific real companies here with confidence, without running them
through Section 2 and 3's actual verification tools, would risk exactly the
kind of unverified, invented-sounding specificity the charter's "never
invent data" rule exists to prevent. **This is intentionally left as a
Blocked deliverable** rather than papered over with plausible-sounding
brand names: the correct unblock is 2–3 hours with a Storeleads Pro trial
or Sales Navigator seat, running the exact filters in Section 3, which
would produce a real, verifiable 20-company list quickly and cheaply
relative to the venture's own Rs 2–3L ceiling.

## 5. What disqualifies a prospect (negative filters)

- Already has a named in-house growth/lifecycle hire (signal 3 above) —
  audit findings likely already known internally, and that hire is a
  natural internal blocker to an outside audit being acted on.
- Uses an email platform other than Klaviyo (Mailchimp, Omnisend, etc.) —
  outside the operator's specific tool expertise; audit quality and
  credibility both drop.
- Enterprise scale (>$20M/year, >50 employees, likely on Shopify Plus
  Advanced or a retained agency already) — Rs 15–20k reads as too small a
  transaction to process, and existing agency relationships crowd out a
  cold audit offer.
- No visible active ad spend at all (Meta Pixel present but no Ad Library
  presence) — nothing for the ad-audit component to diagnose.

## Sources

- [Shopify Plus Statistics 2026 — uptek.com](https://uptek.com/shopify-statistics/plus/) (Klaviyo install rate on Plus)
- [Store Leads Review 2026 — syncgtm.com](https://syncgtm.com/blog/store-leads-review-2026) (Storeleads pricing/filter capability)
- [How to find e-commerce owners on LinkedIn — Quora](https://www.quora.com/How-do-I-find-e-commerce-owners-on-LinkedIn)
- [DTC Ecommerce Founders Prospecting (2026 Guide) — Origami](https://origami.chat/blog/prospect-dtc-ecommerce-founders-ceos-2026)
- [Best Tools for Finding Ecommerce Brand Decision Makers (2026) — Origami](https://origami.chat/blog/best-tools-finding-ecommerce-brand-decision-makers)
