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
EXISTING MARKETS PRO STACK
  strategy -> sizing -> RiskManager -> execution simulator / broker guard
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

## Next integration steps

1. Generate a signed/auditable desk-vote packet for every candidate.
2. Feed the current data-quality result into the mandatory data vote.
3. Feed portfolio heat, drawdown and concentration into the mandatory risk
   votes.
4. Calculate proposed maximum loss before quantity is released.
5. Run the capital-floor kernel before the existing RiskManager.
6. Persist every veto/approval so rejected trades are as visible as fills.
7. Backtest and then paper-trade the entire governance path before considering
   any live execution.
