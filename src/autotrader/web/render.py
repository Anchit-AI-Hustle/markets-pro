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

#: Snapshot region spelling -> the code :data:`REGION_NAMES` is keyed by.
REGION_CODE_BY_NAME = {"india": "IN", "us": "US"}

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
        spark_block = f"""<div class="sparkwrap openable" data-stock="{
            _esc(order.get('key', ''))}" role="button" tabindex="0"
     aria-label="Open {_esc(order['symbol'])} detail">{spark}</div>
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
      <span class="cellspark openable" data-stock="{_esc(position.get('key', ''))}"
            role="button" tabindex="0"
            aria-label="Open {_esc(position['symbol'])} detail">{sparkline_svg(
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

/* Touch devices get their 3D from scrolling instead of hovering.
   A card leans back as it rises into view, comes flat as it passes the middle
   of the screen, and leans away as it leaves — so the depth is driven by the
   reader's own thumb rather than by a gyroscope. That matters: the device
   orientation API needs an explicit permission prompt on iOS, and a card that
   moves whenever the phone does is nausea. Scroll position is the one input
   the reader is already deliberately controlling.

   Pure CSS via a view timeline: no scroll listener, so it cannot jank the
   thread that the price feed and the paper book run on. Browsers without
   support simply keep the flat layout. */
@media (hover: none), (pointer: coarse){
  @supports (animation-timeline: view()){
    .tilt{
      animation:cardturn linear both;
      animation-timeline:view();
      animation-range:entry 12% exit 88%;
      transition:none;
    }
    @keyframes cardturn{
      from{transform:perspective(1000px) rotateX(7deg) scale(.965);opacity:.7}
      42%,58%{transform:perspective(1000px) rotateX(0) scale(1);opacity:1}
      to{transform:perspective(1000px) rotateX(-7deg) scale(.965);opacity:.7}
    }
    /* Gentler on the stat tiles: several sit on screen at once, so a strong
       angle on each turns the grid into noise. */
    .kpi{
      animation:tileturn linear both;
      animation-timeline:view();
      animation-range:entry 5% entry 95%;
    }
    @keyframes tileturn{
      from{transform:perspective(900px) rotateX(5deg) translateY(10px);opacity:.55}
      to{transform:perspective(900px) rotateX(0) translateY(0);opacity:1}
    }
  }
}

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

/* --- mutual funds --------------------------------------------------------- */
.fundsbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.fundstable{width:100%;min-width:560px;font-size:12.5px}
.fundstable td{vertical-align:top}
.fundstable strong{display:block;font-size:13px}
.fundmeta{display:block;font-size:10.5px;color:var(--muted);margin-top:2px}
.fundplan{font-size:11.5px;color:var(--muted);white-space:nowrap}
.fundday{font-size:11px;color:var(--muted);white-space:nowrap}
@media (max-width:640px){.fundplan,.fundday{display:none}
  .fundstable{min-width:0}}

/* --- stock detail --------------------------------------------------------- */
.nofund{padding:12px 14px;border:1px dashed var(--line);border-radius:8px;
  font-size:12.5px;color:var(--muted);line-height:1.6}
.nofund strong{color:var(--ink)}
.nofundfix{display:block;margin-top:7px;padding-top:7px;
  border-top:1px solid var(--line);color:var(--muted)}
.fundwrap{overflow-x:auto;margin:12px 0 4px}
.fundtable{min-width:520px;font-size:12.5px}
.fundtable th{font-size:10.5px}
.fundtable td:first-child,.fundtable th:first-child{font-weight:600}
.fundsrc{color:var(--accent);font-weight:600}
.fundsrc:hover{text-decoration:underline}
.openable{cursor:pointer}
tr.openable:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
.screenrow.openable:hover{border-color:var(--accent)}
.openable:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.detail{animation:rise .3s var(--ease) both}
.detailback{appearance:none;border:1px solid var(--line);background:var(--panel);
  color:var(--muted);font:inherit;font-size:12.5px;font-weight:600;
  padding:8px 13px;border-radius:8px;cursor:pointer;margin:18px 0 16px}
.detailback:hover{color:var(--accent);border-color:var(--accent)}
.detailhead{display:flex;justify-content:space-between;align-items:flex-start;
  gap:18px;flex-wrap:wrap;padding-bottom:16px;border-bottom:1px solid var(--line)}
.detailsym{margin:0;font-size:28px;letter-spacing:-0.02em}
.detailname{margin:2px 0 8px;color:var(--muted);font-size:14px}
.detailtags{margin:0;display:flex;gap:5px;flex-wrap:wrap}
.detailprice{text-align:right;display:flex;flex-direction:column;gap:2px}
.detaillast{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
.detaillast i{font-style:normal;font-size:13px;color:var(--muted)}
.detailmove{font-size:14px;font-weight:600}
.chartbar{display:flex;justify-content:space-between;align-items:center;
  gap:12px;flex-wrap:wrap;margin-bottom:8px}
.chartmove{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums}
.rangebtns{display:inline-flex;gap:2px;border:1px solid var(--line);
  border-radius:8px;padding:2px;background:var(--panel)}
.rangebtn{appearance:none;border:0;background:transparent;color:var(--muted);
  font:inherit;font-size:11.5px;font-weight:600;padding:5px 10px;
  border-radius:6px;cursor:pointer}
.rangebtn:hover{color:var(--ink);background:var(--tag)}
.rangebtn.on{color:var(--accent);background:var(--tag)}
.rangebtn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.volchart{width:100%;height:34px;display:block;margin-top:2px}
.volchart rect{fill:var(--muted);opacity:.42}
.chartscale{display:flex;justify-content:space-between;font-size:11px;
  color:var(--muted);margin-top:6px}
.sparkwrap.openable,.cellspark.openable{cursor:pointer;border-radius:6px}
.idxcard.openable{cursor:pointer;transition:border-color .16s var(--ease),
  transform .16s var(--ease)}
.idxcard.openable:hover{border-color:var(--accent);transform:translateY(-2px)}
.idxcard.openable:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.sparkwrap.openable:hover,.cellspark.openable:hover{
  outline:1px solid var(--accent);outline-offset:2px}
.sparkwrap.openable:focus-visible,.cellspark.openable:focus-visible{
  outline:2px solid var(--accent);outline-offset:2px}
.detailchart{margin:18px 0 6px}
.detailchart svg{width:100%;height:190px;display:block}
.chartscale{display:flex;justify-content:space-between;font-size:11px;
  color:var(--muted);margin-top:6px}
.detailgrid{display:grid;gap:10px;margin:16px 0;
  grid-template-columns:repeat(auto-fit,minmax(132px,1fr))}
.detailgrid.tight{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
.dstat{display:flex;flex-direction:column;gap:1px;padding:10px 12px;
  border:1px solid var(--line);border-radius:8px}
.dstat i{font-style:normal;font-size:10px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.dstat b{font-size:17px;font-variant-numeric:tabular-nums;text-transform:capitalize}
.dstat u{text-decoration:none;font-size:10.5px;color:var(--muted)}
.detailstatus{padding:11px 14px;border-radius:8px;background:var(--tag);
  font-size:13px;color:var(--muted);margin:6px 0 4px;line-height:1.55}
.detailstatus strong{color:var(--ink)}
.detailstatus.held,.detailstatus.signal{
  background:color-mix(in srgb,var(--accent) 12%,var(--tag))}
.detailsub{margin:22px 0 10px;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--accent);font-weight:700}
.detailverdict{display:flex;gap:10px;align-items:stretch;flex-wrap:wrap;
  margin-bottom:10px}
.detailverdict .screensig{margin-left:0;align-self:center;font-size:12px;
  padding:6px 12px}
.detailverdict .dstat{flex:1 1 110px}
.techtable{border:1px solid var(--line);border-radius:9px;overflow:hidden}
.techrow{display:grid;grid-template-columns:130px 78px 96px 1fr;gap:12px;
  align-items:baseline;padding:10px 13px;border-bottom:1px solid var(--line);
  font-size:12.5px}
.techrow:last-child{border-bottom:none}
.techlabel{font-weight:600}
.techval{font-variant-numeric:tabular-nums;color:var(--ink)}
.techword{font-weight:700;font-size:11.5px;color:var(--accent)}
.techsay{color:var(--muted);font-size:12px}
@media (max-width:640px){
  .detailhead{flex-direction:column}
  .detailprice{text-align:left}
  .techrow{grid-template-columns:1fr auto;gap:4px 10px}
  .techword{grid-column:1}
  .techsay{grid-column:1 / -1}
}

/* --- markets -------------------------------------------------------------- */
.mktgroup{margin:20px 0 10px;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--accent);font-weight:700}
.idxgrid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.idxcard{border:1px solid var(--line);border-radius:9px;padding:12px 13px;
  background:var(--panel);box-shadow:var(--elev-1);display:flex;
  flex-direction:column;gap:2px}
.idxname{font-size:12px;color:var(--muted);font-weight:600}
.idxlast{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.idxmove{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums}
.idxmove i{font-style:normal;font-size:10.5px;color:var(--muted);
  font-weight:400;margin-left:5px}
.idxspark{margin:6px 0 4px}
.idxspark .spark{height:34px}
.idxrow{display:flex;gap:12px;border-top:1px solid var(--line);padding-top:7px}
.idxrow span{display:flex;flex-direction:column;gap:1px}
.idxrow i{font-style:normal;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.idxrow b{font-size:12px;font-variant-numeric:tabular-nums;font-weight:600}

.mktblock{margin-top:26px;padding-top:6px}
.breadth{border:1px solid var(--line);border-radius:9px;padding:12px 14px;
  margin-bottom:14px}
.breadthlabel{display:block;font-size:11px;color:var(--muted);margin-bottom:8px}
.breadthbar{display:flex;height:10px;border-radius:5px;overflow:hidden;
  background:var(--tag)}
.breadthup{width:var(--w);background:var(--pos)}
.breadthdown{width:var(--w);background:var(--neg)}
.breadthnums{display:flex;gap:14px;margin-top:8px;font-size:12px;
  align-items:baseline;flex-wrap:wrap}
.breadthnums b{font-variant-numeric:tabular-nums}
.breadthnums i{font-style:normal;color:var(--muted);font-size:11px}

.moverpair{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.moverbox{border:1px solid var(--line);border-radius:9px;padding:11px 13px}
.moverhead{margin:0 0 8px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.05em;font-weight:700;color:var(--muted)}
.moverhead.pos{color:var(--pos)} .moverhead.neg{color:var(--neg)}
.moverrow{display:grid;grid-template-columns:1fr auto auto;gap:10px;
  align-items:baseline;padding:6px 0;border-bottom:1px solid var(--line)}
.moverrow:last-child{border-bottom:none}
.moversym{font-weight:600;font-size:13px;min-width:0}
.moversym i{font-style:normal;font-weight:400;color:var(--muted);
  font-size:11px;display:block}
.moverlast,.movermove{font-variant-numeric:tabular-nums;font-size:12.5px}
.movermove{font-weight:600;min-width:58px;text-align:right}

.sectors{border:1px solid var(--line);border-radius:9px;padding:11px 13px}
.secrow{display:grid;grid-template-columns:minmax(80px,1fr) 2fr auto auto;
  gap:10px;align-items:center;padding:5px 0;font-size:12.5px}
.secname{font-weight:600;text-transform:capitalize}
.sectrack{background:var(--tag);border-radius:3px;height:7px;overflow:hidden}
.secfill{display:block;height:100%;width:var(--w);border-radius:3px;
  background:var(--muted)}
.secfill.pos{background:var(--pos)} .secfill.neg{background:var(--neg)}
.secmove{font-variant-numeric:tabular-nums;font-weight:600;min-width:58px;
  text-align:right}
.seccount{font-size:11px;color:var(--muted);min-width:62px;text-align:right}

/* --- screener ------------------------------------------------------------- */
.screenlist{display:grid;gap:10px}
.screenrow{border:1px solid var(--line);border-radius:9px;padding:12px 14px;
  background:var(--panel);box-shadow:var(--elev-1)}
.screenhead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  margin-bottom:9px}
.screensym{font-weight:700;font-size:15px}
.screensig{margin-left:auto;font-size:11px;font-weight:700;padding:2px 9px;
  border-radius:999px;background:var(--tag);color:var(--muted)}
.screensig.bullish{background:color-mix(in srgb,var(--pos) 20%,var(--tag));
  color:var(--pos)}
.screensig.bearish{background:color-mix(in srgb,var(--neg) 20%,var(--tag));
  color:var(--neg)}
.screenmetrics{display:grid;gap:8px;
  grid-template-columns:repeat(auto-fit,minmax(84px,1fr));margin-bottom:9px}
.screenmetrics span{display:flex;flex-direction:column;gap:1px}
.screenmetrics i{font-style:normal;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.screenmetrics b{font-size:14px;font-variant-numeric:tabular-nums;
  text-transform:capitalize}
.screenwhy{margin:0;font-size:12.5px;color:var(--muted);line-height:1.55}
.screenind{margin:5px 0 0;font-size:11px;color:var(--muted);opacity:.8;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}

@media (max-width:640px){
  .idxgrid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
  .secrow{grid-template-columns:1fr auto auto}
  .sectrack{grid-column:1 / -1;order:4}
  .moverrow{grid-template-columns:1fr auto}
  .moverlast{display:none}
}

/* --- watchlist ------------------------------------------------------------ */
.wbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.wsearch{flex:1 1 240px;min-width:0}
.wsearch input{width:100%;font:inherit;font-size:15px;padding:9px 12px;
  border:1px solid var(--line);border-radius:8px;background:var(--bg);
  color:var(--ink)}
.wsearch input:focus{outline:2px solid var(--accent);outline-offset:1px}
.wfilters{display:flex;gap:6px;flex-wrap:wrap}
.wfilter{appearance:none;font:inherit;font-size:12px;font-weight:600;
  padding:7px 11px;border-radius:999px;border:1px solid var(--line);
  background:var(--panel);color:var(--muted);cursor:pointer;
  display:inline-flex;align-items:center;gap:6px}
.wfilter:hover{color:var(--ink)}
.wfilter[aria-pressed="true"]{color:var(--accent);border-color:var(--accent);
  background:color-mix(in srgb,var(--accent) 10%,var(--panel))}
.wcount{font-size:10.5px;opacity:.75;font-variant-numeric:tabular-nums}
.wtablewrap{overflow-x:auto}
.wtable{min-width:760px}
.wname{min-width:180px}
.wsym{font-weight:700;margin-right:6px}
.wtags{display:block;margin-top:3px}
.wspark{width:110px}
.wspark .spark{height:28px}
.wstatus{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;
  border-radius:999px;background:var(--tag);color:var(--muted)}
.wstatus.held{background:color-mix(in srgb,var(--accent) 18%,var(--tag));
  color:var(--accent)}
.wstatus.signal{background:color-mix(in srgb,var(--pos) 20%,var(--tag));
  color:var(--pos)}
.wstatus.resting{background:color-mix(in srgb,var(--ink) 8%,var(--tag))}
.wnote{display:block;font-size:10.5px;color:var(--muted);margin-top:3px}
.wempty{color:var(--muted);font-size:13px;margin:14px 0 0}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* --- news ----------------------------------------------------------------- */
.newsbar{display:flex;gap:14px;align-items:flex-start;justify-content:space-between;
  flex-wrap:wrap;margin-bottom:16px}
.newslede{margin:0;font-size:13px;color:var(--muted);max-width:62ch;line-height:1.6}
.newsbar button{flex:0 0 auto}
.newsgroup{margin-bottom:20px}
.newshead{margin:0 0 8px;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--accent);font-weight:700}
.newsitem{display:block;padding:10px 12px;border:1px solid var(--line);
  border-radius:8px;margin-bottom:7px;text-decoration:none;color:inherit;
  transition:border-color .16s var(--ease),transform .16s var(--ease)}
.newsitem:hover{border-color:var(--accent);transform:translateY(-1px)}
.newsitem:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.newstitle{display:block;font-size:13.5px;line-height:1.5;color:var(--ink)}
.newsmeta{display:block;font-size:11px;color:var(--muted);margin-top:4px}

/* --- allocation ----------------------------------------------------------- */
.allocsplit{display:grid;gap:9px;margin-bottom:16px;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.allocsplitrow{display:flex;flex-direction:column;gap:2px;padding:10px 12px;
  border:1px solid var(--line);border-radius:8px}
.allocsplitrow i{font-style:normal;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.allocsplitrow b{font-size:18px;font-variant-numeric:tabular-nums}
.allocsplitrow u{text-decoration:none;font-size:11px;color:var(--muted)}
.allocsplitrow.warn{border-color:var(--neg)}
.allocsplitrow.warn u{color:var(--neg)}
.allocsub{margin:14px 0 8px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted);font-weight:600}
.allocrow{display:grid;grid-template-columns:minmax(70px,1fr) 2fr auto auto;
  gap:10px;align-items:center;margin-bottom:6px;font-size:12.5px}
.alloclabel{font-weight:600}
.alloctrack{background:var(--tag);border-radius:3px;height:8px;overflow:hidden}
.allocfill{display:block;height:100%;background:var(--accent);border-radius:3px}
.allocpct,.allocval{font-variant-numeric:tabular-nums;color:var(--muted);
  font-size:11.5px;text-align:right}

@media (max-width:640px){
  .allocrow{grid-template-columns:1fr auto;gap:4px 10px}
  .alloctrack{grid-column:1 / -1;order:3}
  .newsbar button{width:100%}
}
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


def _pct_move(value: object) -> str:
    """A percentage move with its sign, or an em dash when unknown."""
    if value in (None, ""):
        return "&mdash;"
    return f"{float(str(value)) * 100:+.2f}%"


def _move_tone(value: object) -> str:
    if value in (None, ""):
        return "flat"
    number = float(str(value))
    return "pos" if number > 0 else ("neg" if number < 0 else "flat")


WATCH_STATUS = {
    "held": ("held", "In the book"),
    "signal": ("signal", "Suggested today"),
    "resting": ("resting", "Order resting"),
    "watching": ("watching", "Watching"),
}


def _watchlist_section(signals: dict) -> str:
    """Every name the strategies read, priced, with why it is or is not acting.

    The point of showing the whole list is that it makes the quiet days
    legible: you can see the strategies looked at all of these and chose
    nothing, which is a different statement from the app having no opinion.
    """
    # A snapshot written before the watchlist carried prices still renders the
    # rest of the page; this panel just says it has nothing to show rather
    # than taking the document down with it.
    rows = [
        row for row in (signals.get("watchlist") or [])
        if row.get("last") not in (None, "")
    ]
    if not rows:
        return ('<p class="empty">Prices for the watchlist are not in this '
                "build's data. They arrive with the next refresh after the "
                "market close.</p>")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("status", "watching")] = (
            counts.get(row.get("status", "watching"), 0) + 1
        )
    chips = "".join(
        f'<button type="button" class="wfilter" data-wfilter="{key}" '
        f'aria-pressed="false">{label}<span class="wcount">{counts.get(key, 0)}</span>'
        "</button>"
        for key, (_cls, label) in WATCH_STATUS.items()
        if counts.get(key)
    )

    body = ""
    for row in rows:
        cls, label = WATCH_STATUS.get(
            row.get("status", "watching"), ("watching", "Watching")
        )
        region = row.get("region", "")
        region_label = REGION_NAMES.get(
            "IN" if region == "india" else "US", region
        )
        spark = sparkline_svg(row.get("spark") or [], width=110, height=28)
        search_terms = _esc(
            " ".join(str(row.get(f, "")) for f in ("symbol", "name", "sector")).lower()
        )
        body += f"""<tr class="openable" data-wrow data-wstatus="{cls}"
    data-stock="{_esc(row.get('key', ''))}" tabindex="0" role="button"
    aria-label="Open {_esc(row.get('symbol', ''))} detail"
    data-wsearch="{search_terms}">
  <td class="wname">
    <span class="wsym">{_esc(row['symbol'])}</span>
    <span class="muted-inline">{_esc(row['name'])}</span>
    <span class="wtags"><span class="tag">{_esc(region_label)}</span>
      <span class="tag">{_esc(row.get('sector', ''))}</span></span>
  </td>
  <td class="wspark">{spark}</td>
  <td class="num">{_price(row['last'])}
    <span class="ccy">{_esc(row.get('currency', ''))}</span></td>
  <td class="num {_move_tone(row.get('change_1d'))}">{_pct_move(row.get('change_1d'))}</td>
  <td class="num {_move_tone(row.get('change_1w'))}">{_pct_move(row.get('change_1w'))}</td>
  <td class="num {_move_tone(row.get('change_1m'))}">{_pct_move(row.get('change_1m'))}</td>
  <td class="num {_move_tone(row.get('change_3m'))}">{_pct_move(row.get('change_3m'))}</td>
  <td><span class="wstatus {cls}">{_esc(label)}</span>
    <span class="wnote">{_esc(row.get('status_note', ''))}</span></td>
</tr>"""

    return f"""<div class="wbar">
  <label class="wsearch">
    <span class="sr-only">Filter the watchlist</span>
    <input type="search" data-wsearch-input placeholder="Filter by name, symbol or sector">
  </label>
  <div class="wfilters">{chips}
    <button type="button" class="wfilter" data-wfilter="all" aria-pressed="true">All
      <span class="wcount">{len(rows)}</span></button>
  </div>
</div>
<div class="wtablewrap"><table class="wtable">
  <thead><tr><th>Instrument</th><th>60 sessions</th><th class="num">Last close</th>
  <th class="num">1 day</th><th class="num">1 week</th><th class="num">1 month</th>
  <th class="num">3 months</th><th>Status</th></tr></thead>
  <tbody>{body}</tbody>
</table></div>
<p class="wempty" data-wempty hidden>Nothing on the watchlist matches that.</p>
<p class="caption">Sorted by today's move, biggest first. Changes are measured
between closing prices, so a name that has not traded for a session shows the
same figure until it does. Being on this list is not a recommendation &mdash;
most of it is here precisely so the strategies can rule it out.</p>"""


def _news_section(signals: dict) -> str:
    """Headlines for the names actually in play, fetched in the browser.

    Rendered empty and filled by script: headlines change through the day and
    the page is rebuilt only after each close, so baking them in would ship
    stale news with a fresh timestamp on it.
    """
    return """<div class="newsbar">
  <p class="newslede">Headlines for the names you hold, the ones suggested
  today, and the two market indices. Fetched when you open this tab, straight
  from the publisher's own feed.</p>
  <button type="button" class="exec" data-news-refresh>Refresh</button>
</div>
<div data-news-list>
  <p class="empty" data-news-empty>Loading headlines&hellip;</p>
</div>
<p class="caption">Coverage is uneven &mdash; large US listings carry plenty,
and many Indian ones carry none at all. A name with nothing is shown as having
nothing rather than being padded with something less relevant. Headlines link
to the publisher; nothing is summarised or rewritten here, and opening one
tells this page nothing.</p>"""


BENCHMARK_GROUP_LABELS = (
    ("india", "India"),
    ("us", "United States"),
    ("commodity", "Commodities"),
    ("currency", "Currencies"),
)


def _market_section(signals: dict) -> str:
    """Indices, movers, breadth and sectors — the state of the market itself.

    Breadth leads each market rather than the index level, because an index up
    on four names is a different market from an index up on thirty and only the
    advance/decline split tells them apart. Everything is computed from the
    same cached closes the strategies read, so this page and the signals can
    never disagree about what a price did.
    """
    market = signals.get("market") or {}
    benchmarks = market.get("benchmarks") or []
    regions = market.get("regions") or {}
    if not benchmarks and not regions:
        return ('<p class="empty">Market data is not in this build. It arrives '
                "with the next refresh after the close.</p>")

    # --- indices, commodities, currencies, grouped by where they trade ---
    groups = ""
    for key, label in BENCHMARK_GROUP_LABELS:
        rows = [b for b in benchmarks if b.get("group") == key]
        if not rows:
            continue
        cards = ""
        for row in rows:
            tone = _move_tone(row.get("change_1d"))
            spark = sparkline_svg(row.get("spark") or [], width=150, height=34)
            cards += f"""<div class="idxcard openable" data-stock="{
                _esc(row.get('key', ''))}" role="button" tabindex="0"
     aria-label="Open {_esc(row['label'])} detail">
  <span class="idxname">{_esc(row['label'])}</span>
  <span class="idxlast">{_price(row['last'])}</span>
  <span class="idxmove {tone}">{_pct_move(row.get('change_1d'))}<i>today</i></span>
  <div class="idxspark">{spark}</div>
  <div class="idxrow">
    <span><i>1w</i><b class="{_move_tone(row.get('change_1w'))}">{
      _pct_move(row.get('change_1w'))}</b></span>
    <span><i>1m</i><b class="{_move_tone(row.get('change_1m'))}">{
      _pct_move(row.get('change_1m'))}</b></span>
    <span><i>1y</i><b class="{_move_tone(row.get('change_1y'))}">{
      _pct_move(row.get('change_1y'))}</b></span>
  </div>
</div>"""
        groups += f'<h3 class="mktgroup">{_esc(label)}</h3><div class="idxgrid">{cards}</div>'

    # --- per-market breadth, movers and sectors ---
    blocks = ""
    for region, label in (("india", "India"), ("us", "United States")):
        data = regions.get(region)
        if not data:
            continue
        breadth = data["breadth"]
        total = max(breadth["total"], 1)
        up_pct = breadth["advancing"] / total * 100
        down_pct = breadth["declining"] / total * 100

        def movers(rows, kind):
            if not rows:
                return '<p class="empty">Nothing to show.</p>'
            out = ""
            for row in rows:
                out += f"""<div class="moverrow">
  <span class="moversym">{_esc(row['symbol'])}
    <i>{_esc(row['name'])}</i></span>
  <span class="moverlast">{_price(row['last'])}
    <span class="ccy">{_esc(row.get('currency', ''))}</span></span>
  <span class="movermove {_move_tone(row.get('change_1d'))}">{
    _pct_move(row.get('change_1d'))}</span>
</div>"""
            return out

        sector_rows = "".join(
            f"""<div class="secrow">
  <span class="secname">{_esc(s['sector'])}</span>
  <span class="sectrack"><span class="secfill {_move_tone(s['change'])}"
    style="--w:{min(abs(float(s['change'])) * 100 * 12, 100):.1f}%"></span></span>
  <span class="secmove {_move_tone(s['change'])}">{_pct_move(s['change'])}</span>
  <span class="seccount">{s['advancing']}/{s['count']} up</span>
</div>"""
            for s in data["sectors"]
        )

        blocks += f"""<div class="mktblock">
  <h3 class="mktgroup">{_esc(label)}</h3>
  <div class="breadth">
    <span class="breadthlabel">Breadth &mdash; how many names moved which way</span>
    <span class="breadthbar">
      <span class="breadthup" style="--w:{up_pct:.1f}%"></span>
      <span class="breadthdown" style="--w:{down_pct:.1f}%"></span>
    </span>
    <span class="breadthnums">
      <b class="pos">{breadth['advancing']} up</b>
      <b class="neg">{breadth['declining']} down</b>
      <b class="flat">{breadth['unchanged']} flat</b>
      <i>of {breadth['total']} tracked</i>
    </span>
  </div>
  <div class="moverpair">
    <div class="moverbox">
      <h4 class="moverhead pos">Top gainers</h4>{movers(data['gainers'], 'up')}</div>
    <div class="moverbox">
      <h4 class="moverhead neg">Top losers</h4>{movers(data['losers'], 'down')}</div>
  </div>
  <h4 class="moverhead">Sectors</h4>
  <div class="sectors">{sector_rows}</div>
</div>"""

    return f"""{groups}{blocks}
<p class="caption">Levels are the last completed close for each market, so an
index still trading shows yesterday's figure until it settles. Breadth and
sector moves are measured across the {len(signals.get('watchlist') or [])} names
this app tracks &mdash; not the whole exchange, so treat them as the mood of
this list rather than of the entire market.</p>"""


SCREEN_SIGNALS = (
    ("bullish", "Bullish"),
    ("bearish", "Bearish"),
    ("neutral", "Neutral"),
)


def _screener_section(screener: dict | None) -> str:
    """The whole universe ranked by the screener, with its reasoning shown.

    A score with no rationale is an oracle, and an oracle is not something a
    reader can disagree with. Every row carries the indicators that drove it
    and the sentence the screener wrote for itself, so a ranking can be argued
    with rather than merely accepted.
    """
    rows = (screener or {}).get("results") or []
    if not rows:
        return ('<p class="empty">The screener has not run for this build. It '
                "runs on every data refresh, after each market close.</p>")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("signal", "neutral")] = counts.get(row.get("signal", "neutral"), 0) + 1
    chips = "".join(
        f'<button type="button" class="wfilter" data-sfilter="{key}" '
        f'aria-pressed="false">{label}<span class="wcount">{counts.get(key, 0)}</span>'
        "</button>"
        for key, label in SCREEN_SIGNALS
        if counts.get(key)
    )

    body = ""
    for row in rows:
        signal = row.get("signal", "neutral")
        reading = row.get("reading") or {}
        strength = float(row.get("signal_strength") or 0)
        score = float(row.get("score") or 0)
        indicators = ", ".join(row.get("indicators_used") or []) or "&mdash;"
        region_label = REGION_NAMES.get(
            "IN" if row.get("region") == "india" else "US", row.get("region", "")
        )
        body += f"""<article class="screenrow openable" data-srow
    data-stock="{_esc(row.get('key', ''))}" tabindex="0" role="button"
    aria-label="Open {_esc(row.get('symbol', ''))} detail"
    data-ssignal="{_esc(signal)}"
    data-ssearch="{_esc((str(row.get('symbol', '')) + ' ' + str(row.get('name', ''))
                        + ' ' + str(row.get('sector', ''))).lower())}">
  <div class="screenhead">
    <span class="screensym">{_esc(row.get('symbol', ''))}</span>
    <span class="muted-inline">{_esc(row.get('name', ''))}</span>
    <span class="tag">{_esc(region_label)}</span>
    <span class="tag">{_esc(row.get('sector', ''))}</span>
    <span class="screensig {_esc(signal)}">{_esc(signal.title())}</span>
  </div>
  <div class="screenmetrics">
    <span><i>Score</i><b>{score:.2f}</b></span>
    <span><i>Conviction</i><b>{strength * 100:.0f}%</b></span>
    <span><i>Regime</i><b>{_esc(row.get('regime', '&mdash;'))}</b></span>
    <span><i>Volatility</i><b>{_esc(row.get('volatility_bucket', '&mdash;'))}</b></span>
    <span><i>Price</i><b>{_price(reading.get('price')) if reading.get('price')
      else '&mdash;'}</b></span>
    <span><i>RSI</i><b>{f"{float(reading['rsi']):.0f}" if reading.get('rsi')
      else '&mdash;'}</b></span>
  </div>
  <p class="screenwhy">{_esc(row.get('rationale', ''))}</p>
  <p class="screenind">Indicators weighted: {_esc(indicators)}</p>
</article>"""

    return f"""<div class="wbar">
  <label class="wsearch">
    <span class="sr-only">Filter the screener</span>
    <input type="search" data-ssearch-input
           placeholder="Filter by name, symbol or sector">
  </label>
  <div class="wfilters">{chips}
    <button type="button" class="wfilter" data-sfilter="all" aria-pressed="true">All
      <span class="wcount">{len(rows)}</span></button>
  </div>
</div>
<div class="screenlist">{body}</div>
<p class="wempty" data-sempty hidden>Nothing matches that.</p>
<p class="caption">Ranked highest score first. The screener weights its
indicators by the regime it detects &mdash; trend-following ones when a name is
trending, oscillators when it is ranging &mdash; and says which it used on every
row. A high score is a description of what the price has done, not a forecast of
what it will do, and the screener does not size or place anything: only the
strategies on <button type="button" class="linkish" data-tabgo="invest">Invest
Now</button> do that.</p>"""


def _stock_index(signals: dict, screener: dict | None) -> dict:
    """One record per instrument, merging what the watchlist and screener know.

    The detail view is built from this in the browser rather than as 34
    server-rendered panels: duplicating the markup would triple the page for
    content almost nobody opens more than one of.
    """
    merged: dict[str, dict] = {}
    for row in signals.get("watchlist") or []:
        if row.get("last") in (None, ""):
            continue
        merged[row["key"]] = {
            "key": row["key"],
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "region": row.get("region"),
            "sector": row.get("sector"),
            "currency": row.get("currency"),
            "exchange": row.get("exchange"),
            "yahoo": row.get("yahoo"),
            "last": row.get("last"),
            "change_1d": row.get("change_1d"),
            "change_1w": row.get("change_1w"),
            "change_1m": row.get("change_1m"),
            "change_3m": row.get("change_3m"),
            "high_52w": row.get("high_52w"),
            "low_52w": row.get("low_52w"),
            "off_high": row.get("off_high"),
            "off_low": row.get("off_low"),
            "range_position": row.get("range_position"),
            "avg_volume": row.get("avg_volume"),
            "status": row.get("status"),
            "status_note": row.get("status_note"),
            "sessions": row.get("sessions"),
            "spark": row.get("spark") or [],
            # Full series so the detail chart can offer real range filters
            # rather than redrawing the same 60 sessions at every setting.
            "history": row.get("history") or {},
        }

    for row in (screener or {}).get("results") or []:
        record = merged.get(row.get("key"))
        if record is None:
            continue
        record["screen"] = {
            "score": row.get("score"),
            "signal": row.get("signal"),
            "strength": row.get("signal_strength"),
            "regime": row.get("regime"),
            "volatility_bucket": row.get("volatility_bucket"),
            "indicators": row.get("indicators_used") or [],
            "rationale": row.get("rationale"),
            "relative_momentum": row.get("relative_momentum_long"),
            "sector_momentum": row.get("sector_momentum_long"),
            "reading": row.get("reading") or {},
        }

    # Anything the strategies are actually acting on, so the detail view can
    # show the live levels rather than only the screener's opinion.
    # Indices, commodities and currencies open the same detail view. They are
    # marked so it can skip the sections that make no sense for them: an index
    # has no dividend, no filing and no screener verdict.
    for bench in (signals.get("market") or {}).get("benchmarks") or []:
        merged[bench["key"]] = {
            "key": bench["key"],
            "symbol": bench["label"],
            "name": {"index": "Index", "commodity": "Commodity",
                     "currency": "Exchange rate",
                     "volatility": "Volatility index"}.get(bench.get("kind"), ""),
            "region": bench.get("group"),
            "sector": bench.get("kind"),
            "currency": bench.get("currency"),
            "exchange": "",
            "yahoo": bench["yahoo"],
            "last": bench.get("last"),
            "change_1d": bench.get("change_1d"),
            "change_1w": bench.get("change_1w"),
            "change_1m": bench.get("change_1m"),
            "change_3m": bench.get("change_1m"),
            "spark": bench.get("spark") or [],
            "history": bench.get("history") or {},
            "sessions": len((bench.get("history") or {}).get("c") or []),
            "is_benchmark": True,
        }

    funds = signals.get("fundamentals") or {}
    for key, record in (funds.get("companies") or {}).items():
        target = merged.get(key)
        if target is not None:
            target["fundamentals"] = record
    for key, reason in (funds.get("unavailable") or {}).items():
        target = merged.get(key)
        if target is not None and "fundamentals" not in target:
            target["no_fundamentals"] = reason

    for key, actions in (signals.get("corporate_actions") or {}).items():
        target = merged.get(key)
        if target is not None:
            target["actions"] = actions

    for order in signals.get("orders") or []:
        record = merged.get(order.get("key"))
        if record is not None:
            record["order"] = {
                "side": order.get("side"), "quantity": order.get("quantity"),
                "stop_loss": order.get("stop_loss"),
                "take_profit": order.get("take_profit"),
                "reason": plain_reason(order.get("reason") or ""),
                "fresh": order.get("fresh"),
            }
    for position in signals.get("positions") or []:
        record = merged.get(position.get("key"))
        if record is not None:
            record["position"] = {
                "quantity": position.get("quantity"),
                "average_cost": position.get("average_cost"),
                "stop": position.get("stop"),
                "take_profit": position.get("take_profit"),
                "days_held": position.get("days_held"),
                "max_holding_days": position.get("max_holding_days"),
            }
    return merged


def _detail_shell() -> str:
    """The detail view's frame. Script fills it for whichever stock is open."""
    return """<section class="detail" data-detail hidden aria-live="polite">
  <button type="button" class="detailback" data-detail-back>
    &larr; Back to the list</button>
  <div data-detail-body></div>
</section>"""


def _funds_section(funds: dict | None) -> str:
    """Mutual fund NAVs, searched in the browser against a fetched index.

    Fourteen thousand schemes cannot be rendered as rows, and paging them
    server-side would mean a round trip per keystroke on a static host. The
    index is fetched once when the tab is opened and searched locally.
    """
    if not funds:
        return ('<p class="empty">Fund NAVs are not in this build. They refresh '
                "daily with the rest of the data.</p>")
    count = funds.get("count", 0)
    as_of = funds.get("as_of", "")
    houses = funds.get("houses") or []
    categories = funds.get("categories") or []
    chips = "".join(
        f'<button type="button" class="wfilter" data-fcat="{_esc(name)}" '
        f'aria-pressed="false">{_esc(name)}<span class="wcount">{n}</span></button>'
        for name, n in categories[:8]
    )
    return f"""<div class="fundsbar">
  <label class="wsearch">
    <span class="sr-only">Search mutual funds</span>
    <input type="search" data-fsearch placeholder="Search {count:,} schemes by name or fund house">
  </label>
  <div class="wfilters">{chips}
    <button type="button" class="wfilter" data-fcat="all" aria-pressed="true">All
      <span class="wcount">{count:,}</span></button>
  </div>
</div>
<p class="sigmeta">{count:,} schemes from {len(houses)} fund houses &middot;
NAVs as of {_esc(as_of)}</p>
<div data-funds-results><p class="empty" data-funds-hint>Type at least two
characters to search, or pick a category.</p></div>
<p class="caption">Published by AMFI, the association every Indian asset manager
reports to, once a day after valuation. A fund has no intraday price &mdash; any
site showing one is showing an estimate. Direct plans carry lower charges than
regular ones for the same portfolio, which is why the same fund appears twice.
Nothing here is a recommendation, and past NAV growth is not a forecast.</p>"""


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
<h3 class="papersub">Where your money is</h3>
<div class="allocwrap">
  <div data-paper-alloc></div>
  <p class="caption" data-alloc-note>Allocation appears once you hold something.
  Concentration is the risk that does not show up in a profit figure until it
  matters, so it is worth a look before the next buy rather than after.</p>
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

    // --- allocation ---------------------------------------------------
    // Concentration is the risk a profit figure hides, so it gets its own
    // view: how much is working, and how much of that sits in one name.
    var allocEl = document.querySelector('[data-paper-alloc]');
    if (allocEl) {
      if (!keys.length) {
        allocEl.innerHTML = '';
      } else {
        var invested = marketValue;
        var byName = keys.map(function (k) {
          var p = state.positions[k];
          var price = Number(livePrice(p.yahoo) || p.cost);
          return {label: p.symbol, value: toUsd(price * p.qty, p.currency),
                  region: p.region};
        }).sort(function (a, b) { return b.value - a.value; });

        var byRegion = {};
        byName.forEach(function (row) {
          byRegion[row.region] = (byRegion[row.region] || 0) + row.value;
        });

        function bars(items, total) {
          return items.map(function (row) {
            var share = total > 0 ? row.value / total * 100 : 0;
            return '<div class="allocrow">' +
              '<span class="alloclabel">' + esc(row.label) + '</span>' +
              '<span class="alloctrack"><span class="allocfill" style="width:' +
                share.toFixed(1) + '%"></span></span>' +
              '<span class="allocpct">' + share.toFixed(1) + '%</span>' +
              '<span class="allocval">' + money(row.value) + ' USD</span>' +
            '</div>';
          }).join('');
        }

        var cashShare = (cashUsd + invested) > 0
          ? cashUsd / (cashUsd + invested) * 100 : 0;
        var top = byName[0];
        var topShare = invested > 0 ? top.value / invested * 100 : 0;

        allocEl.innerHTML =
          '<div class="allocsplit">' +
            '<span class="allocsplitrow"><i>Invested</i>' +
              '<b>' + money(invested) + ' USD</b>' +
              '<u>' + (100 - cashShare).toFixed(1) + '% of the book</u></span>' +
            '<span class="allocsplitrow"><i>Still in cash</i>' +
              '<b>' + money(cashUsd) + ' USD</b>' +
              '<u>' + cashShare.toFixed(1) + '% of the book</u></span>' +
            '<span class="allocsplitrow' + (topShare >= 40 ? ' warn' : '') + '">' +
              '<i>Largest single holding</i><b>' + esc(top.label) + '</b>' +
              '<u>' + topShare.toFixed(1) + '% of what is invested' +
              (topShare >= 40 ? ' \u2014 concentrated' : '') + '</u></span>' +
          '</div>' +
          '<h4 class="allocsub">By holding</h4>' + bars(byName, invested) +
          '<h4 class="allocsub">By market</h4>' +
          bars(Object.keys(byRegion).map(function (r) {
            return {label: r === 'india' ? 'India' : 'United States',
                    value: byRegion[r]};
          }).sort(function (a, b) { return b.value - a.value; }), invested);
      }
      var note = document.querySelector('[data-alloc-note]');
      if (note) note.hidden = keys.length > 0;
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



#: Watchlist filtering and the headline loader.
#:
#: Headlines are third-party text, so every one of them is written with
#: textContent and every link with a literal href from the feed — nothing from
#: the network is ever interpolated into markup. Links carry rel="noopener
#: noreferrer" so the opened page cannot reach back into this one, and the
#: fetch is deferred until the tab is actually opened rather than fired on
#: load for a panel most readers never visit.
WATCH_NEWS_JS = """
(function () {
  // --- watchlist filtering -------------------------------------------------
  var rows = [].slice.call(document.querySelectorAll('[data-wrow]'));
  var search = document.querySelector('[data-wsearch-input]');
  var chips = [].slice.call(document.querySelectorAll('[data-wfilter]'));
  var empty = document.querySelector('[data-wempty]');
  var active = 'all';

  function applyFilter() {
    var term = (search && search.value || '').trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (row) {
      var okStatus = active === 'all' || row.getAttribute('data-wstatus') === active;
      var okTerm = !term || row.getAttribute('data-wsearch').indexOf(term) >= 0;
      var show = okStatus && okTerm;
      row.hidden = !show;
      if (show) shown++;
    });
    if (empty) empty.hidden = shown > 0;
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      active = chip.getAttribute('data-wfilter');
      chips.forEach(function (other) {
        other.setAttribute('aria-pressed', other === chip ? 'true' : 'false');
      });
      applyFilter();
    });
  });
  if (search) search.addEventListener('input', applyFilter);

  // --- screener filtering --------------------------------------------------
  var srows = [].slice.call(document.querySelectorAll('[data-srow]'));
  var ssearch = document.querySelector('[data-ssearch-input]');
  var schips = [].slice.call(document.querySelectorAll('[data-sfilter]'));
  var sempty = document.querySelector('[data-sempty]');
  var sactive = 'all';

  function applyScreen() {
    var term = (ssearch && ssearch.value || '').trim().toLowerCase();
    var shown = 0;
    srows.forEach(function (row) {
      var okSignal = sactive === 'all' || row.getAttribute('data-ssignal') === sactive;
      var okTerm = !term || row.getAttribute('data-ssearch').indexOf(term) >= 0;
      var show = okSignal && okTerm;
      row.hidden = !show;
      if (show) shown++;
    });
    if (sempty) sempty.hidden = shown > 0;
  }

  schips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      sactive = chip.getAttribute('data-sfilter');
      schips.forEach(function (other) {
        other.setAttribute('aria-pressed', other === chip ? 'true' : 'false');
      });
      applyScreen();
    });
  });
  if (ssearch) ssearch.addEventListener('input', applyScreen);

  // --- headlines -----------------------------------------------------------
  var cfg = window.__mpCfg;
  var list = document.querySelector('[data-news-list]');
  if (!list || typeof fetch !== 'function') return;
  var API = (cfg && cfg.api_base) || '/markets-pro/api';
  var loaded = false, loading = false;

  function subjects() {
    // Indices first so there is always something, then whatever is in play.
    var out = ['^NSEI', '^GSPC'];
    var seen = {};
    ((cfg && cfg.orders) || []).forEach(function (order) {
      if (order.yahoo && !seen[order.yahoo]) { seen[order.yahoo] = 1; out.push(order.yahoo); }
    });
    try {
      var paper = JSON.parse(localStorage.getItem('markets-pro.paper.v1'));
      Object.keys((paper && paper.positions) || {}).forEach(function (key) {
        var pos = paper.positions[key];
        if (pos.yahoo && !seen[pos.yahoo]) { seen[pos.yahoo] = 1; out.push(pos.yahoo); }
      });
    } catch (e) { /* no paper book yet */ }
    return out.slice(0, 8);
  }

  function when(iso) {
    if (!iso) return '';
    var then = new Date(iso), mins = Math.round((Date.now() - then) / 60000);
    if (!isFinite(mins)) return '';
    if (mins < 60) return mins <= 1 ? 'just now' : mins + ' minutes ago';
    var hours = Math.round(mins / 60);
    if (hours < 24) return hours === 1 ? 'an hour ago' : hours + ' hours ago';
    var days = Math.round(hours / 24);
    return days === 1 ? 'yesterday' : days + ' days ago';
  }

  var LABELS = {'^NSEI': 'Nifty 50', '^GSPC': 'S&P 500'};

  function render(payload) {
    list.textContent = '';
    var any = false;
    subjects().forEach(function (symbol) {
      var stories = (payload.news || {})[symbol] || [];
      if (!stories.length) return;
      any = true;
      var group = document.createElement('section');
      group.className = 'newsgroup';

      var head = document.createElement('h3');
      head.className = 'newshead';
      head.textContent = LABELS[symbol] || symbol.replace(/\\.NS$/, '');
      group.appendChild(head);

      stories.forEach(function (story) {
        var item = document.createElement('a');
        item.className = 'newsitem';
        item.href = story.link;                    // literal, never interpolated
        item.target = '_blank';
        item.rel = 'noopener noreferrer';

        var title = document.createElement('span');
        title.className = 'newstitle';
        title.textContent = story.title;           // third-party text stays text
        item.appendChild(title);

        var meta = document.createElement('span');
        meta.className = 'newsmeta';
        meta.textContent = [story.source, when(story.published)]
          .filter(Boolean).join(' \u00b7 ');
        item.appendChild(meta);

        group.appendChild(item);
      });
      list.appendChild(group);
    });

    if (!any) {
      var none = document.createElement('p');
      none.className = 'empty';
      none.textContent = 'No headlines available for these names right now. '
        + 'Coverage is thin for many Indian listings.';
      list.appendChild(none);
    }
  }

  function load(force) {
    if (loading || (loaded && !force)) return;
    loading = true;
    list.textContent = '';
    var wait = document.createElement('p');
    wait.className = 'empty';
    wait.textContent = 'Loading headlines\u2026';
    list.appendChild(wait);

    fetch(API + '/news?symbols=' + encodeURIComponent(subjects().join(',')))
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (body) {
        loading = false;
        if (!body) throw new Error('unavailable');
        loaded = true;
        render(body);
      })
      .catch(function () {
        loading = false;
        list.textContent = '';
        var failed = document.createElement('p');
        failed.className = 'empty';
        failed.textContent = 'Headlines could not be reached just now.';
        list.appendChild(failed);
      });
  }

  var refresh = document.querySelector('[data-news-refresh]');
  if (refresh) refresh.addEventListener('click', function () { load(true); });

  // Only fetch when the tab is actually opened.
  var newsTab = document.querySelector('[data-tabbtn="news"]');
  if (newsTab) newsTab.addEventListener('click', function () { load(false); });
  if (location.hash === '#news') load(false);
  window.addEventListener('hashchange', function () {
    if (location.hash === '#news') load(false);
  });
})();
"""


#: Stock detail views.
#:
#: Rendered in the browser from one embedded index rather than as 34
#: server-rendered panels — the markup would be near-identical and almost
#: nobody opens more than one. Routed on the hash (``#stock/US:XOM``) so a
#: detail view is linkable and the back button behaves.
#:
#: Every technical reading is paired with what it means in words. A number like
#: "RSI 71" tells a reader who already knows nothing they did not know; the
#: point of a detail page is to be readable by someone who does not.
DETAIL_JS = """
(function () {
  var blob = document.getElementById('stocks-data');
  var host = document.querySelector('[data-detail]');
  if (!blob || !host) return;
  var STOCKS = null, loading = null;
  var cfgEarly = window.__mpCfg || {};
  var base = cfgEarly.data_base || '/markets-pro/';
  var rawSrc = blob.getAttribute('data-src');
  var src = rawSrc ? base + rawSrc : null;
  if (!src) {
    try { STOCKS = JSON.parse(blob.textContent); } catch (e) { return; }
  }

  function stocks() {
    if (STOCKS) return Promise.resolve(STOCKS);
    if (loading) return loading;
    loading = fetch(src)
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { STOCKS = data; return STOCKS; })
      .catch(function () { STOCKS = {}; return STOCKS; });
    return loading;
  }

  var body = host.querySelector('[data-detail-body]');
  var back = host.querySelector('[data-detail-back]');
  var lastTab = 'screener';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
    });
  }
  function num(v, dp) {
    if (v == null || v === '') return '—';
    return Number(v).toLocaleString('en-US',
      {minimumFractionDigits: dp == null ? 2 : dp, maximumFractionDigits: dp == null ? 2 : dp});
  }
  function pct(v, dp) {
    if (v == null || v === '') return '—';
    var n = Number(v) * 100;
    return (n >= 0 ? '+' : '') + n.toFixed(dp == null ? 2 : dp) + '%';
  }
  function tone(v) {
    if (v == null || v === '') return 'flat';
    return Number(v) > 0 ? 'pos' : (Number(v) < 0 ? 'neg' : 'flat');
  }

  // Plain-language readings. Thresholds match the strategies' own config so
  // the words cannot contradict the rules on the Invest tab.
  function readRSI(v) {
    if (v == null) return null;
    if (v >= 70) return ['Overbought', 'has run hard and often pauses or pulls back from here'];
    if (v <= 30) return ['Oversold', 'has fallen hard — the dip strategy looks for entries here'];
    if (v >= 55) return ['Firm', 'buyers have had the upper hand recently'];
    if (v <= 45) return ['Soft', 'sellers have had the upper hand recently'];
    return ['Balanced', 'neither side is in control'];
  }
  function readADX(v) {
    if (v == null) return null;
    if (v >= 25) return ['Trending',
      'the move has real direction, so trend rules carry the weight'];
    if (v >= 20) return ['Firming', 'a trend may be forming but is not established'];
    return ['Ranging', 'no clear direction — oscillators carry the weight instead'];
  }
  function readST(v) {
    if (v == null) return null;
    return Number(v) > 0
      ? ['Bullish', 'price is above the supertrend line']
      : ['Bearish', 'price is below the supertrend line'];
  }
  function readMACD(v) {
    if (v == null) return null;
    return Number(v) > 0
      ? ['Positive', 'short-term momentum is above the longer trend']
      : ['Negative', 'short-term momentum has fallen below the longer trend'];
  }

  function readBollinger(v) {
    if (v == null) return null;
    var pctb = Number(v);
    if (pctb >= 1) return ['Above the band', 'stretched above its normal range'];
    if (pctb >= 0.8) return ['Upper band', 'near the top of its normal range'];
    if (pctb <= 0) return ['Below the band', 'stretched below its normal range'];
    if (pctb <= 0.2) return ['Lower band', 'near the bottom of its normal range'];
    return ['Mid-band', 'inside its normal range'];
  }

  function techRow(label, value, read) {
    if (!read) return '';
    return '<div class="techrow"><span class="techlabel">' + esc(label) + '</span>' +
      '<span class="techval">' + esc(value) + '</span>' +
      '<span class="techword">' + esc(read[0]) + '</span>' +
      '<span class="techsay">' + esc(read[1]) + '</span></div>';
  }


  function money(v) {
    if (v == null || v === '') return '—';
    var n = Number(v), sign = n < 0 ? '−' : '';
    n = Math.abs(n);
    if (n >= 1e12) return sign + (n / 1e12).toFixed(2) + 'T';
    if (n >= 1e9) return sign + (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return sign + (n / 1e6).toFixed(1) + 'M';
    return sign + n.toLocaleString('en-US', {maximumFractionDigits: 0});
  }

  // Filed fundamentals. Present only where a filing exists, and where it does
  // not the page says why rather than showing a row of dashes.

  // Dividends and splits. A trailing yield is shown only when the company
  // actually paid inside the last year — projecting one from an older payment
  // would flatter anything that has since cut.
  function actions(stock) {
    var a = stock.actions;
    if (!a || (!(a.dividends || []).length && !(a.splits || []).length)) {
      return '<h3 class="detailsub">Dividends</h3>' +
        '<p class="empty">No dividend or split recorded in the last five years.</p>';
    }
    var html = '<h3 class="detailsub">Dividends and splits</h3>';
    html += '<div class="detailgrid">' +
      '<span class="dstat"><i>Trailing yield</i><b>' +
        (a['yield'] ? pct(a['yield'], 2) : '—') + '</b><u>' +
        (a.ttm_count ? a.ttm_count + ' payment' + (a.ttm_count === 1 ? '' : 's') +
         ' in 12 months' : 'nothing paid in 12 months') + '</u></span>' +
      '<span class="dstat"><i>Paid (12 months)</i><b>' +
        (a.ttm_paid ? num(a.ttm_paid) : '—') + '</b><u>' +
        esc(stock.currency || '') + ' per share</u></span>' +
      '<span class="dstat"><i>Splits (5 years)</i><b>' +
        ((a.splits || []).length || '0') + '</b></span>' +
    '</div>';

    if ((a.dividends || []).length) {
      html += '<div class="fundwrap"><table class="fundtable"><thead><tr>' +
        '<th>Ex-date</th><th class="num">Amount</th></tr></thead><tbody>' +
        a.dividends.map(function (d) {
          return '<tr><td>' + esc(d.date) + '</td><td class="num">' +
            num(d.amount) + ' <span class="ccy">' + esc(stock.currency || '') +
            '</span></td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    if ((a.splits || []).length) {
      html += '<p class="caption">Splits: ' + a.splits.map(function (s) {
        return esc(s.ratio) + ' on ' + esc(s.date);
      }).join(', ') + '. Prices before a split are adjusted for it, so the ' +
      'chart above shows a continuous series rather than a cliff.</p>';
    }
    return html;
  }

  function fundamentals(stock) {
    if (!stock.fundamentals) {
      var why = stock.no_fundamentals || 'No filings source covers this listing.';
      return '<h3 class="detailsub">Fundamentals</h3>' +
        '<div class="nofund"><strong>Not available for this listing.</strong> ' +
        esc(why) + '. Nothing is estimated in its place \u2014 an absent ' +
        'fundamental is honest, an invented one is not.' +
        (stock.region === 'india'
          ? '<span class="nofundfix">Indian fundamentals need a free '
            + 'provider key. Every keyless route was tested: the exchanges '
            + 'block automated access, and the aggregators that do carry the '
            + 'figures forbid reuse. Add a key and these fill in on the next '
            + 'refresh.</span>'
          : '') +
        '</div>';
    }
    var f = stock.fundamentals, r = f.ratios || {}, s = f.series || {};

    function tile(label, value, note) {
      return '<span class="dstat"><i>' + esc(label) + '</i><b>' + value + '</b>' +
        (note ? '<u>' + esc(note) + '</u>' : '') + '</span>';
    }

    var html = '<h3 class="detailsub">Fundamentals</h3>' +
      '<div class="detailgrid">' +
        tile('Market cap', money(r.market_cap)) +
        tile('P/E', r.pe_ratio ? num(r.pe_ratio, 1) : '—', 'on last filed EPS') +
        tile('Price / book', r.price_to_book ? num(r.price_to_book, 1) : '—') +
        tile('Net margin', pct(r.net_margin, 1)) +
        tile('Operating margin', pct(r.operating_margin, 1)) +
        tile('Return on equity', pct(r.return_on_equity, 1)) +
        tile('Debt / equity', r.debt_to_equity ? num(r.debt_to_equity, 2) : '—') +
        tile('Book value / share', r.book_value_per_share
             ? num(r.book_value_per_share) : '—') +
        (r.dividend_yield != null
          ? tile('Dividend yield', pct(r.dividend_yield, 2)) : '') +
        (r.eps != null ? tile('EPS', num(r.eps)) : '') +
        (r.beta != null ? tile('Beta', num(r.beta, 2), 'vs its index') : '') +
        (r.analyst_target != null
          ? tile('Analyst target', num(r.analyst_target), 'provider consensus') : '') +
      '</div>';

    // Multi-year trend: the direction matters more than any single year.
    var rows = [['revenue', 'Revenue'], ['net_income', 'Net income'],
                ['operating_cash_flow', 'Operating cash flow'],
                ['eps_diluted', 'EPS (diluted)']];
    var years = (s.revenue || s.net_income || []).map(function (y) { return y.year; });
    if (years.length) {
      var head = '<tr><th>Figure</th>' + years.map(function (y) {
        return '<th class="num">FY' + esc(y) + '</th>';
      }).join('') + '</tr>';
      var bodyRows = rows.map(function (row) {
        var series = s[row[0]];
        if (!series || !series.length) return '';
        var byYear = {};
        series.forEach(function (item) { byYear[item.year] = item.value; });
        return '<tr><td>' + esc(row[1]) + '</td>' + years.map(function (y) {
          var v = byYear[y];
          if (v == null) return '<td class="num">—</td>';
          return '<td class="num">' +
            (row[0] === 'eps_diluted' ? num(v) : money(v)) + '</td>';
        }).join('') + '</tr>';
      }).join('');
      html += '<div class="fundwrap"><table class="fundtable"><thead>' + head +
        '</thead><tbody>' + bodyRows + '</tbody></table></div>';
    }

    var growth = [];
    if (r.revenue_growth != null) {
      growth.push('revenue ' + pct(r.revenue_growth, 1) + ' on the year');
    }
    if (r.earnings_growth != null) {
      growth.push('earnings ' + pct(r.earnings_growth, 1));
    }
    // Attribution follows the actual source, field by field. A filing does
    // not contain a beta or an analyst consensus target, so a page carrying
    // both must not credit all of it to the filings.
    var PROVIDER_ONLY = ['beta', 'analyst_target', 'dividend_yield', 'eps'];
    var fromProvider = PROVIDER_ONLY.filter(function (name) {
      return r[name] != null;
    });
    var LABELS = {beta: 'beta', analyst_target: 'analyst target',
                  dividend_yield: 'dividend yield', eps: 'EPS'};
    var credit;
    if (f.provider) {
      credit = 'Supplied by ' + esc(f.provider) + ', a third-party data '
        + 'provider' + (f.as_of ? ', as of ' + esc(f.as_of) : '') + '. These are '
        + 'that provider\u2019s own computed ratios rather than figures read '
        + 'from a filing, so they carry its assumptions.';
    } else {
      credit = 'Read from this company\u2019s own 10-K filings with the SEC '
        + '\u2014 nothing estimated, smoothed or modelled. '
        + '<a class="fundsrc" href="' + esc(f.source || '#')
        + '" target="_blank" rel="noopener noreferrer">See the filings</a>.';
      if (f.extras_provider && fromProvider.length) {
        credit += ' The ' + fromProvider.map(function (n) {
          return LABELS[n];
        }).join(', ') + ' ' + (fromProvider.length === 1 ? 'is' : 'are')
          + ' the exception: a filing does not carry '
          + (fromProvider.length === 1 ? 'it' : 'those') + ', so '
          + (fromProvider.length === 1 ? 'it comes' : 'they come') + ' from '
          + esc(f.extras_provider) + '.';
      }
    }
    html += '<p class="caption">' + (growth.length ? esc(growth.join(', ')) + '. ' : '')
      + credit + '</p>';
    return html;
  }

  // --- price chart with range filters ------------------------------------
  // Ranges slice the full cached series rather than redrawing the same 60
  // sessions at every setting, which is why the sidecar carries two years.
  var RANGES = [['1M', 21], ['3M', 63], ['6M', 126], ['1Y', 252], ['2Y', 0]];
  var chartRange = 126;

  function chartSeries(stock) {
    var h = stock.history || {};
    if (h.c && h.c.length >= 2) return {c: h.c, d: h.d || [], v: h.v || []};
    var s = stock.spark || [];
    return s.length >= 2 ? {c: s, d: [], v: []} : null;
  }

  function chart(stock) {
    var full = chartSeries(stock);
    if (!full) return '';
    var n = chartRange > 0 ? Math.min(chartRange, full.c.length) : full.c.length;
    var closes = full.c.slice(-n);
    var days = full.d.slice(-n);
    var vols = full.v.slice(-n);

    var w = 720, h = 190, vh = 34, gap = 8;
    var hi = Number(stock.high_52w), lo = Number(stock.low_52w);
    var vals = closes.slice();
    // Only fold the 52-week levels into the scale when they are actually in
    // view; on a one-month range they would flatten the line to nothing.
    var showLevels = n >= 200;
    if (showLevels && isFinite(hi)) vals.push(hi);
    if (showLevels && isFinite(lo)) vals.push(lo);
    var top = Math.max.apply(null, vals), bottom = Math.min.apply(null, vals);
    if (top === bottom) top = bottom + 1;
    var pad = (top - bottom) * 0.08;
    top += pad; bottom -= pad;
    var span = top - bottom;

    function x(i) { return closes.length < 2 ? 0 : i * w / (closes.length - 1); }
    function y(v) { return h - ((v - bottom) / span * h); }

    var line = closes.map(function (v, i) {
      return x(i).toFixed(1) + ',' + y(v).toFixed(1);
    }).join(' ');
    var area = '0,' + h + ' ' + line + ' ' + w + ',' + h;
    var rising = closes[closes.length - 1] >= closes[0];

    var rules = '';
    if (showLevels) {
      [[hi, 'win', '52w high'], [lo, 'lose', '52w low']].forEach(function (row) {
        if (!isFinite(row[0])) return;
        var yy = y(row[0]);
        if (yy < 0 || yy > h) return;
        rules += '<line class="jrule ' + row[1] + '" x1="0" y1="' + yy.toFixed(1) +
          '" x2="' + w + '" y2="' + yy.toFixed(1) + '"/>';
      });
    }

    // Volume underneath, scaled to its own maximum — sharing the price scale
    // would render every bar invisible.
    var volSvg = '';
    if (vols.length === closes.length && vols.some(function (v) { return v > 0; })) {
      var vmax = Math.max.apply(null, vols) || 1;
      var bw = Math.max(w / closes.length * 0.72, 0.6);
      volSvg = '<svg class="volchart" viewBox="0 0 ' + w + ' ' + vh +
        '" preserveAspectRatio="none" aria-hidden="true">' +
        vols.map(function (v, i) {
          var bh = Math.max(v / vmax * vh, 0.4);
          return '<rect x="' + (x(i) - bw / 2).toFixed(1) + '" y="' +
            (vh - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' +
            bh.toFixed(1) + '"/>';
        }).join('') + '</svg>';
    }

    var buttons = RANGES.map(function (r) {
      var available = r[1] === 0 || full.c.length > r[1];
      if (!available) return '';
      var on = chartRange === r[1];
      return '<button type="button" class="rangebtn' + (on ? ' on' : '') +
        '" data-range="' + r[1] + '"' + (on ? ' aria-pressed="true"' : '') + '>' +
        r[0] + '</button>';
    }).join('');

    var first = days.length ? days[0] : '';
    var last = days.length ? days[days.length - 1] : '';
    var move = closes[0] ? (closes[closes.length - 1] - closes[0]) / closes[0] * 100 : 0;

    return '<div class="detailchart">' +
      '<div class="chartbar"><span class="chartmove ' +
        (move >= 0 ? 'pos' : 'neg') + '">' + (move >= 0 ? '+' : '') +
        move.toFixed(2) + '% over this range</span>' +
        '<span class="rangebtns" role="group" aria-label="Chart range">' +
        buttons + '</span></div>' +
      '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" ' +
        'class="spark spark-' + (rising ? 'up' : 'down') + '" aria-hidden="true">' +
        rules +
        '<polygon class="sparkarea" points="' + area + '" fill="url(#sparkfill)"/>' +
        '<polyline class="sparkline" points="' + line +
        '" vector-effect="non-scaling-stroke"/></svg>' +
      volSvg +
      '<div class="chartscale"><span>' + esc(first) + '</span>' +
        '<span>' + closes.length + ' sessions \u00b7 volume below</span>' +
        '<span>' + esc(last) + '</span></div>' +
    '</div>';
  }


  function render(stock) {
    var screen = stock.screen || {};
    var reading = screen.reading || {};
    var regionLabel = stock.region === 'india' ? 'India' : 'United States';
    var rangePos = stock.range_position == null ? null : Number(stock.range_position) * 100;

    var html =
      '<div class="detailhead">' +
        '<div><h2 class="detailsym">' + esc(stock.symbol) + '</h2>' +
        '<p class="detailname">' + esc(stock.name) + '</p>' +
        '<p class="detailtags"><span class="tag">' + esc(regionLabel) + '</span>' +
        '<span class="tag">' + esc(stock.exchange || '') + '</span>' +
        '<span class="tag">' + esc(stock.sector || '') + '</span></p></div>' +
        '<div class="detailprice"><span class="detaillast">' + num(stock.last) +
          ' <i>' + esc(stock.currency || '') + '</i></span>' +
          '<span class="detailmove ' + tone(stock.change_1d) + '">' +
          pct(stock.change_1d) + ' today</span></div>' +
      '</div>';

    html += chart(stock);

    html += '<div class="detailgrid">' +
      ['1 day', '1 week', '1 month', '3 months'].map(function (label, i) {
        var key = ['change_1d', 'change_1w', 'change_1m', 'change_3m'][i];
        return '<span class="dstat"><i>' + label + '</i><b class="' + tone(stock[key]) +
          '">' + pct(stock[key]) + '</b></span>';
      }).join('') +
      '<span class="dstat"><i>52-week high</i><b>' + num(stock.high_52w) + '</b>' +
        '<u>' + pct(stock.off_high) + ' from here</u></span>' +
      '<span class="dstat"><i>52-week low</i><b>' + num(stock.low_52w) + '</b>' +
        '<u>' + pct(stock.off_low) + ' from here</u></span>' +
      (rangePos == null ? '' :
        '<span class="dstat"><i>Position in range</i><b>' + rangePos.toFixed(0) +
        '%</b><u>' + (rangePos > 80 ? 'near its high' : rangePos < 20 ?
          'near its low' : 'mid-range') + '</u></span>') +
      '<span class="dstat"><i>Avg volume (21d)</i><b>' +
        (stock.avg_volume ? Number(stock.avg_volume).toLocaleString('en-US',
          {maximumFractionDigits: 0}) : '—') + '</b></span>' +
    '</div>';

    // What the strategies are doing about it, if anything.
    if (stock.is_benchmark) {
      html += '<h3 class="detailsub">Headlines</h3><div data-detail-news>'
        + '<p class="empty">Loading&hellip;</p></div>';
      body.innerHTML = html;
      loadNews(stock);
      return;
    }

    var statusText = {
      held: 'The book holds this.', signal: 'Suggested today.',
      resting: 'An order for this is still resting.',
      watching: 'Watched, but nothing qualifies right now.'
    }[stock.status] || '';
    html += '<div class="detailstatus ' + esc(stock.status || '') + '">' +
      '<strong>' + esc(statusText) + '</strong>';
    if (stock.order) {
      html += ' ' + esc(stock.order.reason) + '. Stop ' + num(stock.order.stop_loss) +
        ', target ' + num(stock.order.take_profit) + '.';
    } else if (stock.position) {
      html += ' Holding ' + esc(stock.position.quantity) + ' at ' +
        num(stock.position.average_cost) +
        (stock.position.stop ? ', stop ' + num(stock.position.stop) : '') +
        (stock.position.take_profit ? ', target ' + num(stock.position.take_profit) : '') + '.';
    }
    html += '</div>';

    if (screen.signal) {
      html += '<h3 class="detailsub">What the screener reads</h3>' +
        '<div class="detailverdict">' +
          '<span class="screensig ' + esc(screen.signal) + '">' +
            esc(screen.signal.charAt(0).toUpperCase() + screen.signal.slice(1)) + '</span>' +
          '<span class="dstat"><i>Score</i><b>' + num(screen.score) + '</b></span>' +
          '<span class="dstat"><i>Conviction</i><b>' +
            Math.round(Number(screen.strength || 0) * 100) + '%</b></span>' +
          '<span class="dstat"><i>Regime</i><b>' + esc(screen.regime || '—') + '</b></span>' +
          '<span class="dstat"><i>vs its market</i><b class="' +
            tone(screen.relative_momentum) + '">' + pct(screen.relative_momentum) +
            '</b></span>' +
        '</div>' +
        '<p class="screenwhy">' + esc(screen.rationale || '') + '</p>';

      html += '<h3 class="detailsub">Technical readings</h3><div class="techtable">' +
        techRow('RSI (14)', num(reading.rsi, 0), readRSI(reading.rsi)) +
        techRow('ADX', num(reading.adx, 0), readADX(reading.adx)) +
        techRow('Supertrend', Number(reading.supertrend_direction) > 0 ? 'up' : 'down',
                readST(reading.supertrend_direction)) +
        techRow('MACD histogram', num(reading.macd_hist, 3), readMACD(reading.macd_hist)) +
        techRow('Bollinger position', reading.bollinger_pct_b == null ? '—'
                  : (Number(reading.bollinger_pct_b) * 100).toFixed(0) + '%',
                readBollinger(reading.bollinger_pct_b)) +
      '</div>' +
      '<div class="detailgrid tight">' +
        '<span class="dstat"><i>50-day average</i><b>' + num(reading.sma_fast) + '</b></span>' +
        '<span class="dstat"><i>200-day average</i><b>' + num(reading.sma_slow) + '</b></span>' +
        '<span class="dstat"><i>Daily range (ATR)</i><b>' +
          pct(reading.atr_pct) + '</b><u>of price</u></span>' +
        '<span class="dstat"><i>Annualised volatility</i><b>' +
          pct(reading.annualised_volatility, 1) + '</b></span>' +
        '<span class="dstat"><i>Momentum, 3 months</i><b class="' +
          tone(reading.momentum_short) + '">' + pct(reading.momentum_short, 1) +
          '</b></span>' +
        '<span class="dstat"><i>Momentum, 12 months</i><b class="' +
          tone(reading.momentum_long) + '">' + pct(reading.momentum_long, 1) +
          '</b></span>' +
        '<span class="dstat"><i>Its sector</i><b class="' +
          tone(screen.sector_momentum) + '">' + pct(screen.sector_momentum, 1) +
          '</b><u>same window</u></span>' +
      '</div>';
    } else {
      html += '<p class="empty">The screener has no reading for this name in ' +
        'this build.</p>';
    }

    // An index has no dividend, no filing and no screener verdict. Rendering
    // three "not available" panels would be noise, so they are simply absent
    // and a line says what this view is instead.
    if (!stock.is_benchmark) {
      html += actions(stock);
      html += fundamentals(stock);
    } else {
      html += '<p class="caption">This is a market benchmark, not a tradable '
        + 'holding \u2014 there are no filings, dividends or strategy signals '
        + 'behind it. It is here for context: what the market did while your '
        + 'own positions did whatever they did.</p>';
    }

    html += '<h3 class="detailsub">Headlines</h3><div data-detail-news>' +
      '<p class="empty">Loading&hellip;</p></div>' +
      '<p class="caption">Everything above is measured from closing prices in ' +
      'this app\u2019s own cache. None of it is a forecast, and none of it is ' +
      'advice.</p>';

    body.innerHTML = html;
    loadNews(stock);
  }

  function loadNews(stock) {
    var slot = body.querySelector('[data-detail-news]');
    if (!slot || typeof fetch !== 'function') return;
    var cfg = window.__mpCfg || {};
    var API = cfg.api_base || '/markets-pro/api';
    fetch(API + '/news?symbols=' + encodeURIComponent(stock.yahoo))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        var stories = payload && payload.news ? (payload.news[stock.yahoo] || []) : [];
        slot.textContent = '';
        if (!stories.length) {
          var none = document.createElement('p');
          none.className = 'empty';
          none.textContent = 'No headlines carried for this name. Coverage is '
            + 'thin for many listings.';
          slot.appendChild(none);
          return;
        }
        stories.forEach(function (story) {
          var a = document.createElement('a');
          a.className = 'newsitem';
          a.href = story.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
          var title = document.createElement('span');
          title.className = 'newstitle';
          title.textContent = story.title;
          a.appendChild(title);
          slot.appendChild(a);
        });
      })
      .catch(function () {
        slot.textContent = '';
        var failed = document.createElement('p');
        failed.className = 'empty';
        failed.textContent = 'Headlines could not be reached.';
        slot.appendChild(failed);
      });
  }

  function open(key) {
    return stocks().then(function (all) {
      var stock = all[key];
      if (!stock) { close(); return false; }
      document.querySelectorAll('.tabpanel').forEach(function (p) { p.hidden = true; });
      host.hidden = false;
      openStock = stock;
      render(stock);
      window.scrollTo(0, 0);
      return true;
    });
  }

  function close() {
    host.hidden = true;
    var tab = document.querySelector('[data-tabbtn="' + lastTab + '"]');
    if (tab) tab.click(); else location.hash = '#dashboard';
  }

  var openStock = null;

  document.addEventListener('click', function (event) {
    var range = event.target.closest('[data-range]');
    if (range && openStock) {
      chartRange = Number(range.getAttribute('data-range'));
      render(openStock);                     // redraw at the new range
      return;
    }
    var trigger = event.target.closest('[data-stock]');
    if (trigger) {
      // Read the panel the row lives in rather than the active tab button:
      // the button's class lags a programmatic hash change, which sent Back
      // to the dashboard instead of where the reader actually came from.
      var panel = trigger.closest('[data-tab]');
      if (panel) lastTab = panel.getAttribute('data-tab');
      var key = trigger.getAttribute('data-stock');
      event.preventDefault();
      location.hash = '#stock/' + key;
      return;
    }
    if (event.target.closest('[data-detail-back]')) { location.hash = '#' + lastTab; }
  });

  function route() {
    var match = /^#stock\\/(.+)$/.exec(location.hash || '');
    if (match) { open(decodeURIComponent(match[1])); }
    else if (!host.hidden) { host.hidden = true; }
  }
  window.addEventListener('hashchange', route);
  route();
})();
"""


#: Mutual fund search.
#:
#: The index is ~1.8 MB uncompressed and about 190 KB on the wire, fetched
#: once when the tab is first opened. Searching it locally means a keystroke
#: costs nothing; paging it from a static host would mean a round trip per
#: character.
FUNDS_JS = """
(function () {
  var results = document.querySelector('[data-funds-results]');
  var search = document.querySelector('[data-fsearch]');
  if (!results || !search || typeof fetch !== 'function') return;

  var DATA = null, loading = null, category = 'all';
  var API_FILE = ((window.__mpCfg || {}).data_base || '/markets-pro/')
    + 'funds.json';

  function load() {
    if (DATA) return Promise.resolve(DATA);
    if (loading) return loading;
    loading = fetch(API_FILE)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { DATA = d || {schemes: []}; return DATA; })
      .catch(function () { DATA = {schemes: []}; return DATA; });
    return loading;
  }

  function money(v) {
    return Number(v).toLocaleString('en-IN',
      {minimumFractionDigits: 2, maximumFractionDigits: 4});
  }

  function render(rows, data, truncated) {
    results.textContent = '';
    if (!rows.length) {
      var none = document.createElement('p');
      none.className = 'empty';
      none.textContent = 'No scheme matches that.';
      results.appendChild(none);
      return;
    }
    var table = document.createElement('table');
    table.className = 'fundstable';
    table.innerHTML = '<thead><tr><th>Scheme</th><th>Plan</th>' +
      '<th class="num">NAV</th><th class="num">As of</th></tr></thead>';
    var body = document.createElement('tbody');
    rows.forEach(function (s) {
      var tr = document.createElement('tr');
      var name = document.createElement('td');
      var strong = document.createElement('strong');
      strong.textContent = s.n;                    // third-party text stays text
      name.appendChild(strong);
      var meta = document.createElement('span');
      meta.className = 'fundmeta';
      meta.textContent = (data.house_names[s.h] || '') + ' · ' +
        (data.category_names[s.g] || '');
      name.appendChild(meta);
      tr.appendChild(name);

      var plan = document.createElement('td');
      plan.className = 'fundplan';
      plan.textContent = [s.p, s.o].filter(Boolean).join(' · ');
      tr.appendChild(plan);

      var nav = document.createElement('td');
      nav.className = 'num';
      nav.textContent = money(s.v);
      tr.appendChild(nav);

      var day = document.createElement('td');
      day.className = 'num fundday';
      day.textContent = s.d;
      tr.appendChild(day);
      body.appendChild(tr);
    });
    table.appendChild(body);
    var wrap = document.createElement('div');
    wrap.className = 'fundwrap';
    wrap.appendChild(table);
    results.appendChild(wrap);

    if (truncated) {
      var note = document.createElement('p');
      note.className = 'caption';
      note.textContent = 'Showing the first 200 of ' + truncated.toLocaleString('en-US') +
        ' matches — narrow the search to see the rest. Nothing is hidden by ' +
        'ranking; these are simply the first in the file.';
      results.appendChild(note);
    }
  }

  function run() {
    var term = search.value.trim().toLowerCase();
    if (term.length < 2 && category === 'all') {
      results.innerHTML = '<p class="empty">Type at least two characters to ' +
        'search, or pick a category.</p>';
      return;
    }
    results.innerHTML = '<p class="empty">Searching\u2026</p>';
    load().then(function (data) {
      var schemes = data.schemes || [];
      var matched = [];
      for (var i = 0; i < schemes.length; i++) {
        var s = schemes[i];
        if (category !== 'all' && data.category_names[s.g] !== category) continue;
        if (term) {
          var hay = (s.n + ' ' + (data.house_names[s.h] || '')).toLowerCase();
          if (hay.indexOf(term) < 0) continue;
        }
        matched.push(s);
      }
      render(matched.slice(0, 200), data, matched.length > 200 ? matched.length : 0);
    });
  }

  var debounce = null;
  search.addEventListener('input', function () {
    clearTimeout(debounce);
    debounce = setTimeout(run, 180);
  });

  document.querySelectorAll('[data-fcat]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      category = chip.getAttribute('data-fcat');
      document.querySelectorAll('[data-fcat]').forEach(function (other) {
        other.setAttribute('aria-pressed', other === chip ? 'true' : 'false');
      });
      run();
    });
  });

  // Warm the index when the tab opens so the first search feels instant.
  var tab = document.querySelector('[data-tabbtn="funds"]');
  if (tab) tab.addEventListener('click', function () { load(); });
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


JOURNEY_CSS = """
/* ---------------------------------------------------------------------------
   The walkthrough.

   Everything animated here is scoped to `.jpanel.on`, so a step's motion runs
   exactly when that step becomes the active one and never before. Removing the
   class and re-adding it restarts the whole set, which is what replay does.

   The last block disables all of it under prefers-reduced-motion and opens
   every panel at once, because a reader who has asked for no motion should get
   the same content as a document, not a slideshow they have to drive.
--------------------------------------------------------------------------- */
.journey{border:1px solid var(--line);border-radius:14px;background:var(--panel);
  box-shadow:var(--elev-2);overflow:hidden;margin:0 0 20px}
.jbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
  padding:15px 18px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 6%,var(--panel)),
    var(--panel))}
.jtitle{font-size:15.5px;margin:0;text-transform:none;letter-spacing:-0.01em;
  color:var(--ink);font-weight:650}
.jlede{margin:3px 0 0;font-size:12.5px;color:var(--muted)}
.jctl{display:flex;gap:6px;flex:0 0 auto}
.jbtnctl{appearance:none;font:inherit;font-size:12.5px;display:inline-flex;
  align-items:center;gap:6px;padding:5px 11px;border:1px solid var(--line);
  border-radius:999px;background:var(--panel);color:var(--ink);cursor:pointer;
  transition:background .18s var(--ease),border-color .18s var(--ease)}
.jbtnctl:hover{background:var(--tag)}
.jbtnctl:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
/* Two bars, squeezed to a triangle when playing is the thing on offer. */
.jicon{width:9px;height:11px;flex:0 0 auto;background:currentColor;
  clip-path:polygon(0 0,3.5px 0,3.5px 11px,0 11px,0 0,5.5px 0,9px 0,9px 11px,
    5.5px 11px);transition:clip-path .2s var(--ease)}
.journey.paused .jicon{clip-path:polygon(0 0,9px 5.5px,0 11px)}

.jbody{display:grid;grid-template-columns:210px 1fr;align-items:stretch}
.jrail{list-style:none;margin:0;padding:10px;display:flex;flex-direction:column;
  gap:2px;border-right:1px solid var(--line);
  background:color-mix(in srgb,var(--tag) 45%,transparent)}
.jrail button{appearance:none;width:100%;text-align:left;font:inherit;
  font-size:13px;display:flex;align-items:center;gap:9px;padding:8px 10px;
  border:0;border-radius:8px;background:transparent;color:var(--muted);
  cursor:pointer;position:relative;
  transition:background .2s var(--ease),color .2s var(--ease)}
.jrail button:hover{background:var(--panel);color:var(--ink)}
.jrail button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.jrail button[aria-selected="true"]{background:var(--panel);color:var(--ink);
  font-weight:600;box-shadow:var(--elev-1)}
.jnum{flex:0 0 auto;width:21px;height:21px;border-radius:50%;display:grid;
  place-items:center;font-size:11px;font-weight:600;background:var(--tag);
  color:var(--muted);font-variant-numeric:tabular-nums;
  transition:background .2s var(--ease),color .2s var(--ease)}
.jrail button[aria-selected="true"] .jnum{background:var(--accent);color:#fff}
.jrail button.done .jnum{background:color-mix(in srgb,var(--accent) 22%,transparent);
  color:var(--accent)}
.jrail-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.jstage{position:relative;padding:20px 22px 22px;min-height:340px}
.jpanel{display:flex;flex-direction:column;gap:9px}
/* An explicit `display` on .jpanel beats the user-agent rule for [hidden], so
   the attribute has to be honoured here or every step renders at once. */
.jpanel[hidden]{display:none}
.jpanel:focus-visible{outline:2px solid var(--accent);outline-offset:4px;
  border-radius:8px}
.jpanel.on{animation:jfade .34s var(--ease) both}
@keyframes jfade{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.jkicker{margin:0;font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--accent);font-weight:600}
.jhead{margin:0;font-size:19px;line-height:1.25;letter-spacing:-0.015em;
  font-weight:650}
.jsay{margin:0;font-size:13.5px;color:var(--muted);max-width:62ch}
.jart{margin-top:6px}
.jmeta{margin:11px 0 0;font-size:12px;color:var(--muted);max-width:70ch}

/* --- the detail blocks -----------------------------------------------------
   Each step used to assert a thing ("rules cut the list down") without saying
   which. These carry the specifics. They are dense on purpose: this is the
   part a sceptical reader came for, and it should reward being read closely
   rather than restating the headline. */
.jnotes{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:8px;
  max-width:72ch}
.jnotes li{position:relative;padding-left:16px;font-size:12.5px;
  line-height:1.6;color:var(--muted)}
.jnotes li::before{content:"";position:absolute;left:0;top:.55em;
  width:5px;height:5px;border-radius:50%;background:var(--accent);opacity:.7}
.jnotes strong{color:var(--ink);font-weight:600}

.jrules{display:grid;gap:10px;margin:14px 0 0;
  grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.jrule-card{border:1px solid var(--line);border-radius:9px;padding:11px 13px;
  background:color-mix(in srgb,var(--panel) 70%,transparent);
  animation:jfade .5s var(--ease) both;animation-delay:calc(var(--i) * .12s + .2s)}
.jrule-book{display:inline-block;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;color:var(--accent);
  margin-bottom:3px}
.jrule-name{display:block;font-size:13.5px;margin-bottom:7px;color:var(--ink)}
.jrule-lead{margin:0 0 5px;font-size:11px;color:var(--muted)}
.jrule-tests{margin:0;padding-left:15px;display:grid;gap:4px}
.jrule-tests li{font-size:12px;line-height:1.5;color:var(--muted)}
.jrule-exit{margin:8px 0 0;font-size:11.5px;color:var(--muted);
  padding-top:7px;border-top:1px solid var(--line)}
.jrule-exitlabel{font-weight:700;text-transform:uppercase;font-size:9.5px;
  letter-spacing:.06em;color:var(--ink);margin-right:5px}

.jworked{margin:14px 0 0;padding:12px 14px;border-radius:9px;
  border:1px dashed var(--line);
  background:color-mix(in srgb,var(--panel) 55%,transparent)}
.jworkedlabel{display:block;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;color:var(--accent);
  margin-bottom:8px}
.jsteps{margin:0;padding-left:17px;display:grid;gap:6px}
.jsteps li{font-size:12.5px;line-height:1.55;color:var(--muted)}
.jsteps strong{color:var(--ink)}
.jworkednote{margin:10px 0 0;font-size:12px;color:var(--muted);
  padding-top:8px;border-top:1px solid var(--line)}
.jworkednote em{color:var(--ink);font-style:normal;font-weight:600}

.jtiers{display:grid;gap:9px;margin:14px 0 0;
  grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.jtier{border:1px solid var(--line);border-radius:9px;padding:10px 12px;
  animation:jfade .5s var(--ease) both;animation-delay:calc(var(--i) * .1s + .3s)}
.jtierhead{display:flex;align-items:center;gap:6px;font-size:12.5px;
  font-weight:600;color:var(--ink);margin-bottom:5px}
.jtier p{margin:0;font-size:11.5px;line-height:1.55;color:var(--muted)}

.jpastgrid{display:grid;gap:8px;margin:10px 0 0;
  grid-template-columns:repeat(auto-fit,minmax(96px,1fr))}
.jpast{display:flex;flex-direction:column;gap:1px;padding:8px 10px;
  border:1px solid var(--line);border-radius:8px}
.jpast i{font-style:normal;font-size:10px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.jpast b{font-size:16px;font-variant-numeric:tabular-nums;color:var(--ink)}
.jpast u{text-decoration:none;font-size:10.5px;color:var(--muted)}
.jpast.win b{color:var(--pos)} .jpast.lose b{color:var(--neg)}
.jpastend{margin:10px 0 0;font-size:12px;color:var(--muted);
  display:flex;align-items:center;gap:6px}
.jdot.bad{background:var(--neg)}

@media (max-width:640px){
  .jrules,.jtiers{grid-template-columns:1fr}
  .jpastgrid{grid-template-columns:repeat(2,1fr)}
}
.jmeta strong{color:var(--ink);font-variant-numeric:tabular-nums}
.jempty{margin:0;font-size:13.5px;color:var(--muted);max-width:62ch}

/* step 1 — the amount being typed in */
.jfield{display:flex;flex-direction:column;gap:5px;width:fit-content}
.jflabel{font-size:11.5px;color:var(--muted)}
.jfbox{display:inline-flex;align-items:center;min-width:230px;height:44px;
  padding:0 13px;border:1px solid var(--line);border-radius:8px;
  background:var(--bg);font-size:19px;font-weight:600;
  font-variant-numeric:tabular-nums;box-shadow:var(--elev-1)}
.jpanel.on .jfbox{animation:jfocus .5s var(--ease) .1s both}
@keyframes jfocus{
  from{border-color:var(--line)}
  60%{border-color:var(--accent);
      box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 18%,transparent)}
  to{border-color:var(--accent);
     box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 12%,transparent)}}
.jkey{opacity:0}
.jpanel.on .jkey{animation:jkeyin .01s linear both;animation-delay:calc(.45s + var(--i) * .11s)}
@keyframes jkeyin{to{opacity:1}}
.jcaret{width:2px;height:21px;margin-left:2px;background:var(--accent);opacity:0}
.jpanel.on .jcaret{animation:jblink .8s steps(2,jump-none) .35s 3 both}
@keyframes jblink{0%{opacity:1}50%{opacity:0}100%{opacity:1}}
.jreceipt{display:flex;width:fit-content;align-items:center;gap:8px;margin-top:13px;
  padding:8px 13px;border-radius:999px;font-size:12.5px;
  border:1px solid color-mix(in srgb,var(--pos) 34%,var(--line));
  background:color-mix(in srgb,var(--pos) 9%,transparent);color:var(--ink);
  opacity:0}
.jpanel.on .jreceipt{animation:jrise .42s var(--ease) 1.6s both}
.jpanel.on .jreceipt.delayed{animation-delay:2.1s}
@keyframes jrise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.jdot{width:7px;height:7px;border-radius:50%;background:var(--pos);flex:0 0 auto}

/* step 2 — the watchlist under a scan */
.jscan{position:relative;overflow:hidden;border:1px solid var(--line);
  border-radius:10px;padding:11px;background:var(--bg)}
.jgrid{display:flex;flex-wrap:wrap;gap:5px}
.jtick{font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  padding:3px 7px;border-radius:5px;background:var(--tag);color:var(--muted);
  border:1px solid transparent;opacity:.35}
.jpanel.on .jtick{animation:jlight .9s var(--ease) both;
  animation-delay:calc(var(--i) * .045s)}
@keyframes jlight{
  0%{opacity:.35;transform:scale(.94)}
  35%{opacity:1;transform:scale(1);border-color:color-mix(in srgb,var(--accent) 45%,transparent);
      color:var(--ink)}
  100%{opacity:.82;transform:scale(1);border-color:transparent;color:var(--ink)}}
.jsweep{position:absolute;inset:0 auto 0 0;width:120px;pointer-events:none;
  background:linear-gradient(90deg,transparent,
    color-mix(in srgb,var(--accent) 15%,transparent),transparent);opacity:0}
.jpanel.on .jsweep{animation:jsweep 1.9s var(--ease) .1s both}
@keyframes jsweep{0%{opacity:1;transform:translateX(-130px)}
  100%{opacity:0;transform:translateX(calc(100% + 100vw))}}

/* step 3 — the funnel */
.jfunnel{display:grid;grid-template-columns:1fr 46px;
  grid-template-areas:"label n" "track n" "note note";gap:3px 12px;
  align-items:center;margin-bottom:13px;opacity:0}
.jpanel.on .jfunnel{animation:jrise .45s var(--ease) both;
  animation-delay:calc(.15s + var(--i) * .3s)}
.jfl{grid-area:label;font-size:12.5px;color:var(--ink)}
.jftrack{grid-area:track;height:12px;border-radius:6px;background:var(--tag);
  overflow:hidden}
.jffill{display:block;height:100%;width:var(--w);border-radius:6px;
  background:linear-gradient(90deg,var(--accent),
    color-mix(in srgb,var(--accent) 62%,var(--pos)));transform-origin:left}
.jpanel.on .jffill{animation:jgrow .7s var(--ease) both;
  animation-delay:calc(.3s + var(--i) * .3s)}
@keyframes jgrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.jfn{grid-area:n;font-size:22px;font-weight:650;text-align:right;
  font-variant-numeric:tabular-nums}
.jfnote{grid-area:note;font-size:11.5px;color:var(--muted)}

/* step 4 — the caps */
.jstack{position:relative;height:38px;border-radius:8px;background:var(--tag);
  overflow:hidden;margin-bottom:14px}
.jstackfill{position:absolute;inset:0;transform-origin:left;
  background:linear-gradient(90deg,
    color-mix(in srgb,var(--accent) 20%,transparent),
    color-mix(in srgb,var(--accent) 9%,transparent))}
.jpanel.on .jstackfill{animation:jgrow .6s var(--ease) .1s both}
.jstackslice{position:absolute;top:0;bottom:0;left:0;width:var(--w);
  background:var(--accent);border-radius:8px 0 0 8px;display:grid;
  place-items:center;transform-origin:left;opacity:0}
.jstackslice i{font-style:normal;font-size:11px;font-weight:650;color:#fff;
  white-space:nowrap}
.jpanel.on .jstackslice{animation:jslice .6s var(--ease) .55s both}
@keyframes jslice{from{opacity:0;transform:scaleX(0)}
  to{opacity:1;transform:scaleX(1)}}
.jlimits{list-style:none;margin:0;padding:0;display:grid;gap:7px}
.jlimits li{font-size:12.5px;color:var(--muted);opacity:0;
  padding-left:15px;position:relative}
.jlimits li::before{content:"";position:absolute;left:0;top:7px;width:6px;
  height:6px;border-radius:50%;background:var(--accent);opacity:.55}
.jlimits strong{color:var(--ink);font-variant-numeric:tabular-nums}
.jpanel.on .jlimits li{animation:jrise .4s var(--ease) both;
  animation-delay:calc(.8s + var(--i) * .22s)}

/* step 5 — the real trade */
.jtrade{border:1px solid var(--line);border-radius:10px;padding:13px;
  background:var(--bg)}
.jtradehead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;
  margin-bottom:9px;font-size:15px}
.jchart{width:100%;height:auto;max-width:640px;display:block;overflow:visible}
.jzone{opacity:0}
.jzone.win{fill:var(--pos)}
.jzone.lose{fill:var(--neg)}
.jpanel.on .jzone{animation:jzone .6s var(--ease) 1.15s both}
@keyframes jzone{to{opacity:.09}}
.jchartarea{fill:color-mix(in srgb,var(--accent) 14%,transparent);stroke:none;
  opacity:0}
.jpanel.on .jchartarea{animation:jzone2 .5s var(--ease) .95s both}
@keyframes jzone2{to{opacity:1}}
.jchartline{fill:none;stroke:var(--accent);stroke-width:1.9;
  stroke-linejoin:round;stroke-linecap:round;stroke-dasharray:1;
  stroke-dashoffset:1}
.jpanel.on .jchartline{animation:jdraw 1.15s var(--ease) .15s both}
@keyframes jdraw{to{stroke-dashoffset:0}}
.jrule{stroke-width:1;stroke-dasharray:3 4;opacity:0}
.jrule.win{stroke:var(--pos)} .jrule.lose{stroke:var(--neg)}
.jrule.now{stroke:var(--muted);stroke-dasharray:2 3}
.jtag{font-size:9.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  opacity:0}
.jtag.win{fill:var(--pos)} .jtag.lose{fill:var(--neg)} .jtag.now{fill:var(--muted)}
.jpanel.on .jrule,.jpanel.on .jtag{animation:jzone2 .45s var(--ease) 1.3s both}
.jchartdot{fill:var(--accent);stroke:var(--bg);stroke-width:1.6;opacity:0}
.jpanel.on .jchartdot{animation:jpop .4s var(--ease) 1.25s both}
@keyframes jpop{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:none}}
.joutcomes{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}
.jout{flex:1 1 150px;display:flex;flex-direction:column;gap:2px;padding:9px 12px;
  border-radius:8px;opacity:0}
.jout i{font-style:normal;font-size:11px;font-weight:500;color:var(--muted)}
.jout b{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums}
.jout.win{background:color-mix(in srgb,var(--pos) 10%,transparent);color:var(--pos)}
.jout.lose{background:color-mix(in srgb,var(--neg) 10%,transparent);color:var(--neg)}
.jpanel.on .jout{animation:jrise .45s var(--ease) both}
.jpanel.on .jout.win{animation-delay:1.6s}
.jpanel.on .jout.lose{animation-delay:1.78s}

/* step 6 — the press */
.jact{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.jbtn{position:relative;display:inline-flex;align-items:center;
  justify-content:center;padding:11px 20px;border-radius:8px;font-size:13.5px;
  font-weight:600;border:1px solid var(--line)}
.jbtn.primary{background:var(--accent);color:#fff;border-color:transparent}
.jbtn.ghost{background:transparent;color:var(--muted)}
.jpanel.on .jbtn.primary{animation:jpress 1.5s var(--ease) .55s both}
@keyframes jpress{0%,44%{transform:none;box-shadow:var(--elev-1)}
  52%{transform:scale(.965);box-shadow:var(--elev-1)}
  62%,100%{transform:none;box-shadow:var(--elev-2)}}
.jtap{position:absolute;left:50%;top:50%;width:14px;height:14px;
  margin:-7px 0 0 -7px;border-radius:50%;border:2px solid #fff;opacity:0}
.jpanel.on .jtap{animation:jtap 1s var(--ease) .95s both}
@keyframes jtap{0%{opacity:.85;transform:scale(.3)}100%{opacity:0;transform:scale(4.2)}}

/* step 7 — the record, unflattering side first */
.jstats{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.jstat{border:1px solid var(--line);border-radius:9px;padding:11px 13px;
  background:var(--bg);display:flex;flex-direction:column;gap:2px;opacity:0}
.jpanel.on .jstat{animation:jrise .45s var(--ease) both;
  animation-delay:calc(.15s + var(--i) * .16s)}
.jsv{font-size:23px;font-weight:650;letter-spacing:-0.02em;
  font-variant-numeric:tabular-nums}
.jsl{font-size:12px;color:var(--ink)}
.jsn{font-size:11px;color:var(--muted)}

/* progress + the way out */
.jfootbar{border-top:1px solid var(--line);padding:0}
.jprogress{height:3px;background:var(--tag)}
.jprogress span{display:block;height:100%;width:0;background:var(--accent);
  border-radius:0 3px 3px 0}
.jcta{display:flex;gap:9px;flex-wrap:wrap;align-items:center;padding:13px 18px;
  background:color-mix(in srgb,var(--tag) 40%,transparent)}
/* Outranks button.exec.big's full-width rule: these two sit side by side. */
.jcta button.exec{width:auto;flex:0 0 auto}
.jcta button.exec.big{padding:11px 18px;font-size:13.5px}

.journey.collapsed .jbody,.journey.collapsed .jfootbar{display:none}

@media (max-width:760px){
  .jbody{grid-template-columns:1fr}
  .jrail{flex-direction:row;overflow-x:auto;border-right:0;
    border-bottom:1px solid var(--line);padding:8px;
    scrollbar-width:none}
  .jrail::-webkit-scrollbar{display:none}
  .jrail li{flex:0 0 auto}
  .jrail button{padding:6px 10px}
  .jrail-label{display:none}
  .jrail button[aria-selected="true"] .jrail-label{display:inline}
  .jstage{padding:16px 15px 18px;min-height:0}
  .jhead{font-size:17px}
  .jbar{flex-direction:column;gap:10px}
  .jctl{align-self:stretch}
  .jbtnctl{flex:1 1 0;justify-content:center}
}

/* A reader who has asked for no motion gets the whole thing as a document:
   every step open, nothing playing, no controls that only make sense for a
   thing that moves. */
@media (prefers-reduced-motion:reduce){
  .journey *,.journey *::before,.journey *::after{
    animation:none !important;transition:none !important}
  .jpanel .jkey,.jpanel .jreceipt,.jpanel .jfunnel,.jpanel .jlimits li,
  .jpanel .jstat,.jpanel .jout,.jpanel .jtick,.jpanel .jzone,
  .jpanel .jchartarea,.jpanel .jrule,.jpanel .jtag,.jpanel .jchartdot,
  .jpanel .jstackslice{opacity:1}
  .jpanel .jzone{opacity:.09}
  .jpanel .jchartline{stroke-dashoffset:0}
  .jcaret,.jsweep,.jtap{display:none}
}
.journey.static .jpanel[hidden]{display:flex}
.journey.static .jpanel{border-top:1px solid var(--line);padding-top:16px;
  margin-top:16px}
.journey.static .jpanel:first-child{border-top:0;padding-top:0;margin-top:0}
.journey.static .jrail,.journey.static .jprogress,
.journey.static [data-journey-toggle]{display:none}
/* The rail is the first grid column; dropping it must give the stage the full
   width back rather than leaving it in a 210px lane. */
.journey.static .jbody{grid-template-columns:1fr}
"""


# ---------------------------------------------------------------------------
# The walkthrough.
#
# A dashboard that opens on a wall of finished numbers answers a question the
# first-time reader has not asked yet. Before "how did it do" comes "what does
# this thing do for me, and where do I come into it" — and that is a sequence,
# not a statistic, so it is shown as one: seven steps from the reader's own
# amount through to an honest report of what the strategy actually did.
#
# Three rules keep it from being an advert.
#
# 1. Every number in it is read from the snapshot and the report. The names in
#    the scan are the real watchlist, the funnel counts are today's real
#    counts, the chart is the real signal's real price history, and the closing
#    stats are the real ones — including the losing ones.
# 2. It plays once and stops. The page's motion rule is that nothing loops on
#    its own beside live numbers; a walkthrough that restarts forever would be
#    exactly that. It runs a single pass and rests on the last step.
# 3. It never blocks the app. Without JavaScript every step is on the page as
#    plain readable content; under prefers-reduced-motion it renders as that
#    same static list with no autoplay at all.
# ---------------------------------------------------------------------------

#: (rail label, step heading) — the rail label is what a returning reader scans.
JOURNEY_STEPS: tuple[tuple[str, str], ...] = (
    ("Your amount", "First, it needs to know what you are working with"),
    ("The close", "Every market close, it re-reads the whole list"),
    ("The filter", "Rules cut the list down to what actually qualifies"),
    ("The size", "Risk decides the size before you get a say"),
    ("The trade", "The exit is written at the same moment as the entry"),
    ("Your call", "Nothing happens until you press something"),
    ("The truth", "Then it shows you what it really did, losses included"),
)

#: Milliseconds each step holds before the walkthrough advances. Longer where
#: there is more to read; the JS reads these off the DOM so copy and pacing
#: cannot drift apart.
JOURNEY_HOLDS: tuple[int, ...] = (5200, 5600, 6000, 6400, 7000, 5800, 6400)


def _journey_chart(order: dict, *, width: int = 460, height: int = 150) -> str:
    """The signal's real price history with its stop and target drawn on it.

    The gutter on the right is reserved for the three price labels, so the
    plot is narrower than the SVG. Levels outside the plotted range are still
    included in the y-scale, which is the point: if the target is far away,
    the picture has to show it as far away.
    """
    points = [float(v) for v in (order.get("spark") or []) if v is not None]
    if len(points) < 2:
        return ""

    def level(key: str) -> float | None:
        raw = order.get(key)
        return None if raw in (None, "") else float(str(raw))

    stop, target = level("stop_loss"), level("take_profit")
    entry = level("reference_price") or points[-1]
    marks = [v for v in (stop, target, entry) if v is not None]
    lo, hi = min(points + marks), max(points + marks)
    if hi == lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.10
    lo, hi = lo - pad, hi + pad
    span, plot, n = hi - lo, width - 92, len(points)

    def x_at(i: int) -> float:
        return i * plot / (n - 1)

    def y_at(value: float) -> float:
        return height - ((value - lo) / span * height)

    line = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(points))
    area = f"0,{height:.1f} {line} {plot:.1f},{height:.1f}"

    zones, rules = [], []
    if target is not None:
        y = y_at(target)
        zones.append(f'<rect class="jzone win" x="0" y="0" width="{plot:.1f}" '
                     f'height="{max(y, 0):.1f}"/>')
        rules.append((y, "win", "target", target))
    if stop is not None:
        y = y_at(stop)
        zones.append(f'<rect class="jzone lose" x="0" y="{y:.1f}" width="{plot:.1f}" '
                     f'height="{max(height - y, 0):.1f}"/>')
        rules.append((y, "lose", "stop", stop))
    rules.append((y_at(entry), "now", "entry", entry))

    marks_svg = []
    for y, cls, label, value in rules:
        marks_svg.append(
            f'<line class="jrule {cls}" x1="0" y1="{y:.1f}" x2="{plot:.1f}" y2="{y:.1f}"/>'
            f'<text class="jtag {cls}" x="{plot + 7:.1f}" y="{y + 3.4:.1f}">'
            f"{_esc(label)} {_price(value)}</text>"
        )

    dot_x, dot_y = x_at(n - 1), y_at(points[-1])
    return f"""<svg class="jchart" viewBox="0 0 {width} {height}" role="img"
     aria-label="{_esc(order['symbol'])} closing prices, with the stop and target
     the strategy set for this trade">
  {''.join(zones)}
  <polygon class="jchartarea" points="{area}"/>
  <polyline class="jchartline" points="{line}" pathLength="1"
            vector-effect="non-scaling-stroke"/>
  {''.join(marks_svg)}
  <circle class="jchartdot" cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="3.4"/>
</svg>"""


def _journey_amount(signals: dict) -> str:
    """Step 1: the amount being typed into the field the reader will use."""
    digits = "".join(
        f'<span class="jkey" style="--i:{i}">{ch}</span>'
        for i, ch in enumerate("1,00,000")
    )
    return f"""<div class="jfield">
  <span class="jflabel">Your amount &middot; India (&#8377;)</span>
  <span class="jfbox">{digits}<span class="jcaret"></span></span>
</div>
<div class="jreceipt">
  <span class="jdot ok"></span>Saved. Every figure on the page is now yours.
</div>
<ul class="jnotes">
  <li><strong>Two amounts, one per market.</strong> India in rupees, the US in
    dollars. Leave either blank and that market simply stops suggesting.</li>
  <li><strong>A daily limit, set beside it.</strong> The most you are willing to
    commit in a single day. Left blank it defaults to 30% of your amount, and
    it is enforced on paper trades exactly as on real ones &mdash; so you find
    out where it bites before money is involved.</li>
  <li><strong>Everything downstream is a percentage of this.</strong> Change the
    amount and every share count, cost and outcome on the page is recomputed
    from it.</li>
</ul>
<p class="jmeta">It never leaves this browser &mdash; there is no account and
nowhere for it to go. Clearing site data clears it.</p>"""


def _journey_scan(signals: dict) -> str:
    """Step 2: the real watchlist lighting up under a scan."""
    watchlist = signals.get("watchlist") or []
    mech = signals.get("mechanics") or {}
    chips = "".join(
        f'<span class="jtick" style="--i:{i}">{_esc(row["symbol"])}</span>'
        for i, row in enumerate(watchlist)
    ) or '<span class="jtick" style="--i:0">watchlist unavailable</span>'
    as_of = " &middot; ".join(
        f"{REGION_NAMES.get(REGION_CODE_BY_NAME.get(region, ''), region.title())} "
        f"through {_esc(day)}"
        for region, day in sorted((signals.get("as_of") or {}).items())
    )
    return f"""<div class="jscan"><span class="jsweep"></span>
  <div class="jgrid">{chips}</div>
</div>
<p class="jmeta"><strong>{mech.get('names', len(watchlist))}</strong> names
&middot; <strong>{mech.get('regions', 0)}</strong> markets &middot;
<strong>{mech.get('sessions', 0)}</strong> sessions of history re-scored from
scratch, every close.{' ' + as_of if as_of else ''}</p>
<ul class="jnotes">
  <li><strong>What runs:</strong> a scheduled job fetches every name's closing
    prices after the Indian close and again after the US close, commits them,
    and that commit rebuilds this page. There is no server kept alive between
    times.</li>
  <li><strong>What is recomputed:</strong> moving averages, RSI, ADX, ATR and
    volume averages &mdash; from the raw bars each time, never carried over
    from yesterday's answer.</li>
  <li><strong>What it cannot see:</strong> only completed sessions are used. A
    bar still forming is dropped, so no rule is ever evaluated against a price
    that had not settled.</li>
</ul>"""


def _journey_filter(signals: dict) -> str:
    """Step 3: how many survive, as bars in proportion to each other."""
    orders = signals.get("orders", [])
    mech = signals.get("mechanics") or {}
    names = int(mech.get("names") or 0) or 1
    tracked, fresh = len(orders), sum(1 for o in orders if o["fresh"])
    stages = (
        ("Names read", names, "everything on the watchlist"),
        ("Setups the strategies are holding", tracked, "including yesterday's, still resting"),
        ("Worth acting on today", fresh, "what reaches you"),
    )
    bars = "".join(
        f"""<div class="jfunnel" style="--i:{i}">
  <span class="jfl">{_esc(label)}</span>
  <span class="jftrack"><span class="jffill"
        style="--w:{max(count / names * 100, 2.5):.1f}%"></span></span>
  <span class="jfn">{count}</span>
  <span class="jfnote">{_esc(note)}</span>
</div>"""
        for i, (label, count, note) in enumerate(stages)
    )
    # The rules themselves, quoted from the running strategies. "Rules cut the
    # list down" is not an explanation unless it says which rules.
    cards = ""
    for i, rule in enumerate(mech.get("rules") or []):
        tests = "".join(
            f"<li>{_esc(test)}</li>" for test in rule.get("tests", [])
        )
        cards += f"""<div class="jrule-card" style="--i:{i}">
  <span class="jrule-book">{_esc(rule.get('book', ''))}</span>
  <strong class="jrule-name">{_esc(rule.get('name', ''))}</strong>
  <p class="jrule-lead">All of these must be true on the same day:</p>
  <ul class="jrule-tests">{tests}</ul>
  <p class="jrule-exit"><span class="jrule-exitlabel">Exit</span>
    {_esc(rule.get('exit', ''))}</p>
</div>"""
    rules_block = f'<div class="jrules">{cards}</div>' if cards else ""

    return f"""{bars}
{rules_block}
<p class="jmeta">Every test is measured on closing prices only, so a name either
qualified at the close or it did not &mdash; there is no discretion left in it.
Most days the last number is small, and plenty of days it is zero. A list that
always has something on it is a list that stopped filtering.</p>"""


def _journey_size(signals: dict) -> str:
    """Step 4: the caps that decide the quantity, quoted from the live run."""
    mech = signals.get("mechanics") or {}

    def frac(key: str, places: int = 2) -> str:
        raw = mech.get(key)
        return "&mdash;" if raw in (None, "") else f"{float(str(raw)) * 100:.{places}f}%"

    weight = mech.get("max_position_weight")
    slice_pct = f"{float(str(weight)) * 100:.0f}" if weight else "12"
    limits = (
        (frac("risk_per_trade"), "of the book is risked on any one trade &mdash; "
                                 "the distance to the stop sets the quantity"),
        (frac("max_position_weight", 0), "is the most that can sit in a single name"),
        (str(mech.get("max_open_positions") or "&mdash;"), "open positions at once, "
                                                           "no more"),
        (frac("daily_loss_limit", 0), "lost in a day and it stops trading until "
                                      "tomorrow"),
    )
    rows = "".join(
        f'<li style="--i:{i}"><strong>{value}</strong> {note}</li>'
        for i, (value, note) in enumerate(limits)
    )
    return f"""<div class="jstack" aria-hidden="true">
  <span class="jstackfill"></span>
  <span class="jstackslice" style="--w:{slice_pct}%"><i>{slice_pct}%</i></span>
</div>
<ul class="jlimits">{rows}</ul>
<div class="jworked">
  <span class="jworkedlabel">How that becomes a share count</span>
  <ol class="jsteps">
    <li>Take the risk budget: <strong>{frac('risk_per_trade')}</strong> of the
      book is what this trade may lose.</li>
    <li>Measure the distance from the entry price down to the stop &mdash; set
      by recent volatility, not by preference.</li>
    <li>Divide one by the other. That is the quantity, and it is the whole
      calculation.</li>
    <li>Then clip it: never more than <strong>{frac('max_position_weight', 0)}</strong>
      in one name, never past your daily limit, never more of a day's volume
      than the book could realistically buy.</li>
  </ol>
  <p class="jworkednote">A wider stop therefore buys <em>fewer</em> shares, not
  more. Two trades that look different on the chart put the same amount at
  risk.</p>
</div>
<p class="jmeta">You cannot talk the sizing into a bigger position. It is the
same code that sized every trade in the track record below.</p>"""


def _journey_past_trade(report: PerformanceReport | None) -> str:
    """A finished trade, shown when there is nothing live to show.

    Deliberately picks the most recent completed trade rather than the best
    one. A walkthrough that reaches for its winner on a quiet day is selling,
    and the whole point of the last step is that it does not.
    """
    trades = list(getattr(report, "trades", []) or []) if report else []
    if not trades:
        return """<p class="jempty">There is no live suggestion right now, which
is the ordinary case. When one appears it arrives with its exit already
attached: a price to take the gain at, a price to cut the loss at, and a
deadline after which it is closed either way.</p>"""

    trade = max(trades, key=lambda t: t.exit_day)
    won = trade.net_pnl >= 0
    held = (trade.exit_day - trade.entry_day).days
    ending = EXIT_LABELS.get(trade.exit_reason, trade.exit_reason)
    symbol = trade.key.split(":")[-1]
    return f"""<div class="jtrade past">
  <div class="jtradehead">
    <span class="tag">Closed</span>
    <strong>{_esc(symbol)}</strong>
    <span class="muted-inline">most recent completed trade</span>
  </div>
  <div class="jpastgrid">
    <span class="jpast"><i>Bought</i><b>{_price(trade.entry_price)}</b>
      <u>{_esc(trade.entry_day)}</u></span>
    <span class="jpast"><i>Sold</i><b>{_price(trade.exit_price)}</b>
      <u>{_esc(trade.exit_day)}</u></span>
    <span class="jpast"><i>Held</i><b>{held}</b><u>days</u></span>
    <span class="jpast {'win' if won else 'lose'}"><i>Result</i>
      <b>{'+' if won else '&minus;'}{_money(abs(trade.net_pnl))}</b>
      <u>{_esc(trade.currency)}</u></span>
  </div>
  <p class="jpastend"><span class="jdot {'ok' if won else 'bad'}"></span>
    Ended on: {_esc(ending)}</p>
</div>
<p class="jmeta">No suggestion is live at the moment, so this is a real trade
the strategies already finished &mdash; the most recent one, win or lose, not
the best one. A live suggestion looks the same, except the exit prices are
still ahead of it instead of behind.</p>"""


def _journey_trade(signals: dict, report: PerformanceReport | None = None) -> str:
    """Step 5: a real trade, with the exit levels it was born with.

    Most days there is no live suggestion — that is the ordinary case, and the
    step used to degrade to a paragraph on exactly those days. It now falls
    back to a real completed trade from the track record, so the reader always
    sees an actual entry, its stop, its target and how it ended rather than a
    description of one.
    """
    orders = signals.get("orders", [])
    order = next((o for o in orders if o["fresh"]), orders[0] if orders else None)
    if order is None:
        return _journey_past_trade(report)

    ccy = order["currency"]
    chart = _journey_chart(order)
    hold = order.get("max_holding_days")
    window = f"closed within {hold} trading days either way" if hold else \
        "closed when the exit signal fires"
    return f"""<div class="jtrade">
  <div class="jtradehead">
    <span class="tag {'side-buy' if order['side'] == 'BUY' else 'side-sell'}"
      >{_esc(order['side'])}</span>
    <strong>{_esc(order['symbol'])}</strong>
    <span class="muted-inline">{_esc(order['name'])}</span>
  </div>
  {chart}
  <div class="joutcomes">
    <span class="jout win"><i>If the target hits</i><b>{
      _money_line(order.get('profit_at_target'), ccy, signed=True)}</b></span>
    <span class="jout lose"><i>If the stop hits</i><b>&minus;{
      _money_line(order.get('loss_at_stop'), ccy)}</b></span>
  </div>
</div>
<p class="jmeta"><strong>Why this one:</strong>
{_esc(plain_reason(order.get('reason') or ''))}. It is
{window}. Both figures above are the strategy's own size &mdash; enter your
amount and they are restated in your money.</p>"""


def _journey_act(signals: dict) -> str:
    """Step 6: the two-step, reversible-first action model, acted out."""
    return """<div class="jact">
  <span class="jbtn primary">Paper buy<span class="jtap"></span></span>
  <span class="jbtn ghost">Real &middot; broker</span>
</div>
<div class="jreceipt delayed">
  <span class="jdot ok"></span>Added to your paper book. Nothing was sent
  anywhere, and nothing was spent.
</div>
<div class="jtiers">
  <div class="jtier" style="--i:0">
    <span class="jtierhead"><span class="jdot ok"></span>Paper</span>
    <p>Costs nothing, reaches no broker, needs no account. Recorded in this
    browser and reversible &mdash; sell it back or reset the book.</p>
  </div>
  <div class="jtier" style="--i:1">
    <span class="jtierhead"><span class="jdot"></span>Hand off to your broker</span>
    <p>Opens your own broker with the order pre-filled. You review it and
    confirm it there. Nothing is placed by this page.</p>
  </div>
  <div class="jtier" style="--i:2">
    <span class="jtierhead"><span class="jdot"></span>Capped auto-execute</span>
    <p>Off unless you add your own broker keys, and paper-only until you
    explicitly arm it. The daily limit is checked against the broker's own
    order log, not against what this page believes.</p>
  </div>
</div>
<p class="jmeta">Paper is the default because it is the reversible one. Every
route past it asks twice, is capped by the daily limit you set in step one, and
stops at a confirmation you give. This page never holds a credential &mdash;
keys live in the deployment environment and are never readable from here.</p>"""


def _journey_truth(report: PerformanceReport) -> str:
    """Step 7: the closing stats, chosen so the unflattering ones lead."""
    stats = (
        (f"{_pct(report.win_rate, 1)}", "of trades finished ahead",
         "so most of them did not"),
        (f"-{_pct(report.max_drawdown)}", "worst peak-to-trough fall",
         f"{report.max_drawdown_days} days to get back"),
        (f"{report.max_consecutive_losses}", "losses in a row, at worst",
         "this is what you would have had to sit through"),
        (_signed_pct(report.total_return), "over the period on test",
         "before you decide anything"),
    )
    tiles = "".join(
        f"""<div class="jstat" style="--i:{i}">
  <span class="jsv {'neg' if value.startswith(('-', '&minus;')) else ''}">{value}</span>
  <span class="jsl">{_esc(label)}</span>
  <span class="jsn">{_esc(note)}</span>
</div>"""
        for i, (value, label, note) in enumerate(stats)
    )
    return f"""<div class="jstats">{tiles}</div>
<p class="jmeta">Nothing here is a promise. The full record &mdash; every
market, every book, and how each trade ended &mdash; is under
<button type="button" class="linkish" data-tabgo="performance">Track
record</button>.</p>"""


def _journey_section(report: PerformanceReport, signals: dict) -> str:
    """The whole walkthrough: rail, stage, progress and the way out of it."""
    fresh = sum(1 for order in signals.get("orders", []) if order["fresh"])
    arts = (
        _journey_amount(signals),
        _journey_scan(signals),
        _journey_filter(signals),
        _journey_size(signals),
        _journey_trade(signals, report),
        _journey_act(signals),
        _journey_truth(report),
    )
    says = (
        "Two numbers, kept in this browser: what you invest with in India, and "
        "what you invest with in the US. Everything downstream is sized from "
        "them, so until they exist the page is showing you somebody else's "
        "money.",
        "After each close it reloads every name on the list, recomputes every "
        "indicator from the raw bars, and re-runs both strategies over the "
        "whole history. No name gets a pass because it was interesting "
        "yesterday.",
        "A trend filter, a momentum ranking, a pullback rule and a breakout "
        "rule each get a vote, and the risk limits get a veto. What survives "
        "all of that is what you see.",
        "The stop distance and the caps below decide the quantity between "
        "them. This is the part that keeps one bad day from being the last "
        "one, and it is not negotiable from the interface.",
        "You are handed the entry, the target, the stop and the deadline "
        "together, before anything is bought. Knowing what you lose if it goes "
        "wrong is the whole point of the exercise.",
        "Paper buy simulates the fill in this browser. The real handoff is a "
        "separate, deliberate, twice-confirmed action into your own broker. "
        "You are the one who decides; the app never trades for you.",
        "Win rate, worst drawdown, longest losing streak, and the return on "
        "the period tested — the numbers a system with something to hide "
        "would bury.",
    )
    panels = []
    tabs = []
    steps = zip(JOURNEY_STEPS, says, arts, strict=True)
    for i, ((rail, head), say, art) in enumerate(steps):
        selected = "true" if i == 0 else "false"
        tabs.append(
            f'<li><button type="button" role="tab" id="jtab-{i}" data-jgo="{i}" '
            f'aria-controls="jpanel-{i}" aria-selected="{selected}" '
            f'tabindex="{0 if i == 0 else -1}">'
            f'<span class="jnum">{i + 1}</span>'
            f'<span class="jrail-label">{_esc(rail)}</span></button></li>'
        )
        panels.append(
            f'<div class="jpanel" role="tabpanel" id="jpanel-{i}" '
            f'aria-labelledby="jtab-{i}" data-jpanel="{i}" '
            f'data-jhold="{JOURNEY_HOLDS[i]}" tabindex="0">'
            f'<p class="jkicker">Step {i + 1} of {len(JOURNEY_STEPS)}</p>'
            f"<h3 class=\"jhead\">{_esc(head)}</h3>"
            f'<p class="jsay">{_esc(say)}</p>'
            f'<div class="jart">{art}</div></div>'
        )
    cta_trades = (
        f'<button type="button" class="exec ghost" data-tabgo="invest">'
        f"See today&rsquo;s {fresh} suggestion{'' if fresh == 1 else 's'}</button>"
        if fresh
        else '<button type="button" class="exec ghost" data-tabgo="invest">'
             "See the pending list</button>"
    )
    return f"""<section class="journey" data-journey aria-labelledby="jtitle">
  <div class="jbar">
    <div>
      <h2 class="jtitle" id="jtitle">How a suggestion reaches you</h2>
      <p class="jlede" data-journey-lede>Seven steps, about forty seconds. It
      plays itself &mdash; pause it, or jump to any step.</p>
    </div>
    <div class="jctl">
      <button type="button" class="jbtnctl" data-journey-toggle
              aria-label="Pause the walkthrough">
        <span class="jicon" data-journey-icon aria-hidden="true"></span>
        <span data-journey-toggle-label>Pause</span>
      </button>
      <button type="button" class="jbtnctl" data-journey-collapse
              aria-expanded="true" aria-controls="jbody">Hide</button>
    </div>
  </div>
  <div class="jbody" id="jbody">
    <ol class="jrail" role="tablist" aria-label="Walkthrough steps"
        aria-orientation="vertical">{''.join(tabs)}</ol>
    <div class="jstage">{''.join(panels)}</div>
  </div>
  <div class="jfootbar">
    <div class="jprogress" data-journey-progress aria-hidden="true">
      <span data-journey-bar></span>
    </div>
    <div class="jcta">
      <button type="button" class="exec big" data-journey-start>Start with my
      amount</button>
      {cta_trades}
    </div>
  </div>
</section>"""


#: Drives the walkthrough: one pass, pausable, jumpable, and entirely optional.
#:
#: The panels ship visible so the steps are readable with no JavaScript at all;
#: this script is what turns that list into a player. It refuses to start under
#: prefers-reduced-motion, refuses to run while off-screen or on a hidden tab,
#: and stops for good at the last step rather than looping.
JOURNEY_JS = """
(function () {
  var root = document.querySelector('[data-journey]');
  if (!root) return;

  var panels = [].slice.call(root.querySelectorAll('[data-jpanel]'));
  var tabs = [].slice.call(root.querySelectorAll('[data-jgo]'));
  if (!panels.length || panels.length !== tabs.length) return;

  var bar = root.querySelector('[data-journey-bar]');
  var toggle = root.querySelector('[data-journey-toggle]');
  var toggleLabel = root.querySelector('[data-journey-toggle-label]');
  var collapse = root.querySelector('[data-journey-collapse]');
  var body = root.querySelector('.jbody');
  var reduced = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SEEN = 'markets-pro.journey.v1';

  // Static mode: every step open, no player. Chosen for readers who asked for
  // no motion, and it is also what the page falls back to if anything below
  // throws, because a readable list beats a broken carousel.
  if (reduced) {
    root.classList.add('static');
    return;
  }

  var index = 0, timer = null, playing = false, finished = false;
  var startedAt = 0, remaining = 0;

  function holdOf(i) {
    return Number(panels[i].getAttribute('data-jhold')) || 5000;
  }

  function paint(width, ms) {
    if (!bar) return;
    bar.style.transition = 'none';
    bar.style.width = width;
    if (ms) {
      void bar.offsetWidth;                 // commit the reset before easing
      bar.style.transition = 'width ' + ms + 'ms linear';
      bar.style.width = '100%';
    }
  }

  function show(i) {
    index = i;
    panels.forEach(function (panel, n) {
      var active = n === i;
      panel.hidden = !active;
      panel.classList.remove('on');
      if (active) {
        void panel.offsetWidth;             // restart this step's animations
        panel.classList.add('on');
      }
    });
    tabs.forEach(function (tab, n) {
      tab.setAttribute('aria-selected', n === i ? 'true' : 'false');
      tab.setAttribute('tabindex', n === i ? '0' : '-1');
      tab.classList.toggle('done', n < i);
    });
    keepRailInView();
  }

  // On a phone the rail is a horizontal strip that overflows. Nudging its own
  // scroll (rather than calling scrollIntoView, which would drag the page)
  // keeps the step you are on visible without moving anything else.
  function keepRailInView() {
    var rail = root.querySelector('.jrail');
    if (!rail || rail.scrollWidth <= rail.clientWidth + 1) return;
    var tab = tabs[index];
    rail.scrollTo({
      left: tab.offsetLeft - (rail.clientWidth - tab.offsetWidth) / 2,
      behavior: 'smooth'
    });
  }

  function clear() {
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function schedule(ms) {
    clear();
    startedAt = Date.now();
    remaining = ms;
    paint('0%', ms);
    timer = setTimeout(function () {
      if (index + 1 < panels.length) {
        show(index + 1);
        schedule(holdOf(index));
      } else {
        // One pass, then it rests. Nothing on this page loops on its own.
        finished = true;
        playing = false;
        paint('100%', 0);
        setToggle();
      }
    }, ms);
  }

  function setToggle() {
    if (!toggle) return;
    root.classList.toggle('paused', !playing);
    var label = finished ? 'Replay' : (playing ? 'Pause' : 'Play');
    if (toggleLabel) toggleLabel.textContent = label;
    toggle.setAttribute('aria-label', label + ' the walkthrough');
  }

  function play() {
    if (finished) { finished = false; show(0); }
    playing = true;
    setToggle();
    schedule(remaining && !finished && remaining < holdOf(index)
      ? remaining : holdOf(index));
  }

  function pause() {
    if (playing && timer) {
      remaining = Math.max(holdOf(index) - (Date.now() - startedAt), 400);
      paint(bar ? getComputedStyle(bar).width : '0px', 0);
    }
    playing = false;
    clear();
    setToggle();
  }

  function jump(i) {
    pause();                                 // a reader who steers wants to read
    remaining = 0;
    finished = false;
    show(i);
    paint(String(Math.round(i / (panels.length - 1) * 100)) + '%', 0);
    setToggle();
  }

  show(0);
  paint('0%', 0);
  setToggle();

  tabs.forEach(function (tab, n) {
    tab.addEventListener('click', function () { jump(n); });
  });

  // Roving focus across the rail, as the tablist pattern expects.
  root.querySelector('.jrail').addEventListener('keydown', function (event) {
    var delta = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[event.key];
    var next = null;
    if (delta) next = Math.min(Math.max(index + delta, 0), panels.length - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = panels.length - 1;
    if (next === null) return;
    event.preventDefault();
    jump(next);
    tabs[next].focus();
  });

  if (toggle) {
    toggle.addEventListener('click', function () {
      if (playing) pause(); else play();
    });
  }

  // Reading is not idling. The steps carry real detail — rules, worked sizing,
  // a finished trade — and being advanced mid-sentence loses the reader's
  // place. Resting a pointer on the stage holds the step; moving away resumes,
  // but only if the walkthrough paused itself. A deliberate pause stays paused.
  var stage = root.querySelector('.jstage');
  if (stage) {
    var heldByReader = false;

    stage.addEventListener('pointerenter', function (event) {
      if (event.pointerType === 'touch') return;   // a tap already steers
      if (!playing) return;
      heldByReader = true;
      pause();
    });

    stage.addEventListener('pointerleave', function (event) {
      if (event.pointerType === 'touch') return;
      if (!heldByReader) return;
      heldByReader = false;
      play();
    });

    // Keyboard and screen-reader users get the same courtesy, without the
    // auto-resume: focus moving on is not a signal they finished reading.
    stage.addEventListener('focusin', function () {
      heldByReader = false;
      if (playing) pause();
    });

    // Selecting text is unambiguous intent to read.
    stage.addEventListener('mousedown', function () {
      heldByReader = false;
      if (playing) pause();
    });
  }

  if (collapse && body) {
    var setCollapsed = function (on) {
      root.classList.toggle('collapsed', on);
      collapse.textContent = on ? 'Show me' : 'Hide';
      collapse.setAttribute('aria-expanded', on ? 'false' : 'true');
      if (on) pause();
    };
    collapse.addEventListener('click', function () {
      var next = !root.classList.contains('collapsed');
      setCollapsed(next);
      try { localStorage.setItem(SEEN, next ? 'collapsed' : 'open'); } catch (e) { /* */ }
      if (!next) play();
    });
    var stored = null;
    try { stored = localStorage.getItem(SEEN); } catch (e) { /* blocked */ }
    // Someone who has already set their amount has been through this once;
    // the tour folds itself away rather than making them close it every visit.
    var settled = false;
    try { settled = !!localStorage.getItem('markets-pro.settings.v1'); } catch (e) { /* */ }
    if (stored === 'collapsed' || (stored === null && settled)) setCollapsed(true);
  }

  // Autoplay is opt-out, but only once the thing is actually on screen: a tour
  // that ran itself out while the reader was further down the page is a tour
  // nobody watched.
  var started = false;
  function maybeStart() {
    if (started || root.classList.contains('collapsed')) return;
    started = true;
    play();
  }
  if (typeof IntersectionObserver === 'function') {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { maybeStart(); io.disconnect(); }
      });
    }, {threshold: 0.35});
    io.observe(root);
  } else {
    maybeStart();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) pause();
  });

  var start = root.querySelector('[data-journey-start]');
  if (start) {
    start.addEventListener('click', function () {
      pause();
      var form = document.querySelector('[data-needs-setup]');
      var input = form && !form.hidden
        ? form.querySelector('[data-setting]')
        : null;
      if (!input) {
        var setup = document.querySelector('[data-tabbtn="setup"]');
        if (setup) { setup.click(); window.scrollTo(0, 0); }
        input = document.querySelector('#panel-setup [data-setting]');
      }
      if (input) {
        input.scrollIntoView({block: 'center', behavior: 'smooth'});
        input.focus({preventScroll: true});
      }
    });
  }
})();
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
    screener: dict | None = None,
    funds: dict | None = None,
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
    detail_shell = ""
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
        # Order matters: the walkthrough answers "what is this and where do I
        # come into it", which is the question the reader has before the form
        # asking for their money makes any sense.
        glance = _journey_section(report, signals) + _onboarding(signals) + _glance(signals)
        # The engine's own book is deliberately NOT on this tab. A reader with
        # one paper trade seeing the strategy's three test positions reads them
        # as holdings of theirs; it lives under the track record instead.
        # Assigned before the f-string below consumes it — an f-string is
        # evaluated where it is written, not where its result is used.
        detail_shell = _detail_shell()
        invest_panel = f"""
  <section class="tabpanel" id="panel-invest" data-tab="invest" role="tabpanel" hidden>
    <h2>Today's suggested trades</h2>
    <div class="panel">{_signals_section(signals)}</div>
    <p class="caption">Your own holdings and profit/loss are under
    <button type="button" class="linkish" data-tabgo="paper">Paper</button>.</p>
  </section>

  {detail_shell}

  <section class="tabpanel" id="panel-markets" data-tab="markets"
           role="tabpanel" hidden>
    <h2>Markets</h2>
    <div class="panel">{_market_section(signals)}</div>
  </section>

  <section class="tabpanel" id="panel-screener" data-tab="screener"
           role="tabpanel" hidden>
    <h2>Screener</h2>
    <div class="panel">{_screener_section(screener)}</div>
  </section>

  <section class="tabpanel" id="panel-funds" data-tab="funds"
           role="tabpanel" hidden>
    <h2>Mutual funds</h2>
    <div class="panel">{_funds_section(funds)}</div>
  </section>

  <section class="tabpanel" id="panel-watchlist" data-tab="watchlist"
           role="tabpanel" hidden>
    <h2>Watchlist</h2>
    <div class="panel">{_watchlist_section(signals)}</div>
  </section>

  <section class="tabpanel" id="panel-news" data-tab="news" role="tabpanel" hidden>
    <h2>News</h2>
    <div class="panel">{_news_section(signals)}</div>
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
            # Absolute, not relative: the subdomain serves this document at
            # "/" through a rewrite, so a relative "stocks.json" resolves to
            # /stocks.json and 404s. The path-based URL has the same problem
            # without a trailing slash.
            "data_base": "/markets-pro/",
            "kite_api_key": signals.get("kite_api_key", ""),
            "daily_cap": signals.get("daily_cap", {}),
            "starting_cash": signals.get("starting_cash", {}),
            "usdinr": signals.get("usdinr", ""),
            "orders": signals.get("orders", []),
        }
        # <-escape so no substring can terminate the script element early.
        blob = json.dumps(embedded).replace("<", "\\u003c")
        signal_blob = f'<script type="application/json" id="signals-data">{blob}</script>'
        # The stock index is ~200 KB of JSON that only matters once a reader
        # opens a detail page. Inlining it made every visitor pay for content
        # most never open, so it is written beside the page and fetched on
        # demand; the element carries only its URL.
        signal_blob += (
            '\n<script type="application/json" id="stocks-data" '
            'data-src="stocks.json">{}</script>'
        )
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
            f"<script>{WATCH_NEWS_JS}</script>\n"
            f"<script>{DETAIL_JS}</script>\n"
            f"<script>{FUNDS_JS}</script>\n"
            f"<script>{TILT_JS}</script>\n"
            f"<script>{JOURNEY_JS}</script>"
        )

    dash_label = _tab_label("Today", "Dashboard")
    market_label = _tab_label("Markets", "Markets")
    screen_label = _tab_label("Screen", "Screener")
    funds_label = _tab_label("Funds", "Mutual funds")
    watch_label = _tab_label("List", "Watchlist")
    news_label = _tab_label("News", "News")
    record_label = _tab_label("Record", "Track record")
    setup_label = _tab_label("Setup", "Settings")
    tab_bar = f"""<nav class="tabs" role="tablist" aria-label="Sections">
    <button type="button" role="tab" data-tabbtn="dashboard" aria-selected="true"
            aria-controls="panel-dashboard" class="active">{dash_label}</button>
    {invest_tab}
    <button type="button" role="tab" data-tabbtn="markets" aria-selected="false"
            aria-controls="panel-markets">{market_label}</button>
    <button type="button" role="tab" data-tabbtn="screener" aria-selected="false"
            aria-controls="panel-screener">{screen_label}</button>
    <button type="button" role="tab" data-tabbtn="funds" aria-selected="false"
            aria-controls="panel-funds">{funds_label}</button>
    <button type="button" role="tab" data-tabbtn="watchlist" aria-selected="false"
            aria-controls="panel-watchlist">{watch_label}</button>
    <button type="button" role="tab" data-tabbtn="news" aria-selected="false"
            aria-controls="panel-news">{news_label}</button>
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
<style>{CSS}{SIGNALS_CSS}{JOURNEY_CSS}</style>
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
