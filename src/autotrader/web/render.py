"""Render a :class:`PerformanceReport` to a self-contained HTML dashboard.

No external stylesheets, scripts, fonts or images — the output is one file that
renders identically offline, behind a CSP, or served from any static host. The
equity chart is inline SVG generated from the data, not a charting library.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from ..engine.metrics import PerformanceReport, drawdown_series

REGION_NAMES = {
    "IN": "India",
    "US": "United States",
    "CN": "China",
    "RU": "Russia",
    "HK": "Hong Kong",
}

EXIT_LABELS = {
    "stop_loss": "Stop loss",
    "gap_through_stop": "Gapped through stop",
    "take_profit": "Target",
    "gap_through_target": "Gapped through target",
    "trailing_stop": "Trailing stop",
    "time_exit": "Time limit",
    "signal_exit": "Signal exit",
    "rebalance": "Rebalance",
    "risk_halt": "Risk halt",
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float, places: int = 2) -> str:
    return f"{value * 100:.{places}f}%"


def _signed_pct(value: float, places: int = 2) -> str:
    return f"{value * 100:+.{places}f}%"


def _money(value: Decimal | float, currency: str = "") -> str:
    suffix = f" {currency}" if currency else ""
    return f"{float(value):,.2f}{suffix}"


def _tone(value: float) -> str:
    """CSS class for a number whose sign carries meaning."""
    if value > 0:
        return "pos"
    if value < 0:
        return "neg"
    return "flat"


def _fmt_ratio(value: float) -> str:
    if value == float("inf"):
        return "&infin;"
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# SVG chart
# ---------------------------------------------------------------------------

def equity_chart_svg(
    days: Sequence[date],
    equity: Sequence[Decimal],
    *,
    width: int = 1000,
    height: int = 320,
) -> str:
    """Equity curve with a drawdown band underneath, as inline SVG.

    Drawdown is drawn alongside the curve rather than in a separate collapsed
    panel, because the two numbers only mean something together.
    """
    if len(equity) < 2:
        return '<p class="empty">Not enough data to plot an equity curve.</p>'

    pad_l, pad_r, pad_t, pad_b = 64, 16, 16, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    dd_h = 72
    curve_h = plot_h - dd_h - 12

    values = [float(v) for v in equity]
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1.0
    span = hi - lo
    # Pad the range by 5% so the line never touches the frame.
    lo -= span * 0.05
    hi += span * 0.05
    span = hi - lo

    n = len(values)

    def x_at(i: int) -> float:
        return pad_l + (plot_w * i / (n - 1))

    def y_at(v: float) -> float:
        return pad_t + curve_h - ((v - lo) / span * curve_h)

    points = " ".join(f"{x_at(i):.2f},{y_at(v):.2f}" for i, v in enumerate(values))
    area = (
        f"{pad_l:.2f},{pad_t + curve_h:.2f} "
        + points
        + f" {pad_l + plot_w:.2f},{pad_t + curve_h:.2f}"
    )

    # Drawdown band.
    dd = drawdown_series(equity)
    max_dd = max(dd) if dd else 0.0
    dd_scale = max(max_dd, 0.01)
    dd_top = pad_t + curve_h + 12

    def dd_y(v: float) -> float:
        return dd_top + (v / dd_scale * dd_h)

    dd_points = " ".join(f"{x_at(i):.2f},{dd_y(v):.2f}" for i, v in enumerate(dd))
    dd_area = (
        f"{pad_l:.2f},{dd_top:.2f} " + dd_points + f" {pad_l + plot_w:.2f},{dd_top:.2f}"
    )

    # Y-axis gridlines for the equity panel.
    grid = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = lo + span * frac
        y = y_at(value)
        grid.append(
            f'<line class="grid" x1="{pad_l}" y1="{y:.2f}" '
            f'x2="{pad_l + plot_w}" y2="{y:.2f}"/>'
            f'<text class="axis" x="{pad_l - 8}" y="{y + 4:.2f}" '
            f'text-anchor="end">{value:,.0f}</text>'
        )

    # X-axis labels: first, middle, last. Anchored `middle` at the ends would
    # overflow the frame, so the outer two are pinned to their edges.
    anchors = ("start", "middle", "end")
    x_positions = (pad_l, pad_l + plot_w / 2, pad_l + plot_w)
    x_labels = []
    for slot, (i, anchor, xpos) in enumerate(
        zip((0, n // 2, n - 1), anchors, x_positions, strict=False)
    ):
        x_labels.append(
            f'<text class="axis" data-xlabel="{slot}" x="{xpos:.2f}" '
            f'y="{height - 8}" text-anchor="{anchor}">{days[i].isoformat()}</text>'
        )

    start_line_y = y_at(values[0])
    # Dates drive the x-axis relabelling on zoom. Interpolating between the
    # endpoints would be wrong — sessions skip weekends and holidays — so the
    # actual list travels with the chart.
    day_data = ",".join(d.isoformat() for d in days)

    return f"""<svg class="chart" viewBox="0 0 {width} {height}"
     preserveAspectRatio="xMidYMid meet" role="img"
     data-plot="{pad_l} {plot_w}" data-days="{day_data}"
     aria-label="Equity curve and drawdown">
  <defs>
    <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02"/>
    </linearGradient>
    <clipPath id="plotclip">
      <rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}"/>
    </clipPath>
  </defs>
  {''.join(grid)}
  <text class="axis label" x="{pad_l}" y="{dd_top - 2}">Drawdown</text>
  <text class="axis" x="{pad_l - 8}" y="{dd_y(dd_scale) + 4:.2f}"
        text-anchor="end">-{dd_scale * 100:.0f}%</text>
  <g clip-path="url(#plotclip)">
    <g data-plotgroup>
      <line class="baseline" x1="{pad_l}" y1="{start_line_y:.2f}"
            x2="{pad_l + plot_w}" y2="{start_line_y:.2f}"/>
      <polygon class="eqarea" points="{area}"/>
      <polyline class="eqline" vector-effect="non-scaling-stroke"
                points="{points}"/>
      <polygon class="ddarea" points="{dd_area}"/>
      <polyline class="ddline" vector-effect="non-scaling-stroke"
                points="{dd_points}"/>
    </g>
  </g>
  {''.join(x_labels)}
</svg>"""


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------

def _kpi(label: str, value: str, *, tone: str = "", note: str = "") -> str:
    note_html = f'<span class="kpi-note">{_esc(note)}</span>' if note else ""
    return (
        f'<div class="kpi"><span class="kpi-label">{_esc(label)}</span>'
        f'<span class="kpi-value {tone}">{value}</span>{note_html}</div>'
    )


def _kpi_grid(report: PerformanceReport) -> str:
    cards = [
        _kpi("Total return", _signed_pct(report.total_return),
             tone=_tone(report.total_return)),
        _kpi("CAGR", _signed_pct(report.cagr), tone=_tone(report.cagr),
             note=f"over {report.years:.2f} years"),
        _kpi("Max drawdown", f"-{_pct(report.max_drawdown)}", tone="neg",
             note=f"{report.max_drawdown_days} days underwater"),
        _kpi("Sharpe", f"{report.sharpe:.2f}", tone=_tone(report.sharpe),
             note=f"volatility {_pct(report.annual_volatility)}"),
        _kpi("Sortino", f"{report.sortino:.2f}", tone=_tone(report.sortino)),
        _kpi("Calmar", f"{report.calmar:.2f}", tone=_tone(report.calmar)),
        _kpi("Trades", f"{report.total_trades:,}",
             note=f"win rate {_pct(report.win_rate, 1)}"),
        _kpi("Profit factor", _fmt_ratio(report.profit_factor),
             tone=_tone(report.profit_factor - 1.0)),
        _kpi("Expectancy", f"{report.expectancy:+,.2f}",
             tone=_tone(report.expectancy), note="per trade"),
        _kpi("Worst streak", f"{report.max_consecutive_losses}",
             note="consecutive losses"),
        _kpi("Costs paid", _money(report.total_costs),
             note=f"{report.total_fills:,} fills"),
        _kpi("Rejections", f"{report.rejections:,}",
             note="orders blocked by risk or venue"),
    ]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def _region_table(report: PerformanceReport) -> str:
    if not report.by_region:
        return '<p class="empty">No completed trades to attribute.</p>'
    rows = []
    for region, stats in sorted(
        report.by_region.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True
    ):
        pnl = stats["net_pnl"]
        rows.append(
            f"<tr><td><span class='tag'>{_esc(region)}</span> "
            f"{_esc(REGION_NAMES.get(region, region))}</td>"
            f"<td class='num'>{int(stats['trades']):,}</td>"
            f"<td class='num'>{_pct(stats.get('win_rate', 0.0), 1)}</td>"
            f"<td class='num {_tone(pnl)}'>{pnl:+,.2f}</td></tr>"
        )
    return f"""<table>
  <thead><tr><th>Market</th><th class="num">Trades</th>
  <th class="num">Win rate</th><th class="num">Net P&amp;L</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _horizon_table(report: PerformanceReport) -> str:
    if not report.by_horizon:
        return '<p class="empty">No completed trades yet.</p>'
    labels = {"long_term": "Long-term book", "short_term": "Short-term book"}
    rows = []
    for horizon, stats in sorted(report.by_horizon.items()):
        pnl = stats["net_pnl"]
        rows.append(
            f"<tr><td>{_esc(labels.get(horizon, horizon))}</td>"
            f"<td class='num'>{int(stats['trades']):,}</td>"
            f"<td class='num'>{_pct(stats.get('win_rate', 0.0), 1)}</td>"
            f"<td class='num {_tone(pnl)}'>{pnl:+,.2f}</td></tr>"
        )
    return f"""<table>
  <thead><tr><th>Book</th><th class="num">Trades</th>
  <th class="num">Win rate</th><th class="num">Net P&amp;L</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _exit_breakdown(report: PerformanceReport) -> str:
    if not report.trades:
        return ""
    counts: dict[str, int] = {}
    for trade in report.trades:
        counts[trade.exit_reason or "unknown"] = counts.get(trade.exit_reason or "unknown", 0) + 1
    total = sum(counts.values())
    rows = []
    for reason, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        share = count / total
        rows.append(
            f"<tr><td>{_esc(EXIT_LABELS.get(reason, reason))}</td>"
            f"<td class='num'>{count:,}</td>"
            f"<td><div class='bar'><span style='width:{share * 100:.1f}%'></span></div></td>"
            f"<td class='num'>{_pct(share, 1)}</td></tr>"
        )
    return f"""<table>
  <thead><tr><th>Exit reason</th><th class="num">Count</th>
  <th>Share</th><th class="num">%</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>"""


def _trades_table(report: PerformanceReport, limit: int = 25) -> str:
    if not report.trades:
        return '<p class="empty">No completed round trips.</p>'
    recent = sorted(report.trades, key=lambda t: t.exit_day, reverse=True)[:limit]
    base = report.base_currency
    rows = []
    for t in recent:
        # Two P&L columns on purpose. The local figure is what actually changed
        # hands; the base figure is the only one comparable across rows. Showing
        # a rupee number and a dollar number in one column would invite adding
        # them up.
        local = (
            f"<td class='num muted'>{float(t.net_pnl):+,.2f} "
            f"<span class='ccy'>{_esc(t.currency)}</span></td>"
        )
        rows.append(
            f"<tr><td><span class='tag'>{_esc(t.region)}</span> {_esc(t.key)}</td>"
            f"<td>{_esc(t.entry_day)}</td><td>{_esc(t.exit_day)}</td>"
            f"<td class='num'>{float(t.entry_price):,.2f}</td>"
            f"<td class='num'>{float(t.exit_price):,.2f}</td>"
            f"<td class='num'>{float(t.quantity):,.0f}</td>"
            f"{local}"
            f"<td class='num {_tone(float(t.net_pnl_base))}'>"
            f"{float(t.net_pnl_base):+,.2f}</td>"
            f"<td>{_esc(EXIT_LABELS.get(t.exit_reason, t.exit_reason))}</td></tr>"
        )
    caption = (
        f"Showing {len(recent)} of {len(report.trades):,} round trips, most recent "
        f"first. Local P&L is in the instrument's own currency; only the {base} "
        f"column is comparable across markets."
    )
    return f"""<table>
  <thead><tr><th>Instrument</th><th>Entry</th><th>Exit</th>
  <th class="num">In</th><th class="num">Out</th><th class="num">Qty</th>
  <th class="num">Net P&amp;L (local)</th>
  <th class="num">Net P&amp;L ({_esc(base)})</th><th>Reason</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
<p class="caption">{_esc(caption)}</p>"""


# ---------------------------------------------------------------------------
# Today's signals (live snapshot sections)
# ---------------------------------------------------------------------------

def _price(value: object) -> str:
    return f"{float(str(value)):,.2f}"


def _measured(source: dict, key: str, count: int) -> object | None:
    """A value only when something was actually measured.

    Returns ``None`` — which every caller renders as an em dash — when the
    field is absent or nothing was counted, so an empty day never renders as
    a computed zero the reader could mistake for a real result.
    """
    return source.get(key) if count else None


def _pct_str(value: object, places: int = 1) -> str:
    """Format a snapshot percentage string (a ratio) for display."""
    return f"{float(str(value)) * 100:+.{places}f}%"


def _money_line(amount: object, currency: str, *, signed: bool = False) -> str:
    if amount is None:
        return "&mdash;"
    value = float(str(amount))
    sign = ""
    if value < 0:
        sign, value = "&minus;", abs(value)  # typographic minus, not a hyphen
    elif signed:
        sign = "+"
    return f'{sign}{value:,.0f} <span class="ccy">{_esc(currency)}</span>'


def _signal_card(index: int, order: dict, has_kite_key: bool) -> str:
    """One signal as a money-first card: invest, upside, downside, horizon."""
    side = order["side"]
    side_class = "side-buy" if side == "BUY" else "side-sell"
    ccy = order["currency"]
    stale = "" if order["fresh"] else " stale"
    region_code = "IN" if order["region"] == "india" else "US"
    region_label = REGION_NAMES.get(region_code, order["region"])
    history = order.get("history") or {}
    win_rate = history.get("win_rate")

    # Paper leads deliberately: the reversible, no-credential action is the one
    # that should be easiest to reach, and the real-money path sits behind it.
    paper = (
        f'<button type="button" class="exec big" data-paper-buy="{index}">Paper buy</button>'
    )
    if order["region"] == "india":
        disabled = "" if has_kite_key else (
            ' disabled title="Add your Kite Publisher api_key to'
            ' config/live.json to enable one-tap handoff"'
        )
        real = (
            f'<button type="button" class="exec ghost" data-exec="kite:{index}"{disabled}>'
            "Real &middot; Kite</button>"
        )
    else:
        real = (
            f'<button type="button" class="exec ghost" data-exec="us:{index}">'
            "Real &middot; Alpaca</button>"
        )
    action = paper + real
    status = f'<span class="execstatus" data-exec-status="{index}" aria-live="polite"></span>'

    hold = order.get("max_holding_days")
    typical = history.get("median_days_held")
    window = f"within {hold} trading days" if hold else "held until the exit signal"
    typical_note = f", typically closed in {typical}" if typical else ""
    rate_note = (
        f"{float(win_rate) * 100:.0f}% of {history.get('trades', 0)} past trades in this book "
        "finished profitable"
        if win_rate is not None
        else "no closed trades in this book yet — hit rate unknown"
    )
    reward_risk = order.get("reward_risk")
    rr_note = f"{float(str(reward_risk)):.1f}:1 reward-to-risk" if reward_risk else ""

    return f"""<article class="sigcard{stale}">
  <div class="sighead">
    <span class="tag {side_class}">{side}</span>
    <strong class="signame">{_esc(order['symbol'])}</strong>
    <span class="muted-inline">{_esc(order['name'])}</span>
    <span class="tag">{_esc(region_label)}</span>
    {'' if order['fresh'] else '<span class="tag">resting</span>'}
  </div>
  <div class="sigmoney">
    <div class="mcell">
      <span class="mlabel">You invest</span>
      <span class="mvalue">{_money_line(order.get('invested'), ccy)}</span>
      <span class="mnote">{_esc(order['quantity'])} shares @
        ~{_price(order['reference_price'])}</span>
    </div>
    <div class="mcell win">
      <span class="mlabel">If target hits</span>
      <span class="mvalue">{_money_line(order.get('profit_at_target'), ccy, signed=True)}</span>
      <span class="mnote">{_pct_str(order['profit_at_target_pct'])
        if order.get('profit_at_target_pct') else '&mdash;'} &middot; sell at
        {_price(order['take_profit']) if order.get('take_profit') else '&mdash;'}</span>
    </div>
    <div class="mcell lose">
      <span class="mlabel">If stop hits</span>
      <span class="mvalue">&minus;{_money_line(order.get('loss_at_stop'), ccy)}</span>
      <span class="mnote">{'-' + _pct_str(order['loss_at_stop_pct'], 1).lstrip('+')
        if order.get('loss_at_stop_pct') else '&mdash;'} &middot; exit at
        {_price(order['stop_loss']) if order.get('stop_loss') else '&mdash;'}</span>
    </div>
    <div class="mcell">
      <span class="mlabel">Live price</span>
      <span class="mvalue live-cell" data-quote="{_esc(order['yahoo'])}"
            data-ref="{_esc(order['reference_price'])}">&mdash;</span>
      <span class="mnote">delayed quote</span>
    </div>
    <div class="mcell act">{action}{status}</div>
  </div>
  <p class="sigwhy"><strong>Why:</strong> {_esc(order.get('reason') or '')} &middot;
  <strong>Time:</strong> {window}{typical_note} &middot;
  <strong>Odds:</strong> {rate_note}{' &middot; ' + rr_note if rr_note else ''}</p>
</article>"""


def _totals_bar(totals: dict, base: str) -> str:
    """Portfolio-level answer to "what does all of this add up to?"."""
    signals = totals.get("signals", {})
    positions = totals.get("positions", {})

    def cell(label: str, value: object, note: str, tone: str = "", sign: str = "") -> str:
        """``sign`` is explicit rather than derived from colour: a gain and a
        loss must be distinguishable without seeing the red and the green."""
        if value is None:
            # No trailing currency: "— USD" implies a USD amount was measured.
            shown = "&mdash;"
        else:
            number = float(str(value))
            prefix = sign
            if sign == "auto":
                prefix = "+" if number >= 0 else "&minus;"
                number = abs(number)
            shown = f'{prefix}{number:,.0f} <span class="ccy">{_esc(base)}</span>'
        return (
            f'<div class="tcell"><span class="mlabel">{label}</span>'
            f'<span class="mvalue {tone}">{shown}</span>'
            f'<span class="mnote">{note}</span></div>'
        )

    # With nothing to sum there is no outcome to state: "—" is the honest cell,
    # where "+0 / -0" would read as a computed result that happens to be zero.
    count = signals.get("count", 0)
    upside = _measured(signals, "profit_at_target_base", count)
    downside = _measured(signals, "loss_at_stop_base", count)
    open_pnl = _measured(totals, "open_unrealized_base", positions.get("count", 0))
    pnl_tone = "" if open_pnl is None else _tone(float(str(open_pnl)))
    return f"""<div class="totals">
  {cell("Total to invest today", signals.get("invested_base"),
        f"{count} fresh signal(s), converted to {_esc(base)}")}
  {cell("Total if every target hits", upside,
        _pct_str(signals["profit_at_target_pct"]) + " on the amount invested"
        if signals.get("profit_at_target_pct") else "nothing to invest today", "pos", "+")}
  {cell("Total if every stop hits", downside,
        "-" + _pct_str(signals["loss_at_stop_pct"]).lstrip("+") + " on the amount invested"
        if signals.get("loss_at_stop_pct") else "nothing at risk today", "neg", "&minus;")}
  {cell("Open positions", positions.get("invested_base"),
        f"{positions.get('count', 0)} held at current prices")}
  {cell("Open profit / loss", open_pnl, "unrealised, at last close", pnl_tone, "auto")}
</div>
<p class="caption">Both outcomes are what the strategy's own stop and target
define &mdash; not a forecast. Real trades also end early on a trailing stop or the
time limit, so actual results land between these two numbers more often than on them.
Nothing here is a guaranteed or expected return.</p>"""


def _signals_section(signals: dict) -> str:
    orders = signals.get("orders", [])
    as_of = " &middot; ".join(
        f"{REGION_NAMES.get('IN' if region == 'india' else 'US', region)} data through {_esc(day)}"
        for region, day in signals.get("as_of", {}).items()
    )
    caps = " &middot; ".join(
        f"daily cap {_price(amount)} {_esc(ccy)}"
        for ccy, amount in signals.get("daily_cap", {}).items()
    )
    meta = (
        f'<p class="sigmeta">{as_of} &middot; generated {_esc(signals.get("generated_at", ""))} '
        f"&middot; {caps}</p>"
    )

    if not orders:
        return meta + (
            '<p class="empty">No new orders today. The strategies are either fully '
            "positioned or waiting for a setup &mdash; no signal is itself a signal.</p>"
        )

    has_kite_key = bool(signals.get("kite_api_key"))
    india_fresh = sum(1 for o in orders if o["region"] == "india" and o["fresh"])
    basket_all = ""
    if india_fresh >= 2 and has_kite_key:
        basket_all = (
            '<p><button type="button" class="exec" data-exec="kite:all">'
            f"Send all {india_fresh} India orders to Kite as one basket</button></p>"
        )

    cards = "".join(_signal_card(i, order, has_kite_key) for i, order in enumerate(orders))
    caption = (
        "Orders the strategies would place at the next open, sized against the "
        "simulated book. Invest-now buttons hand the order to YOUR broker — Kite opens "
        "a pre-filled basket you must confirm; the US executor honours the daily cap "
        "and stays in paper mode until you arm it. Live prices are delayed. "
        "None of this is investment advice, and no outcome is guaranteed."
    )
    return f"""{meta}{basket_all}{cards}
<p class="caption">{caption}</p>"""


def _positions_section(signals: dict) -> str:
    positions = signals.get("positions", [])
    if not positions:
        return '<p class="empty">No open positions in the simulated book.</p>'

    rows = []
    for position in positions:
        stop = _price(position["stop"]) if position.get("stop") else "&mdash;"
        target = _price(position["take_profit"]) if position.get("take_profit") else "&mdash;"
        held = position.get("days_held")
        limit = position.get("max_holding_days")
        clock = f"{held}/{limit}d" if held is not None and limit else "&mdash;"
        book = "Short-term" if position["horizon"] == "short_term" else "Long-term"
        region_code = "IN" if position["region"] == "india" else "US"
        region_label = REGION_NAMES.get(region_code, position["region"])
        pnl = position.get("unrealized")
        pnl_tone = ""
        if pnl is not None:
            pnl_tone = "pos" if float(str(pnl)) >= 0 else "neg"
        pnl_pct = (
            _pct_str(position["unrealized_pct"]) if position.get("unrealized_pct") else ""
        )
        upside = position.get("profit_at_target")
        downside = position.get("loss_at_stop")
        rows.append(
            f"""<tr>
  <td><span class="tag">{_esc(region_label)}</span>
      <strong>{_esc(position['symbol'])}</strong>
      <span class="muted-inline">{_esc(position['name'])}</span></td>
  <td>{book}</td>
  <td class="num">{_esc(position['quantity'])}</td>
  <td class="num">{_price(position['average_cost'])}
      <span class="ccy">{_esc(position['currency'])}</span></td>
  <td class="num live-cell" data-quote="{_esc(position['yahoo'])}"
      data-ref="{_esc(position['last_price'])}"
      data-qty="{_esc(position['quantity'])}"
      data-cost="{_esc(position['average_cost'])}"
      data-stop="{_esc(position.get('stop') or '')}"
      data-target="{_esc(position.get('take_profit') or '')}">{_price(position['last_price'])}</td>
  <td class="num {pnl_tone}" data-pnl="{_esc(position['yahoo'])}">{
      _money_line(pnl, position['currency'], signed=True)}
      <span class="mnote">{pnl_pct}</span></td>
  <td class="num pos">{_money_line(upside, position['currency'], signed=True)
      if upside else '&mdash;'}<span class="mnote">at {target}</span></td>
  <td class="num neg">{'&minus;' + _money_line(downside, position['currency'])
      if downside else '&mdash;'}<span class="mnote">at {stop}</span></td>
  <td class="num">{clock}</td>
  <td><span class="badge" data-badge="{_esc(position['yahoo'])}">&mdash;</span></td>
</tr>"""
        )
    caption = (
        "Profit/loss updates with the delayed quote (~15 min for NSE) during market "
        "hours, and a position is flagged the moment it trades through its stop or "
        "target — so you can act before the nightly rebuild. The two right-hand "
        "columns are what is still on the table from here, not from your entry. "
        "Long-term holdings carry no stop by design."
    )
    return f"""<table>
  <thead><tr><th>Instrument</th><th>Book</th><th class="num">Qty</th>
  <th class="num">Avg cost</th><th class="num">Live price</th>
  <th class="num">Profit / loss now</th>
  <th class="num">If target hits</th><th class="num">If stop hits</th>
  <th class="num">Held</th><th>Status</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
<p class="caption">{caption}</p>"""


def _glance(signals: dict) -> str:
    """The dashboard's at-a-glance strip: state of the book, one tap to act."""
    orders = signals.get("orders", [])
    fresh = sum(1 for order in orders if order["fresh"])
    totals = signals.get("totals", {})
    signal_totals = totals.get("signals", {})
    counted = signal_totals.get("count", 0)
    upside = _measured(signal_totals, "profit_at_target_base", counted)
    downside = _measured(signal_totals, "loss_at_stop_base", counted)
    open_pnl = _measured(
        totals, "open_unrealized_base", totals.get("positions", {}).get("count", 0)
    )
    pnl_value = float(str(open_pnl)) if open_pnl is not None else None
    cards = [
        _kpi("Fresh signals", str(fresh), tone="pos" if fresh else "flat",
             note="orders ready for the next open"),
        _kpi("To invest today", _price(signal_totals.get("invested_base", "0")),
             note="USD across both markets"),
        _kpi("If every target hits",
             "&mdash;" if upside is None else "+" + _price(upside),
             tone="pos" if upside is not None else "flat",
             note=_pct_str(signal_totals["profit_at_target_pct"])
             if signal_totals.get("profit_at_target_pct") else "no signals today"),
        _kpi("If every stop hits",
             "&mdash;" if downside is None else "&minus;" + _price(downside),
             tone="neg" if downside is not None else "flat",
             note="the most these signals risk" if downside is not None
             else "nothing at risk today"),
        _kpi("Open positions P&L",  # _kpi escapes the label; pass it raw
             "&mdash;" if pnl_value is None
             else ("+" if pnl_value >= 0 else "&minus;") + f"{abs(pnl_value):,.2f}",
             tone="flat" if pnl_value is None else _tone(pnl_value),
             note="unrealised, USD"),
    ]
    cta = (
        '<div class="kpi cta"><button type="button" class="exec big" data-tabgo="invest">'
        "Invest now &rarr;</button></div>"
    )
    return f'<div class="glance">{"".join(cards)}{cta}</div>'


def _setup_section(signals: dict) -> str:
    """The Setup tab: what each execution tier is, and whether it is armed."""
    kite_on = bool(signals.get("kite_api_key"))
    caps = signals.get("daily_cap", {})
    cap_line = (
        " &middot; ".join(f"{_price(value)} {_esc(ccy)}" for ccy, value in sorted(caps.items()))
        or "not configured"
    )
    kite_state = (
        '<span class="state on">enabled</span>'
        if kite_on
        else '<span class="state off">needs api_key</span>'
    )
    return f"""<div class="tiers">
  <div class="tier">
    <h3>Paper trading <span class="state on">ready now</span></h3>
    <p>Press <strong>Paper buy</strong> on any signal &mdash; no account, no keys.
    The trade is stored in this browser only and appears in the <strong>Paper</strong>
    tab with live profit/loss and stop/target flags. The daily cap applies here too,
    so you learn where it bites before real money is involved. Fills are assumed at
    the price shown, which is kinder than a real market order.</p>
  </div>
  <div class="tier">
    <h3>One-tap Kite basket {kite_state}</h3>
    <p>Each fresh India signal opens pre-filled in Zerodha; you review and confirm inside
    your own broker login. Free. Enable it by putting a Kite Publisher <code>api_key</code>
    into <code>config/live.json</code> and redeploying.</p>
  </div>
  <div class="tier">
    <h3>US executor via Alpaca <span class="state off">armed in Vercel env</span></h3>
    <p>The Alpaca button relays through <code>/markets-pro/api/execute</code>, which refuses
    every order until <code>ALPACA_KEY_ID</code> and <code>ALPACA_SECRET_KEY</code> are set,
    trades paper unless <code>ALPACA_LIVE=true</code>, and enforces
    <code>DAILY_CAP_USD</code> against the broker's own order log &mdash; never against
    what the page claims.</p>
  </div>
  <div class="tier">
    <h3>Capped auto-invest CLI <span class="state off">opt-in</span></h3>
    <p>Places today's fresh India BUY signals within the daily cap &mdash; dry-run by
    default, journalled so re-runs cannot double-spend. Needs Zerodha's paid Kite Connect
    API and a fresh login token each morning, by their design.</p>
  </div>
</div>
<p class="caption">Daily caps: {cap_line}. A cap bounds the worst day &mdash; nothing here
guarantees the best one. Signals are systematic research output, not investment advice,
and past performance does not predict future returns.</p>"""


SIGNALS_CSS = """
.sigmeta{color:var(--muted);font-size:12.5px;margin:0 0 12px}
.muted-inline{color:var(--muted);font-size:12px}
.side-buy{background:color-mix(in srgb,var(--pos) 18%,var(--tag));color:var(--pos)}
.side-sell{background:color-mix(in srgb,var(--neg) 18%,var(--tag));color:var(--neg)}
tr.stale{opacity:.55}
button.exec{appearance:none;border:1px solid var(--line);background:var(--panel);
  color:var(--accent);font:inherit;font-size:12.5px;font-weight:600;line-height:1;
  padding:6px 10px;border-radius:6px;cursor:pointer}
button.exec:hover:not(:disabled){background:var(--tag)}
button.exec:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
button.exec:disabled{opacity:.45;cursor:not-allowed}
button.exec.armed{background:var(--accent);color:var(--panel);border-color:var(--accent)}
.execstatus{display:block;font-size:11px;color:var(--muted);margin-top:4px;max-width:120px}
.badge{display:inline-block;border-radius:4px;padding:1px 7px;font-size:11px;font-weight:600;
  background:var(--tag);color:var(--muted)}
.badge.ok{color:var(--pos)}
.badge.hit{background:color-mix(in srgb,var(--neg) 20%,var(--tag));color:var(--neg)}
.badge.target{background:color-mix(in srgb,var(--pos) 20%,var(--tag));color:var(--pos)}
.live-cell{color:var(--muted)}
.live-cell.fresh{color:var(--ink)}

.tabs{position:sticky;top:0;z-index:20;display:flex;gap:2px;margin:18px -4px 6px;
  padding:6px 4px;background:var(--bg);border-bottom:1px solid var(--line);
  overflow-x:auto;-webkit-overflow-scrolling:touch}
.tabs button{appearance:none;border:0;background:transparent;color:var(--muted);
  font:inherit;font-size:14px;font-weight:600;padding:9px 14px;border-radius:8px;
  cursor:pointer;white-space:nowrap;display:flex;align-items:center;gap:7px}
.tabs button:hover{background:var(--tag);color:var(--ink)}
.tabs button.active{color:var(--accent);background:var(--tag)}
.tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.tabbadge{display:inline-block;min-width:18px;text-align:center;background:var(--accent);
  color:var(--panel);border-radius:999px;font-size:11px;font-weight:700;padding:1px 6px}
.tabpanel[hidden]{display:none}

.glance{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));
  margin:18px 0 4px}
.glance .cta{display:flex;align-items:stretch;justify-content:stretch;padding:0}
button.exec.big{font-size:14.5px;padding:12px 18px;width:100%;border-radius:var(--radius)}

.sigcard{border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;
  margin-bottom:12px;background:var(--bg)}
.sigcard.stale{opacity:.6}
.sighead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.signame{font-size:17px;letter-spacing:-0.01em}
.sigmoney{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  align-items:stretch}
.mcell{display:flex;flex-direction:column;gap:3px;padding:10px 12px;
  background:var(--panel);border:1px solid var(--line);border-radius:8px}
.mcell.win .mvalue{color:var(--pos)}
.mcell.lose .mvalue{color:var(--neg)}
.mcell.act{justify-content:center;background:transparent;border:0;padding:0}
.mlabel{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.mvalue{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;
  letter-spacing:-0.01em}
.mnote{display:block;font-size:11px;color:var(--muted);font-weight:400}
.sigwhy{margin:12px 0 0;font-size:12.5px;color:var(--muted);line-height:1.6}
.sigwhy strong{color:var(--ink);font-weight:600}

.totals{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  margin:14px 0 4px}
.tcell{display:flex;flex-direction:column;gap:3px;padding:12px 14px;
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}

button.exec.ghost{font-size:12px;font-weight:600;padding:7px 10px;color:var(--muted);
  margin-top:6px;width:100%}
button.exec.ghost:hover:not(:disabled){color:var(--accent)}
button.exec.danger{color:var(--neg);border-color:var(--line)}
button.exec.danger:hover{background:color-mix(in srgb,var(--neg) 12%,var(--tag))}
.mcell.act{flex-direction:column;gap:0}
.papersub{font-size:13px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin:26px 0 10px;font-weight:600}
.papertop .caption{margin-top:12px}

.tiers{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  margin-top:14px}
.tier{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:14px 16px}
.tier h3{margin:0 0 8px;font-size:14px;display:flex;align-items:center;gap:8px;
  flex-wrap:wrap}
.tier p{margin:0;font-size:13px;color:var(--muted);line-height:1.55}
.tier code{background:var(--tag);padding:1px 5px;border-radius:4px;font-size:11.5px}
.state{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.state.on{color:var(--pos)} .state.off{color:var(--muted)}
"""

#: Tab switching with hash routing. `hidden` drives visibility, aria-selected
#: drives assistive tech, and location.hash makes every tab linkable — so
#: "#invest" can be bookmarked or sent as a link straight to the action.
TABS_JS = """
(function () {
  var buttons = document.querySelectorAll('[data-tabbtn]');
  if (!buttons.length) return;
  var panels = document.querySelectorAll('[data-tab]');
  var names = [];
  Array.prototype.forEach.call(buttons, function (b) {
    names.push(b.getAttribute('data-tabbtn'));
  });

  function show(name) {
    if (names.indexOf(name) < 0) name = names[0];
    Array.prototype.forEach.call(panels, function (panel) {
      panel.hidden = panel.getAttribute('data-tab') !== name;
    });
    Array.prototype.forEach.call(buttons, function (b) {
      var active = b.getAttribute('data-tabbtn') === name;
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.classList.toggle('active', active);
    });
  }

  function go(name, fromClick) {
    if (fromClick && history.replaceState) {
      history.replaceState(null, '', '#' + name);
    }
    show(name);
  }

  Array.prototype.forEach.call(buttons, function (b) {
    b.addEventListener('click', function () {
      go(b.getAttribute('data-tabbtn'), true);
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-tabgo]'), function (el) {
    el.addEventListener('click', function () {
      go(el.getAttribute('data-tabgo'), true);
      window.scrollTo(0, 0);
    });
  });
  window.addEventListener('hashchange', function () {
    show(location.hash.replace('#', ''));
  });
  show(location.hash.replace('#', ''));
})();
"""

def _paper_section() -> str:
    """Shell for the paper portfolio; JS fills it from browser storage.

    Rendered empty on purpose — the paper book is per-viewer state that lives
    in ``localStorage``, so it cannot be baked into a static page shared by
    everyone. The build stays deterministic; the portfolio stays private to
    the browser that traded it.
    """
    return """<div class="papertop">
  <div class="totals" data-paper-summary></div>
  <p class="caption">Paper trades are simulated, stored only in this browser, and
  never sent to a broker &mdash; the whole point is to see how the signals behave
  before any money is involved. Fills are assumed at the price shown when you
  press the button, which is kinder than reality: a real market order can slip,
  and a real stop can gap straight through. Treat paper results as the optimistic
  edge of what live trading would do.</p>
</div>
<h3 class="papersub">Holdings</h3>
<div data-paper-positions></div>
<h3 class="papersub">Trade log</h3>
<div data-paper-log></div>
<p><button type="button" class="exec danger" data-paper-reset>Reset paper portfolio</button></p>"""


#: The paper broker: a full simulated portfolio in browser storage.
#:
#: No account, no keys, no server. Buying deducts cash and opens a position;
#: selling realises the P&L; the same delayed-quote feed that drives the live
#: overlay marks the book to market. The daily cap is enforced here too, so
#: the cap logic itself gets exercised before it ever guards real money.
PAPER_JS = """
(function () {
  var blob = document.getElementById('signals-data');
  if (!blob) return;
  var cfg;
  try { cfg = JSON.parse(blob.textContent); } catch (e) { return; }

  var KEY = 'markets-pro.paper.v1';
  var summaryEl = document.querySelector('[data-paper-summary]');
  if (!summaryEl) return;

  function fresh() {
    var cash = {};
    Object.keys(cfg.starting_cash || {}).forEach(function (c) {
      cash[c] = Number(cfg.starting_cash[c]);
    });
    return { v: 1, cash: cash, positions: {}, log: [] };
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return fresh();
      var state = JSON.parse(raw);
      if (!state || state.v !== 1 || !state.cash) return fresh();
      return state;
    } catch (e) { return fresh(); }
  }

  function save(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* full or blocked */ }
  }

  function money(n) {
    return Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
    });
  }
  function today() { return new Date().toISOString().slice(0, 10); }

  // Cap check runs against this browser's own paper log for today, mirroring
  // how the live executors check the broker's order log.
  function spentToday(state, currency) {
    var day = today(), total = 0;
    state.log.forEach(function (row) {
      if (row.action === 'buy' && row.currency === currency && row.ts.slice(0, 10) === day) {
        total += row.qty * row.price;
      }
    });
    return total;
  }

  function buy(order) {
    var state = load();
    var ccy = order.currency;
    var price = Number(livePrice(order.yahoo) || order.reference_price);
    var qty = Number(order.quantity);
    var cost = price * qty;
    var cap = Number((cfg.daily_cap || {})[ccy] || 0);

    if (cap > 0 && spentToday(state, ccy) + cost > cap) {
      return {ok: false, message: 'daily cap ' + money(cap) + ' ' + ccy + ' would be exceeded'};
    }
    if ((state.cash[ccy] || 0) < cost) {
      return {ok: false, message: 'not enough paper cash in ' + ccy};
    }

    state.cash[ccy] -= cost;
    var held = state.positions[order.key];
    if (held) {
      var total = held.qty + qty;
      held.cost = (held.cost * held.qty + cost) / total;
      held.qty = total;
    } else {
      state.positions[order.key] = {
        key: order.key, symbol: order.symbol, name: order.name, yahoo: order.yahoo,
        region: order.region, currency: ccy, qty: qty, cost: price,
        stop: order.stop_loss, target: order.take_profit, opened: today()
      };
    }
    state.log.push({ts: new Date().toISOString(), action: 'buy', key: order.key,
                    symbol: order.symbol, qty: qty, price: price, currency: ccy});
    save(state);
    render();
    return {ok: true, message: 'paper bought ' + qty + ' ' + order.symbol};
  }

  function sell(key) {
    var state = load();
    var pos = state.positions[key];
    if (!pos) return;
    var price = Number(livePrice(pos.yahoo) || pos.cost);
    state.cash[pos.currency] = (state.cash[pos.currency] || 0) + price * pos.qty;
    state.log.push({ts: new Date().toISOString(), action: 'sell', key: key, symbol: pos.symbol,
                    qty: pos.qty, price: price, currency: pos.currency,
                    pnl: (price - pos.cost) * pos.qty});
    delete state.positions[key];
    save(state);
    render();
  }

  function livePrice(yahoo) {
    var q = window.__mpQuotes && window.__mpQuotes[yahoo];
    return q ? q.price : null;
  }

  function render() {
    var state = load();
    var keys = Object.keys(state.positions);
    var usdinr = Number(cfg.usdinr) || 0;

    function toUsd(amount, ccy) {
      if (ccy === 'USD') return amount;
      return usdinr ? amount / usdinr : 0;
    }

    var invested = 0, marketValue = 0, openPnl = 0, cashUsd = 0;
    Object.keys(state.cash).forEach(function (c) { cashUsd += toUsd(state.cash[c], c); });
    keys.forEach(function (k) {
      var p = state.positions[k];
      var price = Number(livePrice(p.yahoo) || p.cost);
      invested += toUsd(p.cost * p.qty, p.currency);
      marketValue += toUsd(price * p.qty, p.currency);
      openPnl += toUsd((price - p.cost) * p.qty, p.currency);
    });
    var realised = 0;
    state.log.forEach(function (row) {
      if (row.action === 'sell') realised += toUsd(row.pnl || 0, row.currency);
    });

    function tcell(label, value, note, tone, signed) {
      var shown;
      if (value === null) { shown = '&mdash;'; }
      else {
        var pre = signed ? (value >= 0 ? '+' : '\\u2212') : '';
        shown = pre + money(signed ? Math.abs(value) : value) + ' <span class="ccy">USD</span>';
      }
      return '<div class="tcell"><span class="mlabel">' + label + '</span>' +
             '<span class="mvalue ' + (tone || '') + '">' + shown + '</span>' +
             '<span class="mnote">' + note + '</span></div>';
    }
    function tone(n) { return n > 0 ? 'pos' : (n < 0 ? 'neg' : 'flat'); }

    summaryEl.innerHTML =
      tcell('Paper account value', cashUsd + marketValue, 'cash plus holdings', '') +
      tcell('Cash available', cashUsd, Object.keys(state.cash).map(function (c) {
        return money(state.cash[c]) + ' ' + c; }).join(' &middot; '), '') +
      tcell('Holdings at market', marketValue, keys.length + ' position(s)', '') +
      tcell('Open profit / loss', openPnl, 'unrealised', tone(openPnl), true) +
      tcell('Realised profit / loss', realised, 'from closed paper trades', tone(realised), true);

    var posEl = document.querySelector('[data-paper-positions]');
    if (!keys.length) {
      posEl.innerHTML = '<p class="empty">No paper positions yet. Press ' +
        '<strong>Paper buy</strong> on a signal to open one.</p>';
    } else {
      var rows = keys.map(function (k) {
        var p = state.positions[k];
        var price = livePrice(p.yahoo);
        var mark = Number(price || p.cost);
        var pnl = (mark - p.cost) * p.qty;
        var pct = p.cost ? (mark - p.cost) / p.cost * 100 : 0;
        var flag = 'holding', cls = 'badge ok';
        if (p.stop && mark <= Number(p.stop)) {
          flag = 'STOP HIT'; cls = 'badge hit';
        } else if (p.target && mark >= Number(p.target)) {
          flag = 'TARGET HIT'; cls = 'badge target';
        }
        return '<tr><td><strong>' + esc(p.symbol) + '</strong> ' +
          '<span class="muted-inline">' + esc(p.name) + '</span></td>' +
          '<td class="num">' + p.qty + '</td>' +
          '<td class="num">' + money(p.cost) +
            ' <span class="ccy">' + esc(p.currency) + '</span></td>' +
          '<td class="num live-cell" data-quote="' + esc(p.yahoo) + '">' +
            (price ? money(price) : money(p.cost)) + '</td>' +
          '<td class="num ' + tone(pnl) + '">' + (pnl >= 0 ? '+' : '\\u2212') +
            money(Math.abs(pnl)) +
            ' <span class="mnote">' + (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%</span></td>' +
          '<td><span class="' + cls + '">' + flag + '</span></td>' +
          '<td class="num"><button type="button" class="exec" data-paper-sell="' + esc(k) +
            '">Sell</button></td></tr>';
      }).join('');
      posEl.innerHTML = '<table><thead><tr><th>Instrument</th><th class="num">Qty</th>' +
        '<th class="num">Paper cost</th><th class="num">Live price</th>' +
        '<th class="num">Profit / loss</th><th>Status</th><th class="num">Close</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table>';
    }

    var logEl = document.querySelector('[data-paper-log]');
    if (!state.log.length) {
      logEl.innerHTML = '<p class="empty">No paper trades recorded yet.</p>';
    } else {
      var entries = state.log.slice().reverse().map(function (row) {
        var pnl = row.action === 'sell'
          ? '<span class="' + tone(row.pnl) + '">' + (row.pnl >= 0 ? '+' : '\\u2212') +
            money(Math.abs(row.pnl)) + '</span>'
          : '&mdash;';
        return '<tr><td>' + esc(row.ts.replace('T', ' ').slice(0, 16)) + '</td>' +
          '<td><span class="tag ' + (row.action === 'buy' ? 'side-buy' : 'side-sell') + '">' +
            row.action.toUpperCase() + '</span></td>' +
          '<td><strong>' + esc(row.symbol) + '</strong></td>' +
          '<td class="num">' + row.qty + '</td>' +
          '<td class="num">' + money(row.price) + ' <span class="ccy">' +
            esc(row.currency) + '</span></td>' +
          '<td class="num">' + pnl + '</td></tr>';
      }).join('');
      logEl.innerHTML = '<table><thead><tr><th>When</th><th>Action</th><th>Instrument</th>' +
        '<th class="num">Qty</th><th class="num">Price</th><th class="num">Realised</th>' +
        '</tr></thead><tbody>' + entries + '</tbody></table>';
    }

    var badge = document.querySelector('[data-paper-badge]');
    if (badge) {
      badge.textContent = keys.length ? String(keys.length) : '';
      badge.style.display = keys.length ? '' : 'none';
    }
  }

  document.addEventListener('click', function (event) {
    var buyBtn = event.target.closest('[data-paper-buy]');
    if (buyBtn) {
      var order = (cfg.orders || [])[Number(buyBtn.getAttribute('data-paper-buy'))];
      if (!order) return;
      var result = buy(order);
      var status = buyBtn.parentNode.querySelector('.execstatus');
      if (status) status.textContent = result.message;
      return;
    }
    var sellBtn = event.target.closest('[data-paper-sell]');
    if (sellBtn) { sell(sellBtn.getAttribute('data-paper-sell')); return; }
    var reset = event.target.closest('[data-paper-reset]');
    if (reset) {
      if (window.confirm('Clear the paper portfolio and start over?')) {
        try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
        render();
      }
    }
  });

  window.__mpPaperRender = render;
  render();
})();
"""


#: Broker handoff + delayed-quote overlay for the signals sections.
#:
#: Execution is deliberately two-step everywhere: the first tap arms the button
#: ("Confirm?"), the second fires. Kite orders leave as a pre-filled basket the
#: user must still confirm inside their own broker login; US orders go to the
#: capped serverless executor, which is paper-mode unless the owner armed it.
#: This script never holds credentials and never fires on page load.
SIGNALS_JS = """
(function () {
  var blob = document.getElementById('signals-data');
  if (!blob) return;
  var cfg;
  try { cfg = JSON.parse(blob.textContent); } catch (e) { return; }
  var API = cfg.api_base || '/markets-pro/api';

  function kiteBasket(orders) {
    if (!cfg.kite_api_key || !orders.length) return;
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = 'https://kite.zerodha.com/connect/basket';
    form.target = '_blank';
    var key = document.createElement('input');
    key.type = 'hidden'; key.name = 'api_key'; key.value = cfg.kite_api_key;
    var data = document.createElement('input');
    data.type = 'hidden'; data.name = 'data'; data.value = JSON.stringify(orders);
    form.appendChild(key); form.appendChild(data);
    document.body.appendChild(form);
    form.submit();
    form.remove();
  }

  function usExecute(order, statusEl) {
    if (statusEl) statusEl.textContent = 'sending…';
    fetch(API + '/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ orders: [order.alpaca], notional: order.notional })
    }).then(function (res) {
      return res.json().then(function (body) { return { ok: res.ok, body: body }; });
    }).then(function (res) {
      if (statusEl) statusEl.textContent = res.body.message || (res.ok ? 'sent' : 'refused');
    }).catch(function () {
      if (statusEl) statusEl.textContent = 'executor unreachable';
    });
  }

  var armed = null, armedTimer = null;
  function disarm() {
    if (!armed) return;
    armed.textContent = armed.getAttribute('data-label');
    armed.classList.remove('armed');
    armed = null;
    clearTimeout(armedTimer);
  }

  Array.prototype.forEach.call(document.querySelectorAll('button[data-exec]'), function (btn) {
    btn.setAttribute('data-label', btn.textContent);
    btn.addEventListener('click', function () {
      if (armed !== btn) {
        disarm();
        armed = btn;
        btn.textContent = 'Confirm?';
        btn.classList.add('armed');
        armedTimer = setTimeout(disarm, 6000);
        return;
      }
      var target = btn.getAttribute('data-exec');
      disarm();
      if (target === 'kite:all') {
        var basket = [];
        (cfg.orders || []).forEach(function (order) {
          if (order.region === 'india' && order.fresh && order.kite) basket.push(order.kite);
        });
        kiteBasket(basket);
        return;
      }
      var parts = target.split(':');
      var order = (cfg.orders || [])[Number(parts[1])];
      if (!order) return;
      if (parts[0] === 'kite' && order.kite) kiteBasket([order.kite]);
      if (parts[0] === 'us' && order.alpaca) {
        usExecute(order, document.querySelector('[data-exec-status="' + parts[1] + '"]'));
      }
    });
  });

  // --- delayed quote overlay -------------------------------------------
  // Cells are queried at poll time, not once at startup: the paper portfolio
  // renders its rows after load, and they must pick up quotes as well.
  if (typeof fetch !== 'function') return;
  function quoteCells() { return document.querySelectorAll('[data-quote]'); }
  function symbolList() {
    var out = [];
    Array.prototype.forEach.call(quoteCells(), function (cell) {
      var s = cell.getAttribute('data-quote');
      if (s && out.indexOf(s) < 0) out.push(s);
    });
    return out;
  }
  if (!symbolList().length) return;

  function fmt(value) {
    var opts = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
    return Number(value).toLocaleString('en-US', opts);
  }

  function applyQuotes(quotes) {
    // Shared so the paper book can mark its holdings to the same prices.
    window.__mpQuotes = quotes;
    Array.prototype.forEach.call(quoteCells(), function (cell) {
      var quote = quotes[cell.getAttribute('data-quote')];
      if (!quote || !quote.price) return;
      var price = Number(quote.price);
      var text = fmt(price);
      var ref = Number(cell.getAttribute('data-ref'));
      if (ref) {
        var drift = (price - ref) / ref * 100;
        text += ' (' + (drift >= 0 ? '+' : '') + drift.toFixed(1) + '%)';
      }
      cell.textContent = text;
      cell.classList.add('fresh');

      // Recompute this position's profit/loss from the live price.
      var qty = Number(cell.getAttribute('data-qty'));
      var cost = Number(cell.getAttribute('data-cost'));
      var pnlCell = document.querySelector('[data-pnl="' + cell.getAttribute('data-quote') + '"]');
      if (pnlCell && qty && cost) {
        var pnl = (price - cost) * qty;
        var pct = (price - cost) / cost * 100;
        pnlCell.textContent = (pnl >= 0 ? '+' : '\\u2212') + fmt(Math.abs(pnl))
          + ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%)';
        pnlCell.classList.remove('pos', 'neg');
        pnlCell.classList.add(pnl >= 0 ? 'pos' : 'neg');
      }

      var badge = document.querySelector('[data-badge="' + cell.getAttribute('data-quote') + '"]');
      if (badge) {
        var stop = Number(cell.getAttribute('data-stop')) || null;
        var target = Number(cell.getAttribute('data-target')) || null;
        if (stop && price <= stop) {
          badge.textContent = 'STOP HIT'; badge.className = 'badge hit';
        } else if (target && price >= target) {
          badge.textContent = 'TARGET HIT'; badge.className = 'badge target';
        } else {
          badge.textContent = 'holding'; badge.className = 'badge ok';
        }
      }
    });
  }

  var timer = null;
  function poll() {
    if (document.hidden) return;
    fetch(API + '/quotes?symbols=' + encodeURIComponent(symbolList().join(',')))
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (body) {
        if (!body || !body.quotes) return;
        applyQuotes(body.quotes);
        // Re-render the paper book so its marks and stop flags use these prices.
        if (window.__mpPaperRender) { window.__mpPaperRender(); applyQuotes(body.quotes); }
      })
      .catch(function () { /* offline or proxy down: last close already shown */ });
  }
  poll();
  timer = setInterval(poll, 60000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });
  window.addEventListener('pagehide', function () { clearInterval(timer); });
})();
"""


#: Pinch/wheel/drag zoom for the equity chart.
#:
#: Zoom is applied as a horizontal transform on the plot *group*, not by
#: rewriting the SVG viewBox. Shrinking the viewBox would change the element's
#: intrinsic aspect ratio, so a chart with `height:auto` grows absurdly tall as
#: you zoom in. Transforming the content leaves the frame, the axes and the
#: y-scale exactly where they are.
#:
#: **Zoom is horizontal only.** On a time series the useful axis is time.
#: Zooming vertically as well quickly leaves the window on blank space between
#: the equity line and the drawdown band, and separates two panels that are only
#: meaningful read together.
#:
#: `vector-effect="non-scaling-stroke"` keeps line widths constant, so a 40x
#: zoom does not render a 40x-thick equity line.
#:
#: The gesture split is deliberate: one finger scrolls the page while the chart
#: is fitted (`touch-action: pan-y`) and only pans once zoomed in, so the chart
#: never traps page scrolling on a phone.
ZOOM_JS = """
(function () {
  var MIN = 1, MAX = 40;
  document.querySelectorAll('[data-zoom]').forEach(function (wrap) {
    var svg = wrap.querySelector('svg[data-plot]');
    var group = svg && svg.querySelector('[data-plotgroup]');
    if (!svg || !group) return;

    var plot = svg.getAttribute('data-plot').split(/\\s+/).map(Number);
    var padL = plot[0], plotW = plot[1];
    var viewW = svg.viewBox.baseVal.width || 1000;
    var days = (svg.getAttribute('data-days') || '').split(',').filter(Boolean);
    var labels = svg.querySelectorAll('[data-xlabel]');
    var level = wrap.querySelector('[data-zoom-level]');

    var s = 1;    // zoom factor
    var u0 = 0;   // left edge of the visible window, as a fraction of the data

    function apply() {
      s = Math.min(MAX, Math.max(MIN, s));
      u0 = Math.min(1 - 1 / s, Math.max(0, u0));
      // Map data fraction u0 to the left edge of the plot area.
      var tx = padL - s * (padL + u0 * plotW);
      group.setAttribute('transform',
        'translate(' + tx.toFixed(4) + ' 0) scale(' + s.toFixed(6) + ' 1)');
      if (level) level.textContent = s.toFixed(1) + '\\u00d7';
      wrap.classList.toggle('zoomed', s > 1.01);
      relabel();
    }

    // Re-date the x axis to the visible window. Sessions skip weekends and
    // holidays, so the real date list is indexed rather than interpolated.
    function relabel() {
      if (!days.length || labels.length !== 3) return;
      var last = days.length - 1;
      [0, 0.5, 1].forEach(function (frac, i) {
        var idx = Math.round((u0 + frac / s) * last);
        labels[i].textContent = days[Math.min(last, Math.max(0, idx))];
      });
    }

    // Screen x -> fraction across the plot area, clamped to it.
    function screenToU(clientX) {
      var r = svg.getBoundingClientRect();
      if (!r.width) return 0;
      var svgX = ((clientX - r.left) / r.width) * viewW;
      return Math.min(1, Math.max(0, (svgX - padL) / plotW));
    }

    // Zoom about a focal point: the date under the fingers/cursor stays put.
    function zoomAt(factor, clientX) {
      var uScreen = screenToU(clientX);
      var uData = u0 + uScreen / s;
      s = Math.min(MAX, Math.max(MIN, s * factor));
      u0 = uData - uScreen / s;
      apply();
    }

    function panBy(dxClient) {
      var r = svg.getBoundingClientRect();
      if (!r.width) return;
      var dxSvg = (dxClient / r.width) * viewW;
      u0 -= (dxSvg / plotW) / s;
      apply();
    }

    function reset() { s = 1; u0 = 0; apply(); }

    var pointers = new Map();
    var lastDist = 0, lastMidX = null;

    function pts() { return Array.from(pointers.values()); }
    function midX() { var p = pts(); return (p[0].x + p[1].x) / 2; }
    function dist() {
      var p = pts();
      return Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
    }

    wrap.addEventListener('pointerdown', function (e) {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) { lastDist = dist(); lastMidX = midX(); }
      else if (pointers.size === 1 && s > 1.01) wrap.classList.add('dragging');
      if (pointers.size === 2 || s > 1.01) wrap.setPointerCapture(e.pointerId);
    });

    wrap.addEventListener('pointermove', function (e) {
      if (!pointers.has(e.pointerId)) return;
      var prev = pointers.get(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (pointers.size === 2) {
        e.preventDefault();
        var d = dist(), m = midX();
        if (lastDist > 0) zoomAt(d / lastDist, m);
        if (lastMidX !== null) panBy(m - lastMidX);   // two-finger drag pans too
        lastDist = d; lastMidX = m;
      } else if (pointers.size === 1 && s > 1.01) {
        e.preventDefault();
        panBy(e.clientX - prev.x);
      }
    });

    function release(e) {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) { lastDist = 0; lastMidX = null; }
      if (pointers.size === 0) wrap.classList.remove('dragging');
    }
    wrap.addEventListener('pointerup', release);
    wrap.addEventListener('pointercancel', release);
    wrap.addEventListener('pointerleave', release);

    // Plain wheel is left to the page; ctrl/meta + wheel is the standard zoom
    // gesture and is also what a trackpad pinch emits.
    wrap.addEventListener('wheel', function (e) {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX);
    }, { passive: false });

    wrap.addEventListener('dblclick', function (e) {
      e.preventDefault();
      if (s > 1.01) reset(); else zoomAt(2.5, e.clientX);
    });

    function centreX() {
      var r = svg.getBoundingClientRect();
      return r.left + r.width / 2;
    }
    var zin = wrap.querySelector('[data-zoom-in]');
    var zout = wrap.querySelector('[data-zoom-out]');
    var zres = wrap.querySelector('[data-zoom-reset]');
    if (zin) zin.addEventListener('click', function () { zoomAt(1.6, centreX()); });
    if (zout) zout.addEventListener('click', function () { zoomAt(1 / 1.6, centreX()); });
    if (zres) zres.addEventListener('click', reset);

    wrap.setAttribute('tabindex', '0');
    wrap.addEventListener('keydown', function (e) {
      if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(1.6, centreX()); }
      else if (e.key === '-') { e.preventDefault(); zoomAt(1 / 1.6, centreX()); }
      else if (e.key === '0' || e.key === 'Escape') { e.preventDefault(); reset(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); panBy(40); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); panBy(-40); }
    });

    apply();
  });
})();
"""

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#fbfbfa; --panel:#ffffff; --ink:#1a1a18; --muted:#6b6b66;
  --line:#e6e5e1; --accent:#2f6f4e; --pos:#1f7a4d; --neg:#b4402f;
  --tag:#f0efeb; --radius:10px;
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#141413;--panel:#1c1c1a;--ink:#eceae4;--muted:#9a978f;
        --line:#2c2c29;--accent:#5aa87c;--pos:#5aa87c;--neg:#d97a63;--tag:#262623}
}
:root[data-theme="dark"]{--bg:#141413;--panel:#1c1c1a;--ink:#eceae4;--muted:#9a978f;
  --line:#2c2c29;--accent:#5aa87c;--pos:#5aa87c;--neg:#d97a63;--tag:#262623}
:root[data-theme="light"]{--bg:#fbfbfa;--panel:#ffffff;--ink:#1a1a18;--muted:#6b6b66;
  --line:#e6e5e1;--accent:#2f6f4e;--pos:#1f7a4d;--neg:#b4402f;--tag:#f0efeb}

body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 64px}
header{margin-bottom:24px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-0.02em}
.sub{color:var(--muted);font-size:14px;margin:0}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--muted);margin:34px 0 12px;font-weight:600}

.notice{border:1px solid var(--line);border-left:3px solid var(--accent);
  background:var(--panel);border-radius:var(--radius);padding:14px 16px;margin:20px 0}
.notice p{margin:0;font-size:13.5px;color:var(--muted)}
.notice strong{color:var(--ink)}

.kpi-grid{display:grid;gap:10px;
  grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
.kpi{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.kpi-label{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.kpi-value{font-size:21px;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-0.01em}
.kpi-note{font-size:11.5px;color:var(--muted)}
.pos{color:var(--pos)} .neg{color:var(--neg)} .flat{color:var(--muted)}
td.muted{color:var(--muted)}
.ccy{font-size:10.5px;opacity:.7;letter-spacing:.03em}

.panel{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:16px;overflow-x:auto}

/* `pan-y` rather than `none`: one finger still scrolls the page vertically over
   the chart, while two-finger pinch is delivered to us as pointer events. */
.zoomwrap{position:relative;touch-action:pan-y;overscroll-behavior:contain}
.zoomwrap.zoomed{touch-action:none;cursor:grab}
.zoomwrap.dragging{cursor:grabbing}
.zoomctl{position:absolute;top:6px;right:6px;display:flex;align-items:center;
  gap:4px;background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:3px}
.zoomctl button{appearance:none;border:0;background:transparent;color:var(--ink);
  font:inherit;font-size:13px;line-height:1;min-width:26px;height:24px;
  padding:0 7px;border-radius:5px;cursor:pointer}
.zoomctl button:hover{background:var(--tag)}
.zoomctl button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.zoomlevel{font-size:11px;color:var(--muted);min-width:34px;text-align:right;
  padding-right:4px;font-variant-numeric:tabular-nums}
@media (hover:none){.zoomctl{top:4px;right:4px}
  .zoomctl button{min-width:32px;height:30px}}

.chart{width:100%;height:auto;display:block}
.grid{stroke:var(--line);stroke-width:1}
.baseline{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 4;opacity:.6}
.eqline{fill:none;stroke:var(--accent);stroke-width:2;
  stroke-linejoin:round;stroke-linecap:round}
.eqarea{fill:url(#eqfill);stroke:none}
.ddline{fill:none;stroke:var(--neg);stroke-width:1.2;opacity:.85}
.ddarea{fill:var(--neg);opacity:.14;stroke:none}
.axis{fill:var(--muted);font-size:10.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.axis.label{font-size:10px;text-transform:uppercase;letter-spacing:.06em}

table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}
.tag{display:inline-block;background:var(--tag);border-radius:4px;
  padding:1px 6px;font-size:11px;font-weight:600;margin-right:6px}
.bar{background:var(--tag);border-radius:3px;height:8px;width:100%;min-width:80px}
.bar span{display:block;height:100%;background:var(--accent);border-radius:3px}
.caption,.empty{color:var(--muted);font-size:12.5px;margin:10px 0 0}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12.5px}
footer code{background:var(--tag);padding:1px 5px;border-radius:4px;font-size:11.5px}
.verified{color:var(--pos);font-weight:600}
@media (max-width:640px){
  .wrap{padding:20px 14px 48px} h1{font-size:21px}
  .kpi-value{font-size:18px}
}
"""


def render_dashboard(
    report: PerformanceReport,
    *,
    title: str = "Markets Pro",
    subtitle: str = "",
    tests_passed: int = 0,
    tests_total: int = 0,
    signals: dict | None = None,
) -> str:
    """Return a complete, self-contained HTML document for ``report``.

    When ``signals`` (a snapshot from :mod:`autotrader.signals.live`) is given,
    the page leads with today's orders and open-position triggers, embeds the
    snapshot as JSON for the broker-handoff buttons, and polls the same-origin
    quote proxy for a delayed intraday overlay. Without it the page is the
    pure offline research dashboard, unchanged.
    """
    period = f"{report.start_day} to {report.end_day}"
    sub = subtitle or (
        f"{period} &middot; base currency {report.base_currency} &middot; "
        f"{len(report.equity_days):,} sessions"
    )
    verified = ""
    if tests_total:
        rate = tests_passed / tests_total * 100
        verified = (
            f'<span class="verified">{tests_passed}/{tests_total} logic checks '
            f"passed ({rate:.2f}%)</span> &middot; "
        )

    signal_blob = ""
    signal_script = ""
    glance = ""
    invest_panel = ""
    invest_tab = ""
    if signals is not None:
        fresh_count = sum(1 for order in signals.get("orders", []) if order["fresh"])
        badge = f'<span class="tabbadge">{fresh_count}</span>' if fresh_count else ""
        invest_tab = (
            f'<button type="button" role="tab" data-tabbtn="invest" aria-selected="false" '
            f'aria-controls="panel-invest">Invest Now{badge}</button>'
            '<button type="button" role="tab" data-tabbtn="paper" aria-selected="false" '
            'aria-controls="panel-paper">Paper<span class="tabbadge" data-paper-badge '
            'style="display:none"></span></button>'
        )
        glance = _glance(signals)
        invest_panel = f"""
  <section class="tabpanel" id="panel-invest" data-tab="invest" role="tabpanel" hidden>
    <h2>What today's signals add up to</h2>
    <div class="panel">{_totals_bar(signals.get("totals", {}), report.base_currency)}</div>

    <h2>Today's signals</h2>
    <div class="panel">{_signals_section(signals)}</div>

    <h2>Open positions &amp; live triggers</h2>
    <div class="panel">{_positions_section(signals)}</div>
  </section>

  <section class="tabpanel" id="panel-paper" data-tab="paper" role="tabpanel" hidden>
    <h2>Paper portfolio</h2>
    <div class="panel">{_paper_section()}</div>
  </section>
"""
        embedded = {
            "api_base": "/markets-pro/api",
            "kite_api_key": signals.get("kite_api_key", ""),
            "daily_cap": signals.get("daily_cap", {}),
            "starting_cash": signals.get("starting_cash", {}),
            "usdinr": signals.get("usdinr", ""),
            "orders": signals.get("orders", []),
        }
        # <-escape so no substring can terminate the script element early.
        blob = json.dumps(embedded).replace("<", "\\u003c")
        signal_blob = f'<script type="application/json" id="signals-data">{blob}</script>'
        # Paper first: it defines window.__mpPaperRender before the quote
        # overlay starts polling, so the first poll can already mark the book.
        signal_script = f"<script>{PAPER_JS}</script>\n<script>{SIGNALS_JS}</script>"

    tab_bar = f"""<nav class="tabs" role="tablist" aria-label="Sections">
    <button type="button" role="tab" data-tabbtn="dashboard" aria-selected="true"
            aria-controls="panel-dashboard" class="active">Dashboard</button>
    {invest_tab}
    <button type="button" role="tab" data-tabbtn="performance" aria-selected="false"
            aria-controls="panel-performance">Performance</button>
    <button type="button" role="tab" data-tabbtn="setup" aria-selected="false"
            aria-controls="panel-setup">Setup</button>
  </nav>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- Viewport intentionally omits any scale lock, so browser-native pinch zoom of
     the whole page stays available. That is an accessibility requirement; the
     chart's own pinch handler is additive, not a replacement. -->
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{_esc(title)}</title>
<style>{CSS}{SIGNALS_CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <p class="sub">{sub}</p>
  </header>

  {tab_bar}

  <section class="tabpanel" id="panel-dashboard" data-tab="dashboard" role="tabpanel">
    <div class="notice">
      <p><strong>Simulated results.</strong> These figures come from a backtest, not
      from live trading. Costs, taxes, slippage and venue rules are modelled, and
      the engine is verified free of lookahead &mdash; but past performance on
      historical data does not predict future returns, and no strategy here
      guarantees a profit. Nothing on this page is investment advice.</p>
    </div>
    {glance}
    <h2>Performance</h2>
    {_kpi_grid(report)}

    <h2>Equity &amp; drawdown</h2>
    <div class="panel">
      <div class="zoomwrap" data-zoom>
        {equity_chart_svg(report.equity_days, report.equity_values)}
        <div class="zoomctl" role="group" aria-label="Chart zoom">
          <button type="button" data-zoom-out aria-label="Zoom out">&minus;</button>
          <button type="button" data-zoom-reset aria-label="Reset zoom">Reset</button>
          <button type="button" data-zoom-in aria-label="Zoom in">+</button>
          <span class="zoomlevel" data-zoom-level aria-live="polite">1.0&times;</span>
        </div>
      </div>
      <p class="caption">Pinch to zoom, drag to pan. On a trackpad or mouse use
      ctrl/&#8984; + scroll. Double-tap or press Reset to fit.</p>
    </div>
  </section>
{invest_panel}
  <section class="tabpanel" id="panel-performance" data-tab="performance" role="tabpanel" hidden>
    <h2>By market</h2>
    <div class="panel">{_region_table(report)}</div>

    <h2>By book</h2>
    <div class="panel">{_horizon_table(report)}</div>

    <h2>How trades ended</h2>
    <div class="panel">{_exit_breakdown(report)}</div>

    <h2>Recent round trips</h2>
    <div class="panel">{_trades_table(report)}</div>
  </section>

  <section class="tabpanel" id="panel-setup" data-tab="setup" role="tabpanel" hidden>
    <h2>Execution setup</h2>
    {_setup_section(signals or {})}
  </section>

  <footer>
    {verified}generated by <code>autotrader</code> &middot;
    equity {_money(report.starting_equity)} &rarr;
    {_money(report.ending_equity, report.base_currency)}
  </footer>
</div>
{signal_blob}
<script>{TABS_JS}</script>
<script>{ZOOM_JS}</script>
{signal_script}
</body>
</html>"""
