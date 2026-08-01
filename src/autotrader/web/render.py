"""Render a :class:`PerformanceReport` to a self-contained HTML dashboard.

No external stylesheets, scripts, fonts or images — the output is one file that
renders identically offline, behind a CSP, or served from any static host. The
equity chart is inline SVG generated from the data, not a charting library.
"""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal
from typing import Sequence

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
        zip((0, n // 2, n - 1), anchors, x_positions)
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
) -> str:
    """Return a complete, self-contained HTML document for ``report``."""
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
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <p class="sub">{sub}</p>
  </header>

  <div class="notice">
    <p><strong>Simulated results.</strong> These figures come from a backtest, not
    from live trading. Costs, taxes, slippage and venue rules are modelled, and
    the engine is verified free of lookahead &mdash; but past performance on
    historical data does not predict future returns, and no strategy here
    guarantees a profit. Nothing on this page is investment advice.</p>
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

  <h2>By market</h2>
  <div class="panel">{_region_table(report)}</div>

  <h2>By book</h2>
  <div class="panel">{_horizon_table(report)}</div>

  <h2>How trades ended</h2>
  <div class="panel">{_exit_breakdown(report)}</div>

  <h2>Recent round trips</h2>
  <div class="panel">{_trades_table(report)}</div>

  <footer>
    {verified}generated by <code>autotrader</code> &middot;
    equity {_money(report.starting_equity)} &rarr;
    {_money(report.ending_equity, report.base_currency)}
  </footer>
</div>
<script>{ZOOM_JS}</script>
</body>
</html>"""
