"""Persisting backtest results to Postgres/Supabase.

Two halves, deliberately separated:

* :func:`report_to_rows` is pure — it turns a report into plain dicts and has no
  network, no credentials and no side effects, so it is fully unit-testable.
* :class:`SupabaseWriter` does the I/O over the PostgREST endpoint using only
  the standard library.

Credentials are read from the environment (``SUPABASE_URL``,
``SUPABASE_SERVICE_KEY``) and never written to disk or logged. Nothing in this
module accepts a key as a literal for that reason.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from ..engine.metrics import PerformanceReport

#: Every table is prefixed so it cannot collide with anything already in a
#: shared project's `public` schema.
TABLE_PREFIX = "mkt_"

RUNS = f"{TABLE_PREFIX}backtest_runs"
EQUITY = f"{TABLE_PREFIX}equity_curve"
TRADES = f"{TABLE_PREFIX}trades"
POSITIONS = f"{TABLE_PREFIX}positions"
INSTRUMENTS = f"{TABLE_PREFIX}instruments"
REGION_STATS = f"{TABLE_PREFIX}region_stats"

ALL_TABLES = (RUNS, EQUITY, TRADES, POSITIONS, INSTRUMENTS, REGION_STATS)


def _num(value: Any) -> float | None:
    """Convert Decimal/float to a JSON-safe float, preserving ``None``."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _finite(value: float | None) -> float | None:
    """Postgres ``numeric`` rejects inf/NaN; map them to ``None``.

    Profit factor is legitimately infinite when a run has no losing trades, so
    this is a real case rather than a defensive nicety.
    """
    if value is None:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def new_run_id() -> str:
    return str(uuid.uuid4())


@dataclass
class RunMetadata:
    """Descriptive context stored alongside a run's numbers."""

    label: str
    strategy_names: Sequence[str] = ()
    regions: Sequence[str] = ()
    notes: str = ""
    created_at: datetime | None = None

    def timestamp(self) -> str:
        moment = self.created_at or datetime.now(timezone.utc)
        return moment.isoformat()


def report_to_rows(
    report: PerformanceReport,
    metadata: RunMetadata,
    *,
    run_id: str | None = None,
    positions: Iterable[Any] = (),
    instruments: Iterable[Any] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Flatten a :class:`PerformanceReport` into per-table row lists."""
    run_id = run_id or new_run_id()

    run_row = {
        "id": run_id,
        "label": metadata.label,
        "created_at": metadata.timestamp(),
        "start_day": _iso(report.start_day),
        "end_day": _iso(report.end_day),
        "base_currency": report.base_currency,
        "strategies": list(metadata.strategy_names),
        "regions": list(metadata.regions),
        "starting_equity": _num(report.starting_equity),
        "ending_equity": _num(report.ending_equity),
        "total_return": _finite(report.total_return),
        "cagr": _finite(report.cagr),
        "annual_volatility": _finite(report.annual_volatility),
        "sharpe": _finite(report.sharpe),
        "sortino": _finite(report.sortino),
        "max_drawdown": _finite(report.max_drawdown),
        "max_drawdown_days": report.max_drawdown_days,
        "calmar": _finite(report.calmar),
        "total_trades": report.total_trades,
        "win_rate": _finite(report.win_rate),
        "profit_factor": _finite(report.profit_factor),
        "expectancy": _finite(report.expectancy),
        "average_win": _finite(report.average_win),
        "average_loss": _finite(report.average_loss),
        "max_consecutive_losses": report.max_consecutive_losses,
        "total_costs": _num(report.total_costs),
        "total_fills": report.total_fills,
        "rejections": report.rejections,
        "notes": metadata.notes,
    }

    equity_rows = [
        {
            "run_id": run_id,
            "day": _iso(day),
            "equity": _num(value),
        }
        for day, value in zip(report.equity_days, report.equity_values)
    ]

    trade_rows = [
        {
            "run_id": run_id,
            "instrument_key": t.key,
            "region": t.region,
            "horizon": t.horizon,
            "currency": t.currency,
            "entry_day": _iso(t.entry_day),
            "exit_day": _iso(t.exit_day),
            "entry_price": _num(t.entry_price),
            "exit_price": _num(t.exit_price),
            "quantity": _num(t.quantity),
            "gross_pnl": _num(t.gross_pnl),
            "costs": _num(t.costs),
            "net_pnl": _num(t.net_pnl),
            # Local-currency P&L is what changed hands; the base-currency value
            # is the only one that can be summed across regions.
            "base_currency": t.base_currency,
            "fx_rate": _num(t.fx_rate),
            "net_pnl_base": _num(t.net_pnl_base),
            "is_win": t.is_win,
            "holding_days": t.holding_days,
            "return_pct": _finite(t.return_pct),
            "exit_reason": t.exit_reason,
        }
        for t in report.trades
    ]

    position_rows = [
        {
            "run_id": run_id,
            "instrument_key": p.key,
            "symbol": p.symbol,
            "region": p.region,
            "currency": p.currency,
            "quantity": _num(p.quantity),
            "average_cost": _num(p.average_cost),
            "last_price": _num(p.last_price),
            "market_value": _num(p.market_value.amount),
            "unrealized_pnl": _num(p.unrealized_pnl.amount),
            "realized_pnl": _num(p.realized_pnl.amount),
            "weight": _finite(p.weight),
            "opened_on": _iso(p.opened_on),
        }
        for p in positions
    ]

    instrument_rows = [
        {
            "key": i.key,
            "symbol": i.symbol,
            "region": i.region,
            "asset_class": i.asset_class.value,
            "currency": i.currency,
            "tick_size": _num(i.tick_size),
            "lot_size": _num(i.lot_size),
            "multiplier": _num(i.multiplier),
            "name": i.name,
            "sector": i.sector,
        }
        for i in instruments
    ]

    region_rows = [
        {
            "run_id": run_id,
            "region": region,
            "trades": int(stats.get("trades", 0)),
            "net_pnl": _finite(stats.get("net_pnl")),
            "win_rate": _finite(stats.get("win_rate")),
        }
        for region, stats in sorted(report.by_region.items())
    ]

    return {
        RUNS: [run_row],
        EQUITY: equity_rows,
        TRADES: trade_rows,
        POSITIONS: position_rows,
        INSTRUMENTS: instrument_rows,
        REGION_STATS: region_rows,
    }


class SupabaseWriter:
    """Minimal PostgREST client — insert and upsert only.

    Uses ``urllib`` rather than a dependency so the package stays install-free.
    Rows are chunked because PostgREST will reject very large single payloads.
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        chunk_size: int = 500,
        timeout: int = 30,
    ) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        self.chunk_size = chunk_size
        self.timeout = timeout
        if not self.url or not self.key:
            raise ValueError(
                "Supabase credentials missing. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_KEY in the environment."
            )

    def _headers(self, *, upsert: bool) -> dict[str, str]:
        prefer = "return=minimal"
        if upsert:
            prefer += ",resolution=merge-duplicates"
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    def insert(
        self, table: str, rows: Sequence[Mapping[str, Any]], *, upsert: bool = False
    ) -> int:
        """Insert ``rows`` into ``table``; returns the number of rows sent."""
        if not rows:
            return 0
        sent = 0
        for start in range(0, len(rows), self.chunk_size):
            chunk = rows[start: start + self.chunk_size]
            payload = json.dumps(chunk).encode()
            request = urllib.request.Request(
                f"{self.url}/rest/v1/{table}",
                data=payload,
                headers=self._headers(upsert=upsert),
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.status not in (200, 201, 204):
                        raise RuntimeError(
                            f"{table}: unexpected status {response.status}"
                        )
            except urllib.error.HTTPError as exc:      # pragma: no cover - network
                detail = exc.read().decode(errors="replace")[:500]
                raise RuntimeError(f"{table}: {exc.code} {detail}") from exc
            sent += len(chunk)
        return sent

    def write_report(
        self,
        report: PerformanceReport,
        metadata: RunMetadata,
        *,
        run_id: str | None = None,
        positions: Iterable[Any] = (),
        instruments: Iterable[Any] = (),
    ) -> str:
        """Persist a full run. Returns the run id."""
        run_id = run_id or new_run_id()
        tables = report_to_rows(
            report, metadata, run_id=run_id,
            positions=positions, instruments=instruments,
        )
        # Instruments are shared reference data, so upsert rather than insert.
        self.insert(INSTRUMENTS, tables[INSTRUMENTS], upsert=True)
        self.insert(RUNS, tables[RUNS])
        for table in (EQUITY, TRADES, POSITIONS, REGION_STATS):
            self.insert(table, tables[table])
        return run_id


def rows_to_json(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Serialise flattened rows to JSON — the offline path when there is no DB."""
    return json.dumps(tables, indent=2, sort_keys=True, default=str)
