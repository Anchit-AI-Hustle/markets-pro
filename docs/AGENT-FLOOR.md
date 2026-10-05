# Capital-floor + multi-desk governance

Markets Pro already has the hard parts that a serious trading research system
needs: point-in-time data, lookahead protection, deterministic strategies,
position sizing, portfolio risk, realistic cost/slippage modelling, paper
trading, broker guards and a test gate.

The multi-agent trading-floor concept therefore sits **above** the existing
engine. It does not replace the engine and it does not give an LLM permission
to bypass risk controls.

## Architecture

```text
TREASURY / CAPITAL FLOOR           <- deterministic code
            |
            v
RESEARCH DESKS
  Analyst: company + market
  Quant: strategy + data
  News: headlines + macro
  Risk: trade + portfolio
  Red team: try to invalidate the idea
            |
            v
CONSENSUS KERNEL                   <- deterministic code
  missing input      -> WAIT
  degraded data      -> WAIT
  any veto           -> WAIT
  conflicting signal -> WAIT
            |
            v
INDEPENDENT DECISION + PLAN GATE
  research != TRADE  -> WAIT
  decider != TRADE   -> WAIT
  low confidence     -> WAIT
  invalid plan       -> WAIT
  entry/stop/target/size fixed before execution
            |
            v
EXISTING MARKETS PRO STACK
  strategy -> sizing -> RiskManager -> execution simulator / broker guard
            |
            v
POST-TRADE REVIEW
  original thesis vs decision vs execution vs outcome
            |
            v
AUDIT + PROFIT LOCK
            |
            +---------------------> protected capital
```

## What this adds

### CapitalFloorKernel

The trading sleeve may use only capital that is simultaneously:

1. outside the segregated protected value;
2. above the configured protected floor; and
3. inside a maximum fraction of current NAV.

Already-committed loss budget is deducted first. A proposed trade whose
credible maximum loss does not fit gets zero new risk.

Realised profit can be split into a locked share and a recyclable share. There
is intentionally no inverse operation in the kernel: protected capital is a
one-way destination.

This is structural capital separation, **not a guarantee that a bank, bond,
custodian, exchange or other asset holding the protected value cannot fail**.

### ConsensusKernel

AI/research desks may produce evidence, but the final permission rule is code.

The mandatory desks are:

- data
- risk
- liquidity
- portfolio
- execution
- red team

Every mandatory desk must report. FAIL or UNAVAILABLE means WAIT.
Any directional conflict also means WAIT.

The kernel approves only a proposed BUY or SELL; it does not invent a trade.

### Independent decision + strict trade plan

The carousel's useful "one system researches, another decides" pattern is kept
provider-agnostic. Markets Pro should not depend on a particular model vendor.

A candidate can proceed only when the research component and independent
decision component both return TRADE. The plan must already contain symbol,
side, entry, stop, target, quantity, thesis and confidence. The gate computes
planned loss and reward/risk before execution.

Low confidence is a reason to refuse a trade. High confidence is **not** a
reason to enlarge the risk budget: it cannot override the capital floor,
consensus veto, or RiskManager.

### Post-trade review

Every closed trade should produce a factual review that preserves the original
pre-trade thesis and plan, then compares them with actual entry, exit, size,
fees, slippage, net P&L, R-multiple and thesis outcome. This prevents hindsight
from rewriting what the system believed before the trade.

The review record is learning/audit input; it has no authority to retroactively
change fills or automatically loosen risk limits.

## Mapping the 10-agent concept onto Markets Pro

| Trading-floor role | Markets Pro responsibility |
|---|---|
| Company analyst | fundamentals + instrument research |
| Market analyst | screener + regime context |
| Strategy quant | strategy / research fitness |
| Data quant | livefeed + data-quality gate |
| News analyst | news feed / catalyst evidence |
| Macro analyst | future macro-context adapter |
| Trade risk | RiskManager + stop/target engine |
| Portfolio risk | exposure, concentration, heat |
| Trade executor | existing broker adapter / simulator |
| Order manager | broker relay, journal, idempotency |
| Red team | new required governance veto |

The existing strategy separation remains important: strategies generate
signals, sizing decides quantity, risk may refuse, and execution does not
re-litigate the thesis.

## Paper-first rule

This feature does **not** enable real-money automation.

BROKER_ORDERS_LIVE remains off by default. Any future agent integration must
first write auditable votes and run through paper/execution simulation. Only a
separate, explicit deployment decision may expose an approved order to the
existing broker layer.

## What is wired now

The live snapshot now carries a governance packet for every pending order. It
uses the strategy signal as research input and independently checks data
freshness/sanity, the existing risk state, portfolio rules, liquidity,
executability and an adversarial red-team rule. Missing or failed mandatory
checks produce WAIT.

For new risk, the strict plan gate requires entry, stop, target, size, thesis
and minimum confidence, then computes planned loss before the capital-floor
kernel can release risk capacity. Risk-reducing exits bypass entry-only thesis,
reward/risk and capital-floor gates; they remain subject to data/venue/execution
constraints so a safety system cannot accidentally prevent a close.

The browser paper book re-evaluates the capital floor using the reader's own
capital and already-open paper positions. Positive realised paper P&L is split
according to the configured profit-lock fraction, and every paper close records
the original thesis/plan beside the actual outcome and R-multiple.

Signal cards fail closed: an unapproved order exposes no paper or real execution
button. An approved SELL signal closes an existing paper holding rather than
opening the opposite direction.

## Boundary before real-money automation

The broker relay remains a separate server-side safety boundary and live orders
remain off by default. The dashboard will not expose an execution button for an
unapproved snapshot order, but browser state is not a security credential and
must never be treated as one.

Therefore **do not enable BROKER_ORDERS_LIVE for autonomous use** until a
server-side approval ticket can be recomputed or cryptographically verified
against the canonical decision packet. Paper trading is the governed execution
path in this implementation.

Before that live boundary is crossed:

1. Forward-test the full governed paper path and record approvals, vetoes,
   realised outcomes, slippage assumptions and drawdown.
2. Calibrate confidence thresholds from out-of-sample/paper evidence rather
   than treating model confidence as a probability of profit.
3. Add a server-generated, expiring approval token bound to user, symbol,
   direction, quantity and decision version before a broker BUY can be routed.
4. Keep exits risk-reducing and non-overridable by research agents.
