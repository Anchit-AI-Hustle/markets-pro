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

def _kpi(label: str, value: str, *, tone: str = "", note: str = "", cell: str = "") -> str:
    note_html = f'<span class="kpi-note">{_esc(note)}</span>' if note else ""
    hook = f' data-cell="{_esc(cell)}"' if cell else ""
    note_hook = f' data-cell="{_esc(cell)}-note"' if cell else ""
    if note_html and cell:
        note_html = f'<span class="kpi-note"{note_hook}>{_esc(note)}</span>'
    # Only figures with no `cell` hook are static; a hooked cell is rewritten by
    # script and must not be animated (see COUNTER_JS).
    if not cell:
        hook = " data-count"
    return (
        f'<div class="kpi"><span class="kpi-label">{_esc(label)}</span>'
        f'<span class="kpi-value {tone}"{hook}>{value}</span>{note_html}</div>'
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


#: Defined once per document and referenced by every sparkline: repeating the
#: gradient inside each SVG would duplicate the id across the page.
SPARK_DEFS = """<svg width="0" height="0" aria-hidden="true"
     style="position:absolute"><defs>
  <linearGradient id="sparkfill" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="currentColor" stop-opacity="0.28"/>
    <stop offset="100%" stop-color="currentColor" stop-opacity="0"/>
  </linearGradient>
</defs></svg>"""


def sparkline_svg(
    values: Sequence[float],
    *,
    stop: object = None,
    target: object = None,
    width: int = 240,
    height: int = 56,
) -> str:
    """Recent price as inline SVG, with the trade's own levels drawn in.

    A sparkline that is only a squiggle is decoration. Plotting the stop and
    the target on the same scale turns it into the one picture that answers
    "how far is this from going wrong, and how far from paying off" — which is
    the question the numbers beside it are already trying to answer.

    The y-range spans the price history *and* both levels, so the gaps you see
    are the real ones rather than an artefact of clipping.
    """
    points = [float(v) for v in values if v is not None]
    if len(points) < 2:
        return ""

    levels = [float(str(v)) for v in (stop, target) if v not in (None, "")]
    lo, hi = min(points + levels), max(points + levels)
    if hi == lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    span = hi - lo
    n = len(points)

    def x_at(i: int) -> float:
        return i * width / (n - 1)

    def y_at(v: float) -> float:
        return height - ((v - lo) / span * height)

    line = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(points))
    area = f"0,{height:.1f} {line} {width:.1f},{height:.1f}"
    rising = points[-1] >= points[0]
    tone = "up" if rising else "down"

    bands = []
    for value, cls in ((stop, "sparkstop"), (target, "sparktarget")):
        if value in (None, ""):
            continue
        y = y_at(float(str(value)))
        if 0 <= y <= height:
            bands.append(
                f'<line class="{cls}" x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}"/>'
            )

    last_x, last_y = x_at(n - 1), y_at(points[-1])
    return f"""<svg class="spark spark-{tone}" viewBox="0 0 {width} {height}"
     preserveAspectRatio="none" aria-hidden="true" focusable="false">
  {''.join(bands)}
  <polygon class="sparkarea" points="{area}" fill="url(#sparkfill)"/>
  <polyline class="sparkline" points="{line}" vector-effect="non-scaling-stroke"/>
  <circle class="sparkdot" cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.6"/>
</svg>"""


def plain_reason(reason: str) -> str:
    """Say why a trade fired in words a non-trader can act on.

    The engine's own strings are precise and unreadable ("pullback: RSI(2) 7.5
    above SMA200"). They stay on the page as the supporting detail; this is
    what leads. Anything unrecognised falls through unchanged rather than being
    dressed up into a claim the strategy did not make.
    """
    text = (reason or "").strip()
    lowered = text.lower()
    if lowered.startswith("breakout"):
        return (
            "Price has broken above its highest level in weeks on unusually heavy "
            "trading. The strategy is buying strength, betting the move continues"
        )
    if lowered.startswith("pullback"):
        return (
            "Price dropped sharply but is still above its long-term average. The "
            "strategy is buying the dip inside what it reads as an uptrend"
        )
    if lowered.startswith("momentum"):
        return (
            "One of the steadiest risers in the list right now. The strategy holds "
            "these for the longer run and rebalances as the ranking changes"
        )
    if lowered.startswith("dropped out"):
        return "No longer one of the strongest risers, so the strategy is stepping out"
    if lowered.startswith("mean reversion complete"):
        return "The bounce the strategy was waiting for has happened, so it is taking the gain"
    if lowered.startswith("exit:"):
        return EXIT_LABELS.get(text.split(":", 1)[1], "The strategy's exit rule has triggered")
    return text


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
        f"this strategy finished ahead on {float(win_rate) * 100:.0f}% of its last "
        f"{history.get('trades', 0)} trades"
        if win_rate is not None
        else "not enough finished trades yet to quote a hit rate"
    )
    reward_risk = order.get("reward_risk")
    rr_note = f"{float(str(reward_risk)):.1f}:1 reward-to-risk" if reward_risk else ""

    weight = order.get("weight")
    weight_note = (
        f"{float(str(weight)) * 100:.1f}% of the book"
        if weight
        else "strategy allocation"
    )
    spark = sparkline_svg(
        order.get("spark") or [],
        stop=order.get("stop_loss"),
        target=order.get("take_profit"),
    )
    spark_block = ""
    if spark:
        series = order.get("spark") or []
        move = (series[-1] - series[0]) / series[0] * 100 if series and series[0] else 0.0
        stop_txt = _price(order["stop_loss"]) if order.get("stop_loss") else "&mdash;"
        target_txt = _price(order["take_profit"]) if order.get("take_profit") else "&mdash;"
        spark_block = f"""<div class="sparkwrap">{spark}</div>
  <div class="sparkscale">
    <span>{len(series)} sessions &middot; {move:+.1f}%</span>
    <span>stop {stop_txt} &middot; target {target_txt}</span>
  </div>"""

    return f"""<article class="sigcard tilt{stale}" data-sigcard="{index}">
  <div class="sighead">
    <span class="tag {side_class}">{side}</span>
    <strong class="signame">{_esc(order['symbol'])}</strong>
    <span class="muted-inline">{_esc(order['name'])}</span>
    <span class="tag">{_esc(region_label)}</span>
    {'' if order['fresh'] else '<span class="tag">resting</span>'}
  </div>
  {spark_block}
  <div class="sigmoney">
    <div class="mcell">
      <span class="mlabel" data-cell="invest-label">Strategy size</span>
      <span class="mvalue" data-cell="invested">{_money_line(order.get('invested'), ccy)}</span>
      <span class="mnote" data-cell="qty">{_esc(order['quantity'])} shares @
        ~{_price(order['reference_price'])} &middot; {weight_note}</span>
    </div>
    <div class="mcell win">
      <span class="mlabel">If target hits</span>
      <span class="mvalue" data-cell="profit">{
        _money_line(order.get('profit_at_target'), ccy, signed=True)}</span>
      <span class="mnote">{_pct_str(order['profit_at_target_pct'])
        if order.get('profit_at_target_pct') else '&mdash;'} &middot; sell at
        {_price(order['take_profit']) if order.get('take_profit') else '&mdash;'}</span>
    </div>
    <div class="mcell lose">
      <span class="mlabel">If stop hits</span>
      <span class="mvalue" data-cell="loss">&minus;{
        _money_line(order.get('loss_at_stop'), ccy)}</span>
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
  <p class="sigwhy"><strong>Why:</strong> {_esc(plain_reason(order.get('reason') or ''))}.
  <strong>How long:</strong> {window}{typical_note}.
  <strong>Track record:</strong> {rate_note}{', ' + rr_note if rr_note else ''}.</p>
  <p class="sigtech">Signal detail: {_esc(order.get('reason') or '')}</p>
</article>"""


def _signals_section(signals: dict) -> str:
    orders = signals.get("orders", [])
    as_of = " &middot; ".join(
        f"{REGION_NAMES.get('IN' if region == 'india' else 'US', region)} prices to {_esc(day)}"
        for region, day in signals.get("as_of", {}).items()
    )
    # Deliberately no daily cap here: the cap that matters is the reader's own,
    # which lives in Settings. Printing the build's default would be quoting a
    # limit that does not apply to them.
    meta = f"""<div class="marketbar">
  <span class="mkt" data-market="india"><span class="mktdot"></span>
    <span data-market-label>NSE</span></span>
  <span class="mkt" data-market="us"><span class="mktdot"></span>
    <span data-market-label>US markets</span></span>
  <span>{as_of}</span>
</div>"""

    if not orders:
        # The commonest state by far: these strategies are meant to sit still.
        # It should read as the system working, with something to do next.
        return meta + """<div class="quietday">
  <h3>Nothing to buy today</h3>
  <p>This is the normal state, not a fault. These strategies wait for specific
  setups &mdash; a breakout on heavy volume, or a sharp dip inside an uptrend &mdash;
  and on most days no stock in the list qualifies. Trading anyway is how people
  lose money on good strategies.</p>
  <p><strong>What to do now:</strong> check your open positions below for any
  flagged <span class="badge hit">STOP HIT</span> or
  <span class="badge target">TARGET HIT</span>, then come back after the next
  market close. The list refreshes automatically each evening.</p>
</div>"""

    has_kite_key = bool(signals.get("kite_api_key"))
    india_fresh = sum(1 for o in orders if o["region"] == "india" and o["fresh"])
    basket_all = ""
    if india_fresh >= 2 and has_kite_key:
        basket_all = (
            '<p><button type="button" class="exec" data-exec="kite:all">'
            f"Send all {india_fresh} India orders to Kite as one basket</button></p>"
        )

    # The scene owns the perspective so every card tilts in the same 3D space
    # rather than each establishing its own vanishing point.
    cards = '<div class="scene">' + "".join(
        _signal_card(i, order, has_kite_key) for i, order in enumerate(orders)
    ) + "</div>"
    caption = (
        "These are the trades the strategies would place at the next market open, "
        "sized to the amount you entered. Paper buy costs nothing and reaches no "
        "broker. The Real buttons hand the order to your own broker, where you "
        "still confirm it yourself. Live prices are delayed. Nothing here is "
        "advice, and no outcome is guaranteed."
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
      <span class="muted-inline">{_esc(position['name'])}</span>
      <span class="cellspark">{sparkline_svg(
          position.get('spark') or [], stop=position.get('stop'),
          target=position.get('take_profit'), width=120, height=26)}</span></td>
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


def _onboarding(signals: dict) -> str:
    """Shown until the reader has told the app what they are working with.

    Hidden by script the moment settings exist, so a returning user never sees
    it. It is placed above everything else because until it is answered, every
    number further down the page belongs to somebody else.
    """
    fresh = sum(1 for order in signals.get("orders", []) if order["fresh"])
    today = (
        f"There {'is' if fresh == 1 else 'are'} <strong>{fresh}</strong> "
        f"suggested trade{'' if fresh == 1 else 's'} today."
        if fresh
        else "There are no suggested trades today &mdash; that is normal."
    )
    return f"""<div class="onboard" data-needs-setup>
  <h2 class="onboardtitle">Start here</h2>
  <p>This app watches Indian and US stocks each day and tells you which ones its
  strategies would buy, at what price, with a target to sell at and a stop to
  limit the damage if it goes wrong. {today}</p>
  <p><strong>First, tell it how much you invest with.</strong> Until you do, the
  amounts on this page are the strategy's own test figures &mdash; not yours, and
  not a suggestion for you.</p>
  {_settings_form()}
  <p class="onboardnote">Then press <strong>Paper buy</strong> on any trade to try
  it with pretend money. Nothing reaches a broker, and nothing costs anything,
  until you deliberately connect one.</p>
</div>"""


def _glance(signals: dict) -> str:
    """The dashboard's at-a-glance strip: state of the book, one tap to act."""
    orders = signals.get("orders", [])
    fresh = sum(1 for order in orders if order["fresh"])
    # Values are placeholders until the settings module restates them in the
    # reader's own money; the labels stay honest in the meantime.
    cards = [
        # No tone on the placeholders: a green or red dash reads as a broken
        # number rather than an absent one. Colour arrives with the value.
        _kpi("Suggested today", str(fresh), tone="pos" if fresh else "flat",
             note="trades the strategies would take"),
        _kpi("You would invest", "&mdash;", note="set your amount to see this",
             cell="today-invest"),
        _kpi("If every target hits", "&mdash;",
             note="best case on these trades", cell="today-upside"),
        _kpi("If every stop hits", "&mdash;",
             note="worst case on these trades", cell="today-downside"),
        _kpi("Your paper profit / loss", "&mdash;", note="across your paper trades",
             cell="today-paper"),
    ]
    cta = (
        '<div class="kpi cta"><button type="button" class="exec big" data-tabgo="invest">'
        "See today's trades &rarr;</button></div>"
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
    return f"""{_settings_form()}
<h3 class="papersub">How you can place trades</h3>
<div class="tiers">
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
/* ---------------------------------------------------------------------------
   Trading-surface layer: depth, sparklines and motion.

   Two rules hold this together. Colour carries direction and nothing else —
   green and red are reserved for up and down, so no button or heading may use
   them decoratively. And motion only ever confirms something that actually
   happened (a price ticked, a panel opened); nothing loops or drifts on its
   own, because ambient movement next to live numbers reads as data changing
   when it has not. Every animation here is disabled under
   prefers-reduced-motion.
--------------------------------------------------------------------------- */
:root{
  --elev-1:0 1px 2px rgba(16,18,22,.06), 0 1px 1px rgba(16,18,22,.04);
  --elev-2:0 4px 14px rgba(16,18,22,.09), 0 1px 3px rgba(16,18,22,.05);
  --elev-3:0 18px 44px rgba(16,18,22,.16), 0 3px 10px rgba(16,18,22,.08);
  --ease:cubic-bezier(.22,.61,.36,1);
  --grid:rgba(120,130,145,.09);
}
@media (prefers-color-scheme:dark){
  :root{
    --elev-1:0 1px 2px rgba(0,0,0,.5);
    --elev-2:0 6px 18px rgba(0,0,0,.55), 0 1px 3px rgba(0,0,0,.4);
    --elev-3:0 22px 50px rgba(0,0,0,.62), 0 4px 12px rgba(0,0,0,.45);
    --grid:rgba(150,160,175,.07);
  }
}
:root[data-theme="dark"]{
  --elev-1:0 1px 2px rgba(0,0,0,.5);
  --elev-2:0 6px 18px rgba(0,0,0,.55), 0 1px 3px rgba(0,0,0,.4);
  --elev-3:0 22px 50px rgba(0,0,0,.62), 0 4px 12px rgba(0,0,0,.45);
  --grid:rgba(150,160,175,.07);
}

/* A faint grid behind the page, like a chart backdrop. Fixed so it reads as
   a surface the content sits on rather than something that scrolls with it. */
body::before{
  content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(var(--grid) 1px,transparent 1px),
                   linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:46px 46px;
  mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 40%,transparent 100%);
  -webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 40%,transparent 100%);
}

.panel{box-shadow:var(--elev-1)}
.kpi{box-shadow:var(--elev-1);transition:transform .22s var(--ease),
  box-shadow .22s var(--ease)}
.kpi:hover{transform:translateY(-2px);box-shadow:var(--elev-2)}

/* Sticky bar becomes a frosted surface once content slides under it. */
.tabs{backdrop-filter:saturate(1.6) blur(12px);
  -webkit-backdrop-filter:saturate(1.6) blur(12px);
  background:color-mix(in srgb,var(--bg) 78%,transparent)}
.tabs button{transition:color .18s var(--ease),background .18s var(--ease)}
.tabs button.active{box-shadow:var(--elev-1)}

/* --- sparklines --- */
.spark{width:100%;height:56px;display:block;overflow:visible}
.spark-up{color:var(--pos)}
.spark-down{color:var(--neg)}
.sparkline{fill:none;stroke:currentColor;stroke-width:1.8;
  stroke-linejoin:round;stroke-linecap:round}
.sparkarea{stroke:none}
.sparkdot{fill:currentColor;stroke:var(--panel);stroke-width:1.5}
.sparkstop{stroke:var(--neg);stroke-width:1;stroke-dasharray:3 3;opacity:.55}
.sparktarget{stroke:var(--pos);stroke-width:1;stroke-dasharray:3 3;opacity:.55}
.sparkwrap{position:relative;margin:2px 0 14px;
  border-radius:8px;overflow:hidden}
.sparkscale{display:flex;justify-content:space-between;font-size:10.5px;
  color:var(--muted);margin-top:5px;font-variant-numeric:tabular-nums}
.cellspark{display:block;width:120px;margin-top:4px;opacity:.9}
.cellspark .spark{height:26px}

/* --- market status --- */
.marketbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  margin:14px 0 2px;font-size:12px;color:var(--muted)}
.mkt{display:inline-flex;align-items:center;gap:6px;
  padding:4px 10px;border:1px solid var(--line);border-radius:999px;
  background:var(--panel);box-shadow:var(--elev-1)}
.mktdot{width:7px;height:7px;border-radius:50%;background:var(--muted);
  flex:0 0 auto}
.mkt.open .mktdot{background:var(--pos);animation:pulse 2.4s var(--ease) infinite}
.mkt.open{color:var(--ink)}
@keyframes pulse{
  0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--pos) 60%,transparent)}
  70%{box-shadow:0 0 0 6px transparent}
}

/* --- value motion: a tick should be felt, not just read --- */
.flash{animation:flashup .7s var(--ease)}
.flash-down{animation:flashdown .7s var(--ease)}
@keyframes flashup{
  0%{background:color-mix(in srgb,var(--pos) 28%,transparent);
     border-radius:4px}
  100%{background:transparent}
}
@keyframes flashdown{
  0%{background:color-mix(in srgb,var(--neg) 28%,transparent);
     border-radius:4px}
  100%{background:transparent}
}

/* Panels enter once, staggered, so the page assembles rather than snapping. */
.tabpanel:not([hidden]) > *{animation:rise .42s var(--ease) both}
.tabpanel:not([hidden]) > *:nth-child(1){animation-delay:.02s}
.tabpanel:not([hidden]) > *:nth-child(2){animation-delay:.06s}
.tabpanel:not([hidden]) > *:nth-child(3){animation-delay:.10s}
.tabpanel:not([hidden]) > *:nth-child(n+4){animation-delay:.14s}
@keyframes rise{from{opacity:0;transform:translateY(10px)}
  to{opacity:1;transform:none}}

.sigcard{box-shadow:var(--elev-1);
  transition:transform .24s var(--ease),box-shadow .24s var(--ease)}
.sigcard:hover{transform:translateY(-3px);box-shadow:var(--elev-3)}
button.exec{transition:transform .16s var(--ease),background .16s var(--ease),
  color .16s var(--ease),box-shadow .16s var(--ease)}
button.exec:not(:disabled):hover{transform:translateY(-1px);box-shadow:var(--elev-2)}
button.exec:not(:disabled):active{transform:translateY(0) scale(.985)}

/* ---------------------------------------------------------------------------
   3D layer.

   Real perspective transforms, not shadows pretending to be depth. Three
   things earn it: cards tilt toward the pointer with their contents on
   separate z-planes, panels swing in around the x-axis, and live prices roll
   on a digit cylinder the way a market board does.

   Rules that keep it from becoming a toy: the tilt is capped at 6 degrees so
   text never distorts enough to hurt legibility, it only engages for a fine
   pointer (a finger has no hover, and a phone tilting under your thumb is
   nausea rather than delight), and every transform is composited — no layout
   property is animated. All of it collapses to flat under reduced motion.
--------------------------------------------------------------------------- */
/* A tilted card reaches outside its own box, so the panel holding a scene must
   not clip. The padding/margin pair gives the rotation room to breathe without
   changing where the content sits. */
.scene{perspective:1100px;perspective-origin:50% 30%;
  padding:18px;margin:-18px}
.panel:has(.scene){overflow:visible}

.tilt{transform-style:preserve-3d;
  transition:transform .5s var(--ease),box-shadow .5s var(--ease);
  will-change:transform}
.tilt.tilting{transition:transform .08s linear}
/* Contents ride at different depths, so tilting produces genuine parallax
   rather than a flat plane rotating. */
.tilt .sighead{transform:translateZ(26px)}
.tilt .sparkwrap{transform:translateZ(38px)}
.tilt .sigmoney{transform:translateZ(18px)}
.tilt .sigwhy,.tilt .sigtech{transform:translateZ(8px)}
.tilt .mcell.act{transform:translateZ(42px)}

/* A specular sheen that tracks the pointer sells the surface as physical. */
.tilt::after{content:"";position:absolute;inset:0;border-radius:inherit;
  pointer-events:none;opacity:0;transition:opacity .4s var(--ease);
  background:radial-gradient(600px circle at var(--mx,50%) var(--my,50%),
    color-mix(in srgb,var(--accent) 16%,transparent),transparent 45%)}
.tilt.tilting::after{opacity:1}

/* Panels swing up into place around their own bottom edge. */
.tabpanel:not([hidden]) > *{animation:swing .52s var(--ease) both}
@keyframes swing{
  from{opacity:0;transform:perspective(1000px) rotateX(-9deg) translateY(16px)}
  to{opacity:1;transform:perspective(1000px) rotateX(0) translateY(0)}
}

/* Buttons depress into the page rather than just changing colour. */
button.exec{transform-style:preserve-3d}
button.exec:not(:disabled):hover{
  transform:perspective(600px) translateY(-1px) translateZ(6px)}
button.exec:not(:disabled):active{
  transform:perspective(600px) rotateX(9deg) translateZ(0) scale(.99)}

.kpi{transform-style:preserve-3d}
.kpi:hover{transform:perspective(800px) translateY(-2px) rotateX(3deg)}

/* --- split-flap odometer --------------------------------------------------
   Each digit is a strip of numerals on a shallow cylinder. The wrapper owns
   the perspective; the strip translates in 3D so the roll is composited. */
.odo{display:inline-flex;align-items:center;gap:1px;
  perspective:220px;vertical-align:baseline}
.odo-digit{position:relative;width:.62em;height:1.15em;overflow:hidden;
  transform-style:preserve-3d;
  background:linear-gradient(180deg,
    color-mix(in srgb,var(--ink) 7%,transparent) 0%,
    transparent 28%,transparent 72%,
    color-mix(in srgb,var(--ink) 7%,transparent) 100%);
  border-radius:3px}
.odo-strip{position:absolute;top:0;left:0;right:0;
  display:flex;flex-direction:column;align-items:center;
  transition:transform .58s cubic-bezier(.16,.84,.3,1);
  will-change:transform}
.odo-strip span{height:1.15em;line-height:1.15em;display:block;
  font-variant-numeric:tabular-nums}
/* Separators sit outside the cylinders so commas never roll. */
.odo-sep{padding:0 .02em}

@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none !important;transition:none !important}
  .kpi:hover,.sigcard:hover,button.exec:hover,button.exec:active{transform:none}
  .tilt,.tilt .sighead,.tilt .sparkwrap,.tilt .sigmoney,
  .tilt .sigwhy,.tilt .sigtech,.tilt .mcell.act{transform:none !important}
  .tilt::after{display:none}
  .scene{perspective:none}
}

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
/* .45 opacity on an already-muted colour fell below readable contrast in the
   light theme; keep it visibly disabled but still legible. */
button.exec:disabled{opacity:.75;cursor:not-allowed;color:var(--muted);
  background:var(--tag);border-style:dashed}
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
/* Both label variants live here, in this order: SIGNALS_CSS is concatenated
   after the base sheet, so a mobile override written in the base sheet's media
   query would be overruled by the default below it. */
.tabshort{display:none}
@media (max-width:640px){
  .tabshort{display:inline}
  .tablong{display:none}
}

.glance{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));
  margin:18px 0 4px;align-items:stretch}
.glance .kpi{justify-content:flex-start}
/* The label can wrap to two lines; reserving the space keeps the row of
   numbers on one baseline instead of stepping up and down. */
.glance .kpi-label{min-height:3.1em;display:flex;align-items:flex-start}
.glance .cta{display:flex;align-items:center;justify-content:center;padding:0;
  border-style:dashed}
.glance .cta button{height:100%}
button.exec.big{font-size:14.5px;padding:12px 18px;width:100%;border-radius:var(--radius)}

.sigcard{position:relative;border:1px solid var(--line);
  border-radius:var(--radius);padding:14px 16px;
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
/* Buttons sit level with the numbers beside them rather than floating in the
   middle of a taller cell. */
.mcell.act{justify-content:flex-start;background:transparent;border:0;
  padding:10px 0 0}
.mlabel{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.mvalue{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;
  letter-spacing:-0.01em}
.mnote{display:block;font-size:11px;color:var(--muted);font-weight:400}
.sigwhy{margin:12px 0 0;font-size:13px;color:var(--muted);line-height:1.65}
.sigwhy strong{color:var(--ink);font-weight:600}
.sigtech{margin:6px 0 0;font-size:11.5px;color:var(--muted);opacity:.7;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.quietday h3{margin:0 0 10px;font-size:16px;color:var(--ink)}
.quietday p{margin:0 0 10px;font-size:13.5px;color:var(--muted);line-height:1.65}
.quietday strong{color:var(--ink)}

.totals{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  margin:14px 0 4px}
.tcell{display:flex;flex-direction:column;gap:3px;padding:12px 14px;
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}

button.exec.ghost{font-size:12px;font-weight:600;padding:7px 10px;color:var(--muted);
  margin-top:6px;width:100%}
button.exec.ghost:hover:not(:disabled){color:var(--accent)}
button.linkish{appearance:none;border:0;background:none;padding:0;font:inherit;
  color:var(--accent);font-weight:600;cursor:pointer;text-decoration:underline}
button.exec.danger{color:var(--neg);border-color:var(--line)}
button.exec.danger:hover{background:color-mix(in srgb,var(--neg) 12%,var(--tag))}
.mcell.act{flex-direction:column;gap:0}
.papersub{font-size:13px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin:26px 0 10px;font-weight:600}
.papertop .caption{margin-top:12px}

.onboard{border:1px solid var(--accent);border-radius:var(--radius);
  background:var(--panel);padding:18px 20px;margin:18px 0 22px}
.onboardtitle{margin:0 0 10px;font-size:18px;letter-spacing:-0.01em;
  text-transform:none;color:var(--ink)}
.onboard p{margin:0 0 12px;font-size:14px;line-height:1.6;color:var(--muted)}
.onboard strong{color:var(--ink)}
.onboardnote{margin-top:14px !important;font-size:13px !important}

.setupbox{margin-bottom:8px}
/* Sentence case at body weight: inside "Start here" this is a sub-step, not a
   second page section competing with the heading above it. */
.fieldsetlabel{margin:0 0 6px;font-size:14px;font-weight:600;color:var(--ink);
  text-transform:none;letter-spacing:0}
.setuphelp{color:var(--muted);font-size:13px;margin:0 0 14px;line-height:1.6}
/* Subgrid rows keep every input on one baseline even when a label wraps to
   two lines, which is what made this form look broken. */
.fields{display:grid;gap:14px 16px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.field{display:grid;grid-template-rows:auto auto auto;gap:5px;align-content:start}
/* min-height reserves a second line so a label that wraps in a narrow column
   cannot drag its input out of line with its neighbours. */
.flabel{font-size:12.5px;font-weight:600;color:var(--ink);align-self:end;
  min-height:1.5em}
.field input{appearance:none;font:inherit;font-size:16px;padding:10px 12px;
  border:1px solid var(--line);border-radius:8px;background:var(--bg);
  color:var(--ink);width:100%;font-variant-numeric:tabular-nums}
.field input:focus{outline:2px solid var(--accent);outline-offset:1px;
  border-color:var(--accent)}
.fnote{font-size:11.5px;color:var(--muted)}
.setupactions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0 0}
.setupactions .execstatus{margin-top:0;max-width:none}
/* Outranks button.exec.big's full-width rule; a Save button should be the
   size of its label, not the width of the form. */
.setupactions button.exec.big{width:auto;min-width:140px;flex:0 0 auto}

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

def _settings_form() -> str:
    """The money controls, in the app.

    Position sizes are meaningless until the app knows what the reader is
    actually working with, and asking them to edit a JSON file and redeploy is
    not a product. These two numbers live in the browser and drive every share
    count, every rupee figure and every cap check on the page.
    """
    return """<div class="setupbox">
  <h3 class="fieldsetlabel">Your money</h3>
  <p class="setuphelp">Nothing here leaves your browser. It is used to size the
  suggested trades to what you actually have, and to cap what you can commit in
  a single day.</p>
  <div class="fields">
    <label class="field">
      <span class="flabel">Your amount &middot; India (&#8377;)</span>
      <input type="number" inputmode="decimal" min="0" step="1000"
             data-setting="capital.INR" placeholder="e.g. 100000">
      <span class="fnote">Blank if you do not trade Indian stocks.</span>
    </label>
    <label class="field">
      <span class="flabel">Your amount &middot; US ($)</span>
      <input type="number" inputmode="decimal" min="0" step="100"
             data-setting="capital.USD" placeholder="e.g. 2000">
      <span class="fnote">Blank if you do not trade US stocks.</span>
    </label>
    <label class="field">
      <span class="flabel">Daily limit &middot; India (&#8377;)</span>
      <input type="number" inputmode="decimal" min="0" step="1000"
             data-setting="cap.INR" placeholder="auto: 30% of your amount">
      <span class="fnote">Most you will commit in one day.</span>
    </label>
    <label class="field">
      <span class="flabel">Daily limit &middot; US ($)</span>
      <input type="number" inputmode="decimal" min="0" step="50"
             data-setting="cap.USD" placeholder="auto: 30% of your amount">
      <span class="fnote">Most you will commit in one day.</span>
    </label>
  </div>
  <p class="setupactions">
    <button type="button" class="exec big" data-settings-save>Save</button>
    <span class="execstatus" data-settings-status aria-live="polite"></span>
  </p>
</div>"""


#: Per-user money settings, and the re-sizing of every signal to match them.
#:
#: The engine sizes positions against its own simulated book. Showing those
#: share counts to a reader with different capital is worse than showing
#: nothing: it reads as instruction. So each signal carries the allocation it
#: represents as a fraction, and this module restates quantity, cost, upside
#: and downside in the reader's own money before anything is presented as
#: theirs.
SETTINGS_JS = """
(function () {
  var blob = document.getElementById('signals-data');
  if (!blob) return;
  var cfg = window.__mpCfg;
  if (!cfg) {
    try { cfg = JSON.parse(blob.textContent); } catch (e) { return; }
    window.__mpCfg = cfg;
  }
  // Shared parse (see __mpCfg above): the per-order sizing written here must
  // be the same object the paper broker later spends against.
  var KEY = 'markets-pro.settings.v1';
  var CAP_FRACTION = 0.30;

  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return null;
      var s = JSON.parse(raw);
      return (s && s.capital) ? s : null;
    } catch (e) { return null; }
  }
  function write(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* blocked */ }
  }
  function total(settings) {
    if (!settings) return 0;
    var rate = Number(cfg.usdinr) || 0;
    var inr = Number(settings.capital.INR || 0);
    var usd = Number(settings.capital.USD || 0);
    return usd + (rate ? inr / rate : 0);
  }
  function capFor(settings, ccy) {
    if (!settings) return 0;
    var explicit = Number((settings.cap || {})[ccy] || 0);
    if (explicit > 0) return explicit;
    return Number(settings.capital[ccy] || 0) * CAP_FRACTION;
  }
  function money(n, digits) {
    return Number(n).toLocaleString('en-US',
      {minimumFractionDigits: digits === undefined ? 0 : digits,
       maximumFractionDigits: digits === undefined ? 0 : digits});
  }

  // How many shares the reader's own capital buys at this signal's allocation.
  function sizeFor(order, settings) {
    var weight = Number(order.weight || 0);
    var price = Number(order.reference_price || 0);
    if (!weight || !price || !settings) return null;
    var rate = Number(cfg.usdinr) || 0;
    var allocationBase = total(settings) * weight;
    var allocation = order.currency === 'INR' ? allocationBase * rate : allocationBase;
    var pocket = Number(settings.capital[order.currency] || 0);
    if (pocket <= 0) return {qty: 0, reason: 'no ' + order.currency + ' set'};
    if (allocation > pocket) allocation = pocket;
    var qty = Math.floor(allocation / price);
    return {qty: qty, allocation: allocation, price: price,
            reason: qty < 1 ? 'needs at least ' + money(Math.ceil(price)) + ' ' +
                              order.currency + ' for one share' : ''};
  }

  function applySizing() {
    var settings = read();
    (cfg.orders || []).forEach(function (order, i) {
      var card = document.querySelector('[data-sigcard="' + i + '"]');
      if (!card) return;
      var label = card.querySelector('[data-cell="invest-label"]');
      var invested = card.querySelector('[data-cell="invested"]');
      var qtyNote = card.querySelector('[data-cell="qty"]');
      var profit = card.querySelector('[data-cell="profit"]');
      var loss = card.querySelector('[data-cell="loss"]');
      var button = card.querySelector('[data-paper-buy]');
      var ccy = '<span class="ccy">' + order.currency + '</span>';

      if (!settings) {
        label.textContent = 'Strategy size';
        return;
      }
      var sized = sizeFor(order, settings);
      order.user = sized;                      // paper buys use the reader's size
      label.textContent = 'You invest';
      if (!sized || sized.qty < 1) {
        invested.innerHTML = '&mdash;';
        qtyNote.textContent = sized ? sized.reason : 'set your amount in Settings';
        profit.innerHTML = '&mdash;';
        loss.innerHTML = '&mdash;';
        if (button) { button.disabled = true; button.textContent = 'Too small to buy'; }
        return;
      }
      if (button) { button.disabled = false; button.textContent = 'Paper buy'; }
      var cost = sized.qty * sized.price;
      invested.innerHTML = money(cost) + ' ' + ccy;
      qtyNote.textContent = sized.qty + ' share' + (sized.qty === 1 ? '' : 's') +
        ' @ ~' + money(sized.price, 2);
      if (order.take_profit) {
        var up = (Number(order.take_profit) - sized.price) * sized.qty;
        profit.innerHTML = '+' + money(up) + ' ' + ccy;
      }
      if (order.stop_loss) {
        var down = (sized.price - Number(order.stop_loss)) * sized.qty;
        loss.innerHTML = '\\u2212' + money(down) + ' ' + ccy;
      }
    });
    renderToday(settings);
  }

  // The dashboard headline: the reader's own exposure today, never the
  // engine's. Left blank rather than filled with the book's figures.
  function renderToday(settings) {
    function put(name, text, tone) {
      var el = document.querySelector('[data-cell="' + name + '"]');
      if (!el) return;
      el.innerHTML = text;
      if (tone !== undefined) {
        el.classList.remove('pos', 'neg', 'flat');
        if (tone) el.classList.add(tone);
      }
    }
    var rate = Number(cfg.usdinr) || 0;
    function toBase(amount, ccy) {
      return ccy === 'INR' ? (rate ? amount / rate : 0) : amount;
    }

    if (!settings) {
      put('today-invest', '&mdash;', '');
      put('today-upside', '&mdash;', '');
      put('today-downside', '&mdash;', '');
      put('today-paper', '&mdash;', '');
      return;
    }

    var invest = 0, up = 0, down = 0, taken = 0;
    (cfg.orders || []).forEach(function (order) {
      if (!order.fresh) return;
      var sized = order.user;
      if (!sized || sized.qty < 1) return;
      taken += 1;
      invest += toBase(sized.qty * sized.price, order.currency);
      if (order.take_profit) {
        up += toBase((Number(order.take_profit) - sized.price) * sized.qty, order.currency);
      }
      if (order.stop_loss) {
        down += toBase((sized.price - Number(order.stop_loss)) * sized.qty, order.currency);
      }
    });

    if (!taken) {
      put('today-invest', '&mdash;', '');
      put('today-upside', '&mdash;', '');
      put('today-downside', '&mdash;', '');
      var note = document.querySelector('[data-cell="today-invest-note"]');
      if (note) note.textContent = 'nothing to buy today';
    } else {
      put('today-invest', money(invest, 2) + ' <span class="ccy">USD</span>');
      put('today-upside', '+' + money(up, 2) + ' <span class="ccy">USD</span>', 'pos');
      put('today-downside', '\\u2212' + money(down, 2) + ' <span class="ccy">USD</span>', 'neg');
      var n = document.querySelector('[data-cell="today-invest-note"]');
      if (n) n.textContent = 'across ' + taken + ' trade' + (taken === 1 ? '' : 's') +
        ', in your money';
    }

    // Paper profit/loss, marked with whatever quotes have arrived.
    var paper = null;
    try { paper = JSON.parse(localStorage.getItem('markets-pro.paper.v1')); } catch (e) { /* */ }
    if (!paper || !paper.positions) { put('today-paper', '&mdash;', ''); return; }
    var pnl = 0, held = 0;
    Object.keys(paper.positions).forEach(function (k) {
      var p = paper.positions[k];
      held += 1;
      var q = window.__mpQuotes && window.__mpQuotes[p.yahoo];
      var mark = q ? Number(q.price) : Number(p.cost);
      pnl += toBase((mark - p.cost) * p.qty, p.currency);
    });
    (paper.log || []).forEach(function (row) {
      if (row.action === 'sell') pnl += toBase(row.pnl || 0, row.currency);
    });
    if (!held && !(paper.log || []).length) { put('today-paper', '&mdash;', ''); return; }
    put('today-paper', (pnl >= 0 ? '+' : '\\u2212') + money(Math.abs(pnl), 2) +
      ' <span class="ccy">USD</span>', pnl > 0 ? 'pos' : (pnl < 0 ? 'neg' : 'flat'));
  }
  window.__mpRenderToday = function () { renderToday(read()); };

  function fillForm() {
    var settings = read() || {capital: {}, cap: {}};
    document.querySelectorAll('[data-setting]').forEach(function (input) {
      var parts = input.getAttribute('data-setting').split('.');
      var value = (settings[parts[0]] || {})[parts[1]];
      input.value = (value === undefined || value === null || value === 0) ? '' : value;
    });
  }

  function save() {
    var settings = {capital: {}, cap: {}};
    document.querySelectorAll('[data-setting]').forEach(function (input) {
      var parts = input.getAttribute('data-setting').split('.');
      var value = Number(input.value);
      if (input.value !== '' && isFinite(value) && value >= 0) settings[parts[0]][parts[1]] = value;
    });
    var status = document.querySelector('[data-settings-status]');
    if (!Number(settings.capital.INR || 0) && !Number(settings.capital.USD || 0)) {
      if (status) status.textContent = 'Enter how much you invest with, in at least one market.';
      return;
    }
    write(settings);
    if (status) status.textContent = 'Saved. Every signal is now sized to your amount.';
    applySizing();
    document.querySelectorAll('[data-needs-setup]').forEach(function (el) {
      el.hidden = true;
    });
  }

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-settings-save]')) save();
    if (event.target.closest('[data-goto-settings]')) {
      var tab = document.querySelector('[data-tabbtn="setup"]');
      if (tab) { tab.click(); window.scrollTo(0, 0); }
    }
  });

  window.__mpSettings = {read: read, capFor: capFor, apply: applySizing, total: total};
  fillForm();
  applySizing();
  if (read()) {
    document.querySelectorAll('[data-needs-setup]').forEach(function (el) { el.hidden = true; });
  }
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
  var cfg = window.__mpCfg;
  if (!cfg) {
    try { cfg = JSON.parse(blob.textContent); } catch (e) { return; }
    window.__mpCfg = cfg;
  }

  var KEY = 'markets-pro.paper.v1';
  var summaryEl = document.querySelector('[data-paper-summary]');
  if (!summaryEl) return;

  // The paper book opens with the reader's own capital, not the engine's.
  function fresh() {
    var settings = window.__mpSettings && window.__mpSettings.read();
    var source = (settings && settings.capital) || cfg.starting_cash || {};
    var cash = {};
    Object.keys(source).forEach(function (c) { cash[c] = Number(source[c]) || 0; });
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
    var settings = window.__mpSettings && window.__mpSettings.read();
    if (!settings) {
      return {ok: false, message: 'set how much you invest with first'};
    }
    var state = load();
    var ccy = order.currency;
    var price = Number(livePrice(order.yahoo) || order.reference_price);
    // order.user is the reader-sized quantity written by the settings module.
    var qty = order.user ? Number(order.user.qty) : Number(order.quantity);
    if (!qty || qty < 1) {
      return {ok: false, message: 'your amount is too small for one share'};
    }
    var cost = price * qty;
    var cap = window.__mpSettings.capFor(settings, ccy);

    if (cap > 0 && spentToday(state, ccy) + cost > cap) {
      return {ok: false, message: 'that is ' + money(cost) + ' ' + ccy +
        ', over your ' + money(cap) + ' daily limit — raise it in Settings if you mean to'};
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
      tcell('Holdings at market', marketValue,
            keys.length + (keys.length === 1 ? ' position' : ' positions'), '') +
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
    // The dashboard headline reports this book, so it has to hear about
    // every buy, sell and reset — not only about new quotes.
    if (window.__mpRenderToday) window.__mpRenderToday();
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


#: Split-flap odometer for live prices.
#:
#: Ownership is the whole design here. An earlier count-up animation captured
#: an element's text on start and wrote it back on end, which stranded a stale
#: figure whenever application code updated the same cell mid-flight — wrong
#: money left on screen. So the odometer never reads the DOM to decide what to
#: show: the caller passes the value, the digits are rebuilt from that value
#: alone, and the accessible text is set from it in the same call. There is
#: exactly one writer.
ODOMETER_JS = """
(function () {
  var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  var animate = !(still && still.matches);

  function buildDigit() {
    var digit = document.createElement('span');
    digit.className = 'odo-digit';
    var strip = document.createElement('span');
    strip.className = 'odo-strip';
    for (var n = 0; n <= 9; n++) {
      var face = document.createElement('span');
      face.textContent = String(n);
      strip.appendChild(face);
    }
    digit.appendChild(strip);
    return digit;
  }

  // `text` is the already-formatted string; we only decide how to display it.
  function render(node, text) {
    var wrap = node.querySelector('.odo');
    if (!wrap || wrap.getAttribute('data-shape') !== shapeOf(text)) {
      node.textContent = '';
      wrap = document.createElement('span');
      wrap.className = 'odo';
      wrap.setAttribute('data-shape', shapeOf(text));
      // Every digit carries all ten numerals; only one is visible through the
      // clip. Assistive tech would otherwise read "0123456789" per digit, so
      // the strip is hidden from it and the cell's aria-label carries the
      // real value instead.
      wrap.setAttribute('aria-hidden', 'true');
      for (var i = 0; i < text.length; i++) {
        var ch = text[i];
        if (ch >= '0' && ch <= '9') {
          wrap.appendChild(buildDigit());
        } else {
          var sep = document.createElement('span');
          sep.className = 'odo-sep';
          sep.textContent = ch;
          wrap.appendChild(sep);
        }
      }
      node.appendChild(wrap);
    }

    var slots = wrap.childNodes, index = 0;
    for (var j = 0; j < text.length; j++) {
      var c = text[j];
      var slot = slots[j];
      if (!slot) break;
      if (c >= '0' && c <= '9') {
        var strip = slot.firstChild;
        var offset = -Number(c) * 1.15;
        if (!animate) strip.style.transition = 'none';
        // Stagger by position: the board settles left to right.
        strip.style.transitionDelay = animate ? (index * 45) + 'ms' : '0ms';
        strip.style.transform = 'translate3d(0,' + offset + 'em,0)';
        index++;
      } else if (slot.textContent !== c) {
        slot.textContent = c;
      }
    }
    node.setAttribute('aria-label', text);
    node.setAttribute('role', 'text');
  }

  function shapeOf(text) {
    return text.replace(/[0-9]/g, '#');
  }

  window.__mpOdometer = render;
})();
"""


#: Pointer-tracked 3D tilt.
#:
#: Engages only for a fine pointer with hover: on a touch screen there is no
#: hover to track, and a card that tilts under a thumb is motion sickness, not
#: delight. Reads are batched into one rAF frame and only ever write transform
#: and two custom properties, so nothing here triggers layout.
TILT_JS = """
(function () {
  var fine = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)');
  var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!fine || !fine.matches || (still && still.matches)) return;

  var MAX = 6;           // degrees; beyond this, text starts to smear

  function bind(card) {
    // Per-card frame handle. A shared one would let the first card to schedule
    // block every other card until its callback ran.
    var frame = null;
    var pending = null;

    function apply() {
      frame = null;
      if (!pending) return;
      var rect = pending.rect, x = pending.x, y = pending.y;
      var px = (x - rect.left) / rect.width;
      var py = (y - rect.top) / rect.height;
      var rotY = (px - 0.5) * 2 * MAX;
      var rotX = (0.5 - py) * 2 * MAX;
      card.style.transform =
        'rotateX(' + rotX.toFixed(2) + 'deg) rotateY(' + rotY.toFixed(2) + 'deg) ' +
        'translateZ(6px)';
      card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
      card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
    }

    card.addEventListener('pointermove', function (event) {
      if (event.pointerType !== 'mouse') return;
      pending = {rect: card.getBoundingClientRect(), x: event.clientX, y: event.clientY};
      card.classList.add('tilting');
      if (frame === null) frame = requestAnimationFrame(apply);
    });

    card.addEventListener('pointerleave', function () {
      // Clearing the handle matters: while the page is hidden the browser
      // never runs the callback, so a handle left set would make the guard
      // below reject every future move and the card would stop tilting for
      // the rest of the session.
      if (frame !== null) { cancelAnimationFrame(frame); frame = null; }
      pending = null;
      card.classList.remove('tilting');
      card.style.transform = '';
      card.style.removeProperty('--mx');
      card.style.removeProperty('--my');
    });

    // Same reasoning on returning to the tab: drop any handle whose callback
    // was never delivered.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && frame !== null) {
        cancelAnimationFrame(frame);
        frame = null;
      }
    });
  }

  document.querySelectorAll('.tilt').forEach(bind);
  window.__mpBindTilt = function (root) {
    (root || document).querySelectorAll('.tilt').forEach(bind);
  };
})();
"""


#: The live layer: market clock, counting numbers, and a flash on every tick.
#:
#: Session times are computed in the viewer's browser from UTC, so the status
#: stays correct between nightly rebuilds — a market that opened an hour ago
#: must not still say "closed" because the page was generated last night.
#: Holidays are not modelled, so this answers "are we inside trading hours",
#: which is what the label claims and no more.
MARKET_JS = """
(function () {
  // Local exchange times, resolved through the venue's own timezone so US
  // daylight saving is handled by the platform rather than hardcoded — a
  // fixed UTC offset would read an hour wrong for half the year.
  var SESSIONS = {
    india: {label: 'NSE', zone: 'Asia/Kolkata', open: 9 * 60 + 15, close: 15 * 60 + 30},
    us: {label: 'US markets', zone: 'America/New_York', open: 9 * 60 + 30, close: 16 * 60}
  };

  function localParts(zone) {
    try {
      var fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: zone, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false
      });
      var parts = {};
      fmt.formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
      return {
        minutes: Number(parts.hour) * 60 + Number(parts.minute),
        weekday: parts.weekday
      };
    } catch (e) {
      return null;                    // no Intl: fall back to "closed"
    }
  }

  function refresh() {
    Object.keys(SESSIONS).forEach(function (region) {
      var node = document.querySelector('[data-market="' + region + '"]');
      if (!node) return;
      var spec = SESSIONS[region];
      var now = localParts(spec.zone);
      var weekday = now && ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].indexOf(now.weekday) >= 0;
      var open = !!now && weekday && now.minutes >= spec.open && now.minutes < spec.close;
      node.classList.toggle('open', open);
      var label = node.querySelector('[data-market-label]');
      if (label) label.textContent = spec.label + (open ? ' open' : ' closed');
      node.title = (open ? spec.label + ' is in its trading session'
                         : spec.label + ' is outside trading hours')
        + ' — public holidays are not accounted for';
    });
  }

  refresh();
  setInterval(refresh, 30000);
})();
"""

#: Counts a number up to its value on first sight.
#:
#: Scoped strictly to elements marked ``data-count`` — figures the page renders
#: once and never rewrites. It must never touch a value that application code
#: updates: the animation captures the text when it starts and restores it when
#: it ends, so a write landing mid-flight would be overwritten by the stale
#: string, leaving a wrong number on screen permanently. The live cells get
#: their motion from the tick flash instead, which only ever adds a class.
#:
#: Purely presentational either way: the correct figure is already in the
#: markup, so reduced-motion and no-script readers see it immediately.
COUNTER_JS = """
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (typeof IntersectionObserver !== 'function') return;

  // Animate the number's own text node only. Rewriting the element's
  // textContent would flatten the currency <span> that sits beside it.
  function animate(node) {
    var textNode = null;
    for (var i = 0; i < node.childNodes.length; i++) {
      var child = node.childNodes[i];
      if (child.nodeType === 3 && child.nodeValue.trim()) { textNode = child; break; }
    }
    if (!textNode) return;

    var original = textNode.nodeValue;
    // Keep the surrounding whitespace: the gap before a trailing currency
    // span is part of the layout, and dropping it makes the value jump.
    var edges = original.match(/^(\\s*)([\\s\\S]*?)(\\s*)$/);
    var lead = edges[1], core = edges[2], trail = edges[3];
    var match = core.match(/^([+\\u2212-]?)([\\d,]+(?:\\.\\d+)?)$/);
    if (!match) return;
    var sign = match[1], target = Number(match[2].replace(/,/g, ''));
    if (!isFinite(target) || target === 0) return;
    // Counting a small integer up from zero just makes "1 trade" flicker
    // through "0", which is the one value that must never be shown wrongly.
    if (Math.abs(target) < 10) return;
    var decimals = (match[2].split('.')[1] || '').length;
    var started = null, duration = 750;

    function frame(now) {
      if (started === null) started = now;
      var t = Math.min((now - started) / duration, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      if (t < 1) {
        textNode.nodeValue = lead + sign + (target * eased).toLocaleString('en-US', {
          minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + trail;
        requestAnimationFrame(frame);
      } else {
        textNode.nodeValue = original;   // exact original string, never a re-format
      }
    }
    requestAnimationFrame(frame);
  }

  var seen = new WeakSet();
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting || seen.has(entry.target)) return;
      seen.add(entry.target);
      animate(entry.target);
    });
  }, {threshold: 0.6});

  function watch() {
    document.querySelectorAll('[data-count]').forEach(function (n) {
      if (!seen.has(n)) io.observe(n);
    });
  }
  watch();
  window.__mpWatchCounters = watch;
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
  var cfg = window.__mpCfg;
  if (!cfg) {
    try { cfg = JSON.parse(blob.textContent); } catch (e) { return; }
    window.__mpCfg = cfg;
  }
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
      // Flash the direction of the change, the way a trading screen does.
      var prev = Number(cell.getAttribute('data-last'));
      if (prev && prev !== price) {
        cell.classList.remove('flash', 'flash-down');
        void cell.offsetWidth;                       // restart the animation
        cell.classList.add(price > prev ? 'flash' : 'flash-down');
      }
      cell.setAttribute('data-last', String(price));
      // The odometer is the single writer for this cell's contents; it is
      // handed the finished string rather than reading anything back.
      if (window.__mpOdometer && cell.classList.contains('mvalue')) {
        window.__mpOdometer(cell, text);
      } else {
        cell.textContent = text;
      }
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
/* A right-aligned number butting against a left-aligned badge in the next
   column reads as one run-on value; give the pair breathing room. */
td.num + td:not(.num),th.num + th:not(.num){padding-left:18px}
td.num .mnote{display:block;line-height:1.35}
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
  /* Fit all five tabs on a phone rather than hiding the last one behind a
     scroll most people never discover. */
  /* Share the width equally so every tab is reachable without a sideways
     scroll people do not know is there. */
  .tabs{gap:0;overflow-x:visible}
  .tabs button{flex:1 1 0;min-width:0;justify-content:center;
    font-size:12.5px;padding:9px 4px;gap:4px}
  .tabbadge{min-width:16px;font-size:10px;padding:1px 5px}
  .onboard{padding:16px 15px}
  .onboardtitle{font-size:17px}
  .sigcard{padding:13px 13px}
  .mvalue{font-size:17px}
}
"""


def _tab_label(short: str, full: str) -> str:
    """Short label on phones, full label with room to spare."""
    return f'<span class="tabshort">{short}</span><span class="tablong">{full}</span>'


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
    strategy_book = ""
    if signals is not None:
        fresh_count = sum(1 for order in signals.get("orders", []) if order["fresh"])
        badge = f'<span class="tabbadge">{fresh_count}</span>' if fresh_count else ""
        invest_label = _tab_label("Invest", "Invest Now")
        paper_label = _tab_label("Paper", "Paper")
        invest_tab = (
            '<button type="button" role="tab" data-tabbtn="invest" aria-selected="false" '
            f'aria-controls="panel-invest">{invest_label}{badge}</button>'
            '<button type="button" role="tab" data-tabbtn="paper" aria-selected="false" '
            f'aria-controls="panel-paper">{paper_label}'
            '<span class="tabbadge" data-paper-badge '
            'style="display:none"></span></button>'
        )
        glance = _onboarding(signals) + _glance(signals)
        # The engine's own book is deliberately NOT on this tab. A reader with
        # one paper trade seeing the strategy's three test positions reads them
        # as holdings of theirs; it lives under the track record instead.
        invest_panel = f"""
  <section class="tabpanel" id="panel-invest" data-tab="invest" role="tabpanel" hidden>
    <h2>Today's suggested trades</h2>
    <div class="panel">{_signals_section(signals)}</div>
    <p class="caption">Your own holdings and profit/loss are under
    <button type="button" class="linkish" data-tabgo="paper">Paper</button>.</p>
  </section>

  <section class="tabpanel" id="panel-paper" data-tab="paper" role="tabpanel" hidden>
    <h2>Your paper portfolio</h2>
    <div class="panel">{_paper_section()}</div>
  </section>
"""
        strategy_book = f"""
    <h2>What the strategy holds in its own test book</h2>
    <div class="panel">{_positions_section(signals)}</div>"""
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
        # Order matters: settings defines the sizing the paper book spends
        # against, and both must exist before the quote poll starts marking.
        signal_script = (
            f"<script>{SETTINGS_JS}</script>\n"
            f"<script>{PAPER_JS}</script>\n"
            f"<script>{SIGNALS_JS}</script>\n"
            f"<script>{MARKET_JS}</script>\n"
            f"<script>{COUNTER_JS}</script>\n"
            f"<script>{ODOMETER_JS}</script>\n"
            f"<script>{TILT_JS}</script>"
        )

    dash_label = _tab_label("Today", "Dashboard")
    record_label = _tab_label("Record", "Track record")
    setup_label = _tab_label("Setup", "Settings")
    tab_bar = f"""<nav class="tabs" role="tablist" aria-label="Sections">
    <button type="button" role="tab" data-tabbtn="dashboard" aria-selected="true"
            aria-controls="panel-dashboard" class="active">{dash_label}</button>
    {invest_tab}
    <button type="button" role="tab" data-tabbtn="performance" aria-selected="false"
            aria-controls="panel-performance">{record_label}</button>
    <button type="button" role="tab" data-tabbtn="setup" aria-selected="false"
            aria-controls="panel-setup">{setup_label}</button>
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
{SPARK_DEFS}
<div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <p class="sub">{sub}</p>
  </header>

  {tab_bar}

  <section class="tabpanel" id="panel-dashboard" data-tab="dashboard" role="tabpanel">
    {glance}
    <div class="notice">
      <p><strong>No profit is promised here.</strong> These are rule-based
      suggestions, not advice, and the strategies lose on plenty of individual
      trades &mdash; see the track record for exactly how often. Past results
      come from a backtest and do not predict future returns. Decide every
      trade yourself.</p>
    </div>
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
{strategy_book}
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
    {verified}Prices refresh automatically after each market close.
    Your amounts and paper trades are stored only in this browser.
  </footer>
</div>
{signal_blob}
<script>{TABS_JS}</script>
<script>{ZOOM_JS}</script>
{signal_script}
</body>
</html>"""
