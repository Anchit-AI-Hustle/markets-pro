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
values, at a 100% pass rate.** `python verify.py` runs 587 checks and exits
non-zero if a single one fails. Specifically:

| Area | What is verified |
|---|---|
| Money & FX | Exact `Decimal` arithmetic, currency-mismatch rejection, cross-rate derivation, tick/lot rounding |
| Indicators | SMA, EMA, Wilder RMA, RSI, ATR, ADX, MACD, Bollinger, Donchian, z-score, returns — each against values derived from its definition |
| Lookahead | No strategy ever observes a bar dated after its decision date, audited across a full run |
| Accounting | `equity == initial cash + realized + unrealized − costs`, exactly, at every point |
| Costs | India STT/stamp/GST split by delivery vs intraday, US SEC + FINRA sell-side fees with cap, China sell-side stamp duty and CNY 5 commission floor, MOEX both-sided fees |
| Venue rules | China T+1 blocks same-session round trips; board lots enforced; daily price limits reject fills |
| Sizing | Fixed-fractional risk, volatility targeting, target weight, capped Kelly, and the constraint ladder |
| Risk | Position/region/sector/leverage caps, drawdown and daily-loss kill-switches |
| Exits | Stops, targets, gaps, trailing stops, time limits, and pessimistic ambiguity resolution |
| Determinism | Identical inputs produce identical equity curves |

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
  data/          bars, the lookahead-guarded history window, synthetic generators
  indicators/    technical indicators (full-length output, explicit None warmup)
  strategy/      base interface, long-term momentum, short-term swing
  portfolio/     FIFO positions, multi-currency ledger, position sizing
  risk/          pre-trade limits, kill-switches, exit engine
  execution/     orders, regional cost models, slippage, fill simulator
  engine/        the backtest event loop and performance metrics
  persistence/   Postgres/Supabase row mapping and writer
  web/           dashboard rendering and the /markets-pro route
tests/           587 checks
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
