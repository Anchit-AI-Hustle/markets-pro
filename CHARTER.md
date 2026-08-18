# CHARTER — Solo Venture Build

Status: **Provisional** — active document, source of truth for all agents and gates in this build.

## Operator

Anchit Tandon. Ex-Senior Director of Growth, premium D2C tea/wellness, US + UK
markets. Last salaried day: 9 Sep 2026. Strong in Meta/Google performance
marketing, Klaviyo lifecycle, landing pages, CRO, analytics, AI-assisted
shipping. India-based. Solo — no hires, no co-founder.

## Constraints

- **Capital at risk:** Rs 2–3L total. Nothing more. No exceptions without an
  explicit charter amendment.
- **Revenue timeline:** First revenue by month 2. Month 3 is the absolute
  latest. A candidate that cannot plausibly clear this is disqualified in
  Phase 0, not carried forward "to see."
- **Success bar:** Rs 1L/month recurring, with paid acquisition under 30% of
  revenue.
- **Team:** Solo. Any plan requiring a second human (co-founder, hire,
  contractor on the critical path) is invalid.

## Time Budget

**1 hour/day. 7 hours/week. Hard ceiling.** No exceptions.

This rules out:
- Synchronous delivery of any kind
- Client calls
- Ongoing service work
- Anything requiring live availability in US or UK working hours
- Any build phase longer than 3 weeks

Only ventures where **the asset does the selling** and **the work is done
once** are permitted (content, product, or system that sells without the
operator being present transaction-by-transaction).

Every module in this build must be completable by an AI agent with **under
60 minutes of operator review**.

**If nothing clears the month-3 revenue bar at this time budget, Phase 0 must
say so directly rather than forcing a candidate through.**

### Flag — income during build

The operator has no salary from 10 September 2026. Phase 0 must flag,
explicitly, whether a 7-hour/week ceiling is realistic only because other
income exists during the build window, and must ask the operator directly
whether that other income exists. This is not assumed either way here.

## Standing Rules — apply to every agent, every module

1. State assumptions explicitly.
2. Never invent data. If a number isn't known, it isn't guessed.
3. Label every number **Final**, **Provisional**, or **Blocked**.
4. Cheapest test before any build.
5. Pre-sell over build, wherever a pre-sell is possible.
6. Every recommendation names a **kill number** and a **kill date**.
7. Outputs are files, not chat prose.
8. Never rename or restructure source data.
9. Live formulas in spreadsheets — never hardcoded results.
10. All UI work uses the frontend-design skill — never default or templated
    styling.
11. Voice in customer-facing copy is **first person plural** ("we", not "I").

## Folder Structure

```
/00-decisions   — venture selection, gates, sign-offs, kill decisions
/01-strategy    — market, ICP, competitors, risks
/02-finance     — unit economics, pricing, runway model, kill criteria
/03-product     — PRD, module map, roadmap
/04-brand       — naming, brand kit, voice, messaging
/05-design      — design system, flows, rationale
/06-build       — engineering output (frontend, backend, analytics)
/07-qa          — test plan, results, money path, security, compliance
/08-growth      — channel plan, first 100, creative brief, lifecycle flows
/09-ops         — runbook, launch checklist, ongoing operations
BUILD-LOG.md    — running log: what shipped, what was skipped, blockers, next module, days elapsed vs. month-2 target
```

## Process

Work proceeds in phases (0–4), each phase composed of named specialist
agents producing named files. **One module per response.** After each
module: log to `/00-decisions/BUILD-LOG.md` and report days elapsed against
the month-2 target. **Stop at every GATE and wait for operator sign-off**
before continuing.

Phase order: **0 Decide → 1 Define → 2 Build → 3 Verify → 4 Launch.**
Full phase/module/agent breakdown lives in the build instructions this
charter was created from; gate files in `/00-decisions/` are the
authoritative record of what was decided at each checkpoint.
