# Signals, execution, and the daily cap

The dashboard at `anchit-tandon.com/markets-pro` shows, every trading day, the
orders the verified strategies would place at the next open — what to buy or
sell, how much, at what reference price, with the stop and target attached.
This document is about the step after that: getting those orders to a broker.

**Read this first:** nothing here guarantees a profit. The dashboard shows the
strategies' real backtested record on real data — including losing years —
precisely so you never mistake a systematic signal for a sure thing. Signals
are research output, not investment advice. Every execution path below either
ends with you confirming inside your own broker, or is capped and off by
default.

---

## Tier 0 — Paper trading — free, no account, start here

Every signal has a **Paper buy** button. It needs no broker, no API key and no
signup: the trade is recorded in your browser's own storage, and the **Paper**
tab tracks holdings, cash, live profit/loss, stop and target flags, and a full
trade log. Sell any holding, or reset the book, at any time.

The daily cap applies to paper exactly as it does to real money, so you find
out that (say) a $250/day cap refuses a $1,566 Apple order *here*, not after
wiring a broker.

Two honest limits on paper results:

- **Fills are optimistic.** Paper assumes you get the price shown at the moment
  you press the button. Real market orders slip, and a real stop can gap
  straight through its level, filling well below it.
- **It lives in one browser.** Clearing site data clears the paper book. It is a
  learning tool, not a record you should rely on.

When you want broker-side realism — real fills, real rejections, real
settlement — move to Alpaca paper in Tier 2, which is still free and still not
real money.

## Tier 1 — One-tap handoff to Zerodha (India) — free

Each fresh India signal has a **Kite** button; with two or more, a basket
button sends them all at once. Tapping opens Kite with the order(s) pre-filled;
you review and confirm inside Zerodha. Nothing is placed until you do.

Setup (once):

1. Create a (free) **Kite Publisher** app at developers.kite.trade.
2. Put its `api_key` into `config/live.json` → `"kite_api_key"`.
3. Commit; the next deploy enables the buttons.

## Tier 2 — Capped US auto-executor (Alpaca) — free, off by default

The **Alpaca** button posts the order to `/markets-pro/api/broker/link` — the
same authenticated relay every other broker uses — which:

- **requires you to be signed in.** The request carries your Supabase access
  token and the relay exchanges it for your user id. There is no unauthenticated
  route to a broker; an earlier build had one, and anyone who could reach the URL
  could have traded the account;
- refuses everything until you add `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY`
  to the Vercel project's environment variables **and** set
  `BROKER_ORDERS_LIVE=true`;
- trades **paper by default**; real money additionally requires
  `ALPACA_LIVE=true`;
- **reserves against `DAILY_CAP_USD` before contacting the broker.** The intent
  is written to the order journal first, so a second request already counts it.
  Checking a total and only then writing to it leaves a window where two
  requests both pass and together breach the cap;
- **refuses a sell of stock you do not hold**, because that is a short position
  and a short has unbounded loss;
- carries a **`client_order_id`**, so a retried request — a double-tap, a flaky
  network, a re-invoked function — is refused by Alpaca rather than becoming a
  second position.

## Tier 3 — Capped India auto-invest (Kite Connect) — paid, opt-in

Fully automated NSE order placement needs **Kite Connect**, whose Personal
tier is free for exactly this (orders, holdings, positions; market data is
the part that costs), and
Zerodha requires a fresh login token every morning by design, so "automated"
means: log in once each trading morning, then run:

```bash
PYTHONPATH=src python3 -m autotrader.broker.kite --data data/live
```

That is a **dry run** — it prints the plan and the cap math. To execute:

```bash
KITE_API_KEY=... KITE_ACCESS_TOKEN=... \
PYTHONPATH=src python3 -m autotrader.broker.kite --data data/live --live
```

- Only **fresh BUY signals from today's snapshot** are eligible.
- `daily_cap.INR` from `config/live.json` is enforced, and every accepted
  order is journalled to `data/executions/` so re-running cannot double-spend.
- SEBI's algo-trading framework applies to API-driven retail orders; check
  Zerodha's approval requirements before going live.

## The daily cap

`config/live.json`:

```json
{
  "starting_cash": {"INR": "500000", "USD": "10000"},
  "daily_cap": {"INR": "20000", "USD": "250"},
  "kite_api_key": ""
}
```

`starting_cash` is what the simulated book manages (signal sizes scale with
it); `daily_cap` is the most any executor may deploy per day. The cap bounds
your worst day — it does not, and cannot, "ensure" your best one.

## How freshness works

A GitHub Action fetches end-of-day bars after the NSE close (18:45 IST) and
after the US close, commits the cache, and the push redeploys the site — so
signals recompute every trading day without a server. In between, the page
polls delayed quotes (~15 min for NSE) and flags any open position that trades
through its stop or target.

---

## Where the data comes from

Every number on the site is traceable to a source, and each source was chosen
for being free and legitimate rather than merely available.

| Data | Source | Key needed |
|---|---|---|
| Daily prices, India + US | Yahoo Finance chart API | no |
| Indices, commodities, FX | Yahoo Finance chart API | no |
| Dividends and splits | Yahoo Finance chart events | no |
| Headlines | Yahoo Finance RSS | no |
| US fundamentals | **SEC EDGAR** company facts (XBRL from 10-K filings) | no |
| Indian mutual fund NAVs | **AMFI** `NAVAll.txt` | no |
| Non-US fundamentals | Alpha Vantage free tier | **yes — free** |

### Filling in Indian fundamentals

This is the one gap, and it is an access problem rather than an engineering
one. Every keyless route was tested and rejected:

- **NSE and BSE company APIs** return `403` to automated clients, including
  the cookie-seeded flow their own website uses.
- **Yahoo's `quoteSummary`** is crumb-gated, and the crumb endpoint
  rate-limits datacenter addresses — which is exactly what a CI runner is.
- **Commercial aggregators** expose the figures only through their frontend's
  private payloads: undocumented, liable to change without notice, and
  against the terms of the sites publishing them.

What is left is a keyed provider on a free tier — but **coverage differs
between providers and is not visible from the outside**, so check before
relying on one:

```bash
ALPHAVANTAGE_KEY=... TWELVEDATA_KEY=... \
PYTHONPATH=src python3 -m autotrader.data.fundamentals_intl --probe
```

That asks each configured provider for one Indian company and reports what
came back, in a single call.

**Alpha Vantage does not carry Indian fundamentals.** Tested against a live
key: `OVERVIEW` returns a full record for `IBM` and an empty object for
`RELIANCE.BSE`. It indexes Indian symbols for search, which makes it look
supported when it is not. It is still worth configuring — it supplies beta,
analyst target price, dividend yield and PEG for US names, none of which
EDGAR publishes.

**Twelve Data's fundamentals are paid-only.** Its keyless catalogue lists
Reliance on NSE with full metadata, so the instrument is genuinely in its
universe — but `/statistics` answers `403: available exclusively with pro or
ultra or venture or enterprise plans`. The free tier gives quotes and time
series, which this app already gets from Yahoo, so a free key adds nothing
here.

**Conclusion: no free tier was found that carries Indian fundamentals.** Both
candidates were tested with live keys rather than trusted on their coverage
pages. This is a purchasing decision, not an engineering one. The pages say
"not available" and will keep saying it until a paid feed is configured.

<details><summary>Original note on Twelve Data's catalogue</summary>

**Twelve Data lists NSE instruments** in its keyless catalogue endpoint, so
Reliance is in its universe with full metadata. Whether its statistics
endpoint sits on the free plan can only be settled with a key — which is what
`--probe` is for. Free key: <https://twelvedata.com/pricing>.

</details>

Set either key as `ALPHAVANTAGE_KEY` / `TWELVEDATA_KEY`, in the repository
secrets **or** in the Vercel project's environment variables — the build
honours both, rate-guarded to one pass a day. Until a provider that covers
India is configured, the pages say "not available", which is the honest
state.

Provider figures are labelled as such on the page. They are that provider's
computed ratios, not values read from a filing, and the attribution says so.
