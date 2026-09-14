"""Yahoo Finance daily-bar fetcher — standard library only.

Fetches end-of-day OHLCV via the public v8 chart endpoint and normalises it
into the JSON cache format under ``data/live/``. The cache, not the network,
is what the build consumes: the site build must stay deterministic and
offline-capable, so fetching and building are separate steps. The nightly
refresh job runs the fetch, commits the changed cache, and the deploy build
reads only committed files.

Yahoo quirks handled here:
- rows where any OHLC field is null (halts, partial sessions) are dropped;
- the final row can be a live/incomplete session — it is dropped unless its
  timestamp falls on a completed session day;
- requests without a browser-like User-Agent are rejected.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .universe import UniverseEntry

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1d"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_CACHE_VERSION = 1


class FetchError(RuntimeError):
    """A symbol could not be fetched or parsed after retries."""


@dataclass(frozen=True)
class DailyRow:
    """One completed session as fetched, prices kept as strings.

    Strings, not floats: the cache is the boundary where float leaves the
    system. Consumers construct Decimal directly from these strings.
    """

    day: date
    open: str
    high: str
    low: str
    close: str
    volume: str


def _http_get_json(url: str, *, retries: int = 3, timeout: float = 20.0) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(2**attempt)
    raise FetchError(f"GET {url} failed after {retries} attempts: {last_error}")


def _fmt_price(value: float) -> str:
    return f"{value:.4f}"


def parse_chart(payload: dict, *, today: date) -> tuple[list[DailyRow], str]:
    """Parse a v8 chart payload into completed-session rows plus the currency.

    ``today`` is the fetch date: a bar stamped today is treated as a possibly
    incomplete live session and excluded, unless the payload's own metadata
    says the market is closed (post/closed trading period).
    """
    try:
        result = payload["chart"]["result"][0]
        meta = result["meta"]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as error:
        raise FetchError(f"unexpected chart payload shape: {error}") from error

    currency = str(meta.get("currency", ""))
    tz_offset = int(meta.get("gmtoffset", 0))
    rows: list[DailyRow] = []
    for i, ts in enumerate(timestamps):
        o, h, low, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
        if None in (o, h, low, c):
            continue
        session_day = datetime.fromtimestamp(ts + tz_offset, tz=timezone.utc).date()
        rows.append(
            DailyRow(
                day=session_day,
                open=_fmt_price(o),
                high=_fmt_price(h),
                low=_fmt_price(low),
                close=_fmt_price(c),
                volume=str(int(quote["volume"][i] or 0)),
            )
        )

    market_closed = str(meta.get("marketState", "")).upper() not in {"REGULAR", "PRE"}
    if rows and rows[-1].day >= today and not market_closed:
        rows.pop()
    return rows, currency


def fetch_daily(entry: UniverseEntry, *, range_: str = "2y") -> tuple[list[DailyRow], str]:
    url = _CHART_URL.format(symbol=entry.yahoo, range=range_)
    payload = _http_get_json(url)
    return parse_chart(payload, today=datetime.now(timezone.utc).date())


# --- cache -----------------------------------------------------------------


def _last_cached_day(path: Path) -> date | None:
    """Newest valid session already on disk, when the cache can be read.

    A provider can temporarily return a shorter series while still answering
    successfully.  Treating that response as fresh used to delete a completed
    session from the committed cache.  The refresh may correct values for the
    same day or append a newer day, but it must never move the horizon backward.
    """
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text())
        bars = document.get("bars") or []
        raw_day = bars[-1].get("day") if bars and isinstance(bars[-1], dict) else None
        return date.fromisoformat(raw_day) if raw_day else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def cache_path(root: Path, entry: UniverseEntry) -> Path:
    return root / entry.region / f"{entry.symbol}.json"


def write_cache(root: Path, entry: UniverseEntry, rows: Sequence[DailyRow], currency: str) -> Path:
    path = cache_path(root, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        cached_day = _last_cached_day(path)
        incoming_day = rows[-1].day
        if cached_day is not None and incoming_day < cached_day:
            raise FetchError(
                f"refusing to regress {entry.symbol} cache from {cached_day} "
                f"to {incoming_day}"
            )
    document = {
        "version": _CACHE_VERSION,
        "symbol": entry.symbol,
        "yahoo": entry.yahoo,
        "exchange": entry.exchange,
        "region": entry.region,
        "currency": currency or entry.currency,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bars": [
            {
                "day": row.day.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ],
    }
    path.write_text(json.dumps(document, indent=1) + "\n")
    return path


def read_cache(root: Path, entry: UniverseEntry) -> dict:
    path = cache_path(root, entry)
    if not path.exists():
        raise FetchError(
            f"no cached data for {entry.symbol} at {path}; run autotrader.data.fetch first"
        )
    document = json.loads(path.read_text())
    if document.get("version") != _CACHE_VERSION:
        raise FetchError(f"{path}: cache version {document.get('version')} != {_CACHE_VERSION}")
    return document
