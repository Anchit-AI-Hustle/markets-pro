"""Delayed-quote proxy for the dashboard's intraday overlay.

Exists because the page cannot query Yahoo directly: the dashboard ships under
a strict CSP with ``connect-src 'self'``, and Yahoo sends no CORS headers
anyway. One spark request serves every symbol on the page; the CDN cache
header keeps upstream traffic to about one request a minute regardless of how
many viewers are polling.

Quotes are delayed (~15 min for NSE). This endpoint is read-only public
market data — it neither sees nor stores anything about the viewer.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

_SPARK_URL = "https://query1.finance.yahoo.com/v8/finance/spark?symbols={symbols}&range=1d&interval=5m"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=]{0,14}$")
_MAX_SYMBOLS = 25


def _latest_price(series: dict) -> float | None:
    closes = [c for c in (series.get("close") or []) if c is not None]
    return closes[-1] if closes else None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — Vercel handler contract
        query = urllib.parse.urlparse(self.path).query
        raw = urllib.parse.parse_qs(query).get("symbols", [""])[0]
        symbols = [s for s in raw.upper().split(",") if _SYMBOL_RE.match(s)][:_MAX_SYMBOLS]
        if not symbols:
            self._reply(400, {"error": "symbols parameter required"})
            return

        try:
            request = urllib.request.Request(
                _SPARK_URL.format(symbols=urllib.parse.quote(",".join(symbols))),
                headers={"User-Agent": _USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except Exception:  # noqa: BLE001 — upstream flakiness must not 500 the page
            self._reply(502, {"error": "quote source unavailable"})
            return

        quotes = {}
        for symbol in symbols:
            series = payload.get(symbol)
            if not isinstance(series, dict):
                continue
            price = _latest_price(series)
            if price is not None:
                timestamps = series.get("timestamp") or []
                quotes[symbol] = {
                    "price": round(price, 4),
                    "ts": timestamps[-1] if timestamps else None,
                }
        self._reply(200, {"quotes": quotes}, cache="public, s-maxage=55, max-age=30")

    def _reply(self, status: int, body: dict, *, cache: str = "no-store") -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
