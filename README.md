# markets-pro / autotrader

A multi-region systematic trading research engine. It runs two independent
books — a long-term momentum portfolio and a short-term swing book — across
Indian, US, Chinese and Russian equity markets, with region-correct costs,
taxes, settlement rules and trading calendars.

Zero runtime dependencies. Pure standard library, Python 3.11+.

```bash
python verify.py                                   # run the accuracy gate
make demo                                          # multi-region backtest
make serve                                         # dashboard at /markets-pro
```

---

## What is claimed

**Every implemented behaviour is verified correct against hand-computed expected
values, at a 100% pass rate.** `python verify.py` runs the registered verification suite and exits
non-zero if a single check fails. Specifically:

| Area | What is verified |
|---|---|
| Money & FX | Exact `Decimal` arithmetic, currency-mismatch rejection, cross-rate derivation, tick/lot rounding |
| Indicators | SMA, EMA, Wilder RMA, RSI, ATR, ADX, MACD, Bollinger, Donchian, Supertrend, z-score, returns — each against values derived from its definition |
| Lookahead | No strategy ever observes a bar dated after its decision date, audited across a full run |
| Accounting | `equity == initial cash + realized + unrealized − costs`, exactly, at every point |
| Costs | India STT/stamp/GST split by delivery vs intraday, US SEC + FINRA sell-side fees with cap, China sell-side stamp duty and CNY 5 commission floor, MOEX both-sided fees |
| Venue rules | China T+1 blocks same-session round trips; board lots enforced; daily price limits reject fills |
| Sizing | Fixed-fractional risk, volatility targeting, target weight, capped Kelly, and the constraint ladder |
| Risk | Position/region/sector/leverage caps, drawdown and daily-loss kill-switches |
| Exits | Stops, targets, gaps, trailing stops, time limits, and pessimistic ambiguity resolution |
| Determinism | Identical inputs produce identical equity curves |
| Data quality | Live cache staleness checked against each market's own trading calendar; single-session outlier moves and zero-volume sessions flagged |
| Screener | Regime-appropriate indicator weighting (trend vs. mean-reversion), sector-relative momentum ranking |

## What is **not** claimed

**This does not guarantee a profit, and no amount of testing could establish
that it would.**

Markets are non-stationary. A strategy that was profitable across all available
history can lose money tomorrow, because the conditions that produced the edge
are not fixed. Any system advertising guaranteed returns is describing either
fraud or an undiscovered bug in its own backtest — most often lookahead bias,
which this engine is specifically built to prevent.

Concretely:

- The bundled demo runs on **synthetic** data and **loses money**. That is the
  correct outcome. Generated prices contain no exploitable structure, so after
  realistic costs and slippage a strategy should lose. A system that showed a
  profit there would be evidence of a defect, not of skill.
- The two shipped strategies are conventional, documented designs (trend +
  cross-sectional momentum; RSI pullback and Donchian breakout). They are
  reasonable starting points, not validated alphas. Both have historically had
  multi-year losing stretches.
- **Nothing here executes real trades.** There is no broker integration, no
  order routing, and no credential handling for a trading account. It is a
  research and paper-trading engine by design.
- Fee and tax rates are documented defaults that **will** drift. Verify them
  against current exchange schedules before relying on any result.

This is not investment advice.

---

## Design decisions that matter

A backtest is easy to write and easy to get wrong. The specific defenses here:

**Orders decided at the close of day D fill at the open of day D+1.** Filling at
day D's close — a very common shortcut — hands the strategy a price it could not
have traded, because the decision required that close to exist.

**Strategies cannot reach future data structurally, not by convention.** They
receive a `HistoryWindow` clipped to the decision date; every accessor is
bounded, and reaching past it raises `LookaheadError`. A lookahead bug fails a
test instead of quietly inflating returns.

**Ambiguous bars resolve against the trader.** When a daily bar's low pierces the
stop *and* its high reaches the target, there is no way to know which came
first. The stop always wins. Assuming otherwise is assuming intraday luck you
have no evidence for.

**Gapped stops fill at the open, not the stop.** If the stop is 95 and the
session opens at 90, the fill is 90. Filling at 95 is the single most common way
a backtest understates drawdown.

**Money is `Decimal`, never float.** `0.1 + 0.2 != 0.3` is not an acceptable
property for a ledger. Statistics run in float; the ledger does not.

**Cash is held per currency.** A rupee balance and a dollar balance are different
things. Conversion happens only at mark-to-market, at that day's rate.

**Trade P&L is summed in base currency.** Aggregating a rupee gain and a dollar
gain as raw numbers produces a total wrong by the exchange rate — a real bug
this engine had, caught by a reconciliation test that now asserts summed trade
P&L equals the change in equity.

**Rejected orders are recorded with a reason.** A strategy whose orders are all
being blocked by a concentration limit looks identical to one generating no
signals, unless rejections are visible.

---

## Capital-floor governance

A deterministic governance layer can sit above the existing strategy/risk stack.
It has two jobs: keep segregated protected capital outside the trading sleeve,
and fail closed when mandatory research/risk desks are missing, degraded, veto
a candidate, or disagree on direction. AI-generated confidence never overrides
either rule.

This layer does **not** turn trading into a zero-loss activity and does not enable
live broker execution. It makes the loss budget and decision permissions
explicit and testable. Research and the independent decision component must both
say TRADE; low confidence, disagreement, or an invalid entry/stop/target/size
returns WAIT. Every closed trade can then be reviewed against the immutable
pre-trade thesis and plan. See [docs/AGENT-FLOOR.md](docs/AGENT-FLOOR.md).

## Regional rules modelled

| | India | United States | China | Russia |
|---|---|---|---|---|
| Currency | INR | USD | CNY | RUB |
| Tick | 0.05 | 0.01 | 0.01 | 0.01 |
| Board lot | 1 | 1 | **100** | 1 |
| Same-session sell | yes | yes | **no (T+1)** | yes |
| Daily price band | ±20% | LULD halts | **±10%** | ±20% |
| Short selling | intraday | yes | no | no |
| Sell-side taxes | STT 0.1% delivery | SEC + FINRA TAF | stamp 0.05% | — |
| Buy-side taxes | stamp 0.015% | — | — | — |

China's T+1 rule is enforced end to end: shares bought today cannot be sold
today, and a stop triggered on the entry session simply waits for the next one.

---

## Layout

```
src/autotrader/
  core/          money & FX, instruments, market specs, trading calendars
  data/          bars, the lookahead-guarded history window, synthetic generators,
                 the live-cache fetcher/adapter and its freshness/sanity checks
  indicators/    technical indicators (full-length output, explicit None warmup)
  strategy/      base interface, long-term momentum, short-term swing
  screener/      cross-universe ranking: regime-selected indicators, sector-
                 relative momentum, independent of either trading book
  portfolio/     FIFO positions, multi-currency ledger, position sizing
  risk/          pre-trade limits, kill-switches, exit engine
  governance/    capital floor, independent decision, strict plan gate, review
  execution/     orders, regional cost models, slippage, fill simulator
  engine/        the backtest event loop and performance metrics
  persistence/   Postgres/Supabase row mapping and writer
  web/           dashboard rendering and the /markets-pro route
tests/           verification suite
verify.py        the accuracy gate
```

## Usage

```python
from datetime import date
from decimal import Decimal
from autotrader import (
    BacktestConfig, BacktestEngine, FXRates,
    LongTermStrategy, ShortTermStrategy,
)

engine = BacktestEngine(
    instruments=instruments,          # your Instrument list
    data=market_data,                 # MarketDataSet of BarSeries
    strategies=[LongTermStrategy(), ShortTermStrategy()],
    config=BacktestConfig(
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
        base_currency="USD",
        starting_cash={"USD": Decimal("1000000")},
    ),
    fx=FXRates("USD", {"INR": Decimal("83")}),
)
report = engine.run()
print(report.summary())
```

Point it at real history rather than the synthetic generators to get a result
worth interpreting.

## Dashboard

`make dashboard` writes a self-contained page to `out/markets-pro/index.html` —
no external scripts, styles, fonts or images, so it serves under a strict CSP
and renders offline. `make serve` hosts it at `http://localhost:8000/markets-pro`.

### The walkthrough

When the page has live signals it opens with a seven-step, self-playing
walkthrough of what actually happens between a market close and a decision you
have to make: your amount, the re-scan, the filter, the sizing, the trade with
its exit already attached, the paper-first action, and the track record
including the parts that do not flatter it.

It exists because a dashboard that opens on finished statistics answers a
question a first-time reader has not asked yet. Three constraints keep it from
being an advert:

- **Every figure is read from the run.** The names in the scan are the real
  watchlist, the funnel counts are today's counts, the chart is the live
  signal's own price history with its real stop and target, and the closing
  stats are the real ones — win rate, worst drawdown, longest losing streak and
  the period return, whichever way they point. The snapshot carries a
  `mechanics` block for exactly this, so retuning the engine cannot leave the
  explanation describing a system that no longer exists.
- **It plays once and stops.** The page's motion rule is that nothing loops on
  its own beside live numbers; the tour runs a single pass, rests on the last
  step, and folds itself away once you have saved an amount.
- **It never blocks the app.** The steps ship as ordinary visible content, so
  with no JavaScript they read as a list. Under `prefers-reduced-motion` that
  same static list is exactly what renders — no autoplay, no transitions, no
  controls for a thing that is not moving.

Autoplay waits for the section to be on screen, stops on a hidden tab, and
pauses the moment you steer it. Steps are a keyboard-navigable tablist
(`←`/`→`/`↑`/`↓`, `Home`, `End`).

The equity chart supports **pinch to zoom**:

| Gesture | Action |
|---|---|
| Two-finger pinch | Zoom the time axis in/out |
| Two-finger drag | Pan |
| One-finger drag | Pan (only once zoomed in) |
| ctrl/⌘ + scroll | Zoom (trackpad pinch emits this) |
| Double-tap / double-click | Zoom in, or reset if already zoomed |
| `+` `-` `0` `←` `→` | Zoom, reset, pan from the keyboard |

Zoom is **horizontal only** and is applied as a transform on the plot group, not
by rewriting the SVG `viewBox`. Both matter: shrinking the viewBox would change
the element's intrinsic aspect ratio and make a `height:auto` chart grow
absurdly tall as it zooms, and zooming vertically would leave the window on
blank space between the equity line and the drawdown band. Strokes use
`vector-effect="non-scaling-stroke"` so a 40× zoom does not draw a 40×-thick
line, and the x-axis re-dates to the visible window from the real session list
rather than interpolating across weekends.

Page-level browser zoom is left fully enabled — the viewport sets no scale lock,
and one finger still scrolls the page over the chart until it is zoomed in.

To deploy under an existing domain, publish `out/markets-pro/` at the
`/markets-pro` path of whatever already serves that domain.

## Database

`src/autotrader/persistence/schema.sql` creates six `mkt_`-prefixed tables. All
have row-level security **enabled with no permissive policy**, so only the
service role can read or write them. Position and P&L data is not made
world-readable just because a dashboard wants to render it; opt in explicitly if
you want browser-side reads.

Credentials come from `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in the
environment and are never written to disk or logged.

## Licence

MIT. See [LICENSE](LICENSE).

## Live signals & execution

The deployed dashboard ([anchit-tandon.com/markets-pro](https://anchit-tandon.com/markets-pro))
runs these same strategies over **real NSE + US end-of-day data** and leads with
the orders they would place at the next open — quantity, reference price, stop
and target attached. A GitHub Action refreshes the data after each market's
close; between closes the page overlays delayed quotes and flags any position
that trades through its stop or target.

Execution is tiered and capped — one-tap Kite basket handoff (you confirm in
your broker), an Alpaca relay that is paper-mode until armed, and an opt-in
capped Kite Connect auto-invest CLI. See [docs/AUTO-INVEST.md](docs/AUTO-INVEST.md)
for setup and the honest constraints. None of it guarantees a profit, and none
of it is investment advice.

## Screener

Independent of either trading book's own entry logic, `autotrader.screener`
ranks the *entire* loaded universe on the same cache the strategies read:

```bash
PYTHONPATH=src python3 -m autotrader.data.quality --data data/live   # freshness + sanity, exit 1 on hard failure
PYTHONPATH=src python3 -m autotrader.screener.core --data data/live --out data/live/screener.json
```

For each instrument it classifies the regime from ADX — **trending** (ADX ≥ 25)
weights Supertrend, MACD and a 50/200-day SMA cross; **ranging** weights RSI and
Bollinger %B instead, since trend-following tools whipsaw in a range and
mean-reversion oscillators overshoot in a real trend. That regime-appropriate
signal is then blended with the stock's momentum *relative to its own sector's
average* — a mediocre stock in a hot sector does not borrow the sector's score,
and a strong stock in a weak sector is not buried under sector-wide malaise.
`sector_performance()` aggregates the same run into a top-industries ranking.

The nightly `refresh-signals` workflow verifies cache freshness against each
market's own trading calendar, re-runs the screener, and commits its snapshot
alongside the price cache — the screener is never more than one trading day
stale, same as the signals it sits next to.
