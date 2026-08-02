"""Capped US order executor — an Alpaca relay the owner must explicitly arm.

Safety model, in order of what stops a bad day:

1. **Unarmed by default.** With no ``ALPACA_KEY_ID``/``ALPACA_SECRET_KEY`` in
   the Vercel environment this endpoint refuses everything. Adding keys arms
   PAPER trading only; real money additionally requires ``ALPACA_LIVE=true``.
2. **The daily cap is enforced against the broker, not the client.** Before
   accepting an order the relay sums today's buy notional from Alpaca's own
   order log and prices the new order from the quote source. Client-supplied
   notionals are display hints and are never trusted for the cap.
3. **Whitelist sizing.** One market day-order at a time, integer quantity,
   bounded symbol grammar. Nothing else passes validation.

The keys live only in the deployment environment and are never sent to, or
readable from, the page.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MAX_QTY = 10_000
_SPARK_URL = "https://query1.finance.yahoo.com/v8/finance/spark?symbols={symbol}&range=1d&interval=5m"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _alpaca_base() -> str:
    if os.environ.get("ALPACA_LIVE", "").lower() == "true":
        return "https://api.alpaca.markets"
    return "https://paper-api.alpaca.markets"


def _alpaca(path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, dict | list]:
    request = urllib.request.Request(
        _alpaca_base() + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "APCA-API-KEY-ID": os.environ["ALPACA_KEY_ID"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error)
        except Exception:  # noqa: BLE001
            detail = {"message": str(error)}
        return error.code, detail


def _spent_today() -> float:
    """Buy notional already committed today, from Alpaca's own order log."""
    today = datetime.now(timezone.utc).date().isoformat()
    query = urllib.parse.urlencode(
        {"status": "all", "after": f"{today}T00:00:00Z", "limit": 500}
    )
    status, orders = _alpaca("/v2/orders?" + query)
    if status != 200 or not isinstance(orders, list):
        raise RuntimeError(f"could not read today's orders from Alpaca (HTTP {status})")
    spent = 0.0
    for order in orders:
        if order.get("side") != "buy" or order.get("status") in ("canceled", "expired", "rejected"):
            continue
        notional = order.get("filled_avg_price") or order.get("limit_price")
        qty = float(order.get("filled_qty") or 0) or float(order.get("qty") or 0)
        if notional is not None:
            spent += float(notional) * qty
        else:
            spent += float(order.get("notional") or 0)
    return spent


def _market_price(symbol: str) -> float:
    request = urllib.request.Request(
        _SPARK_URL.format(symbol=urllib.parse.quote(symbol)),
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    closes = [c for c in (payload.get(symbol, {}).get("close") or []) if c is not None]
    if not closes:
        raise RuntimeError(f"no quote available for {symbol}")
    return closes[-1]


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — Vercel handler contract
        if not (os.environ.get("ALPACA_KEY_ID") and os.environ.get("ALPACA_SECRET_KEY")):
            self._reply(503, {"message": "executor not armed — add Alpaca keys in Vercel env"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            orders = body["orders"]
            assert isinstance(orders, list) and len(orders) == 1
            order = orders[0]
            symbol = str(order["symbol"]).upper()
            qty = int(order["qty"])
            side = str(order["side"]).lower()
            assert _SYMBOL_RE.match(symbol), "bad symbol"
            assert 0 < qty <= _MAX_QTY, "bad quantity"
            assert side in ("buy", "sell"), "bad side"
        except Exception:  # noqa: BLE001 — any malformed body is a 400
            self._reply(400, {"message": "expected {orders: [{symbol, qty, side}]}"})
            return

        cap = float(os.environ.get("DAILY_CAP_USD", "0"))
        try:
            if side == "buy":
                if cap <= 0:
                    self._reply(403, {"message": "no DAILY_CAP_USD set — refusing buys"})
                    return
                estimate = _market_price(symbol) * qty
                spent = _spent_today()
                if spent + estimate > cap:
                    self._reply(
                        403,
                        {
                            "message": (
                                f"daily cap: {spent:,.0f} spent + {estimate:,.0f} est "
                                f"> {cap:,.0f} USD"
                            )
                        },
                    )
                    return

            status, result = _alpaca(
                "/v2/orders",
                method="POST",
                body={
                    "symbol": symbol,
                    "qty": str(qty),
                    "side": side,
                    "type": "market",
                    "time_in_force": "day",
                },
            )
        except Exception as error:  # noqa: BLE001 — surfaced, never silent
            self._reply(502, {"message": f"executor error: {error}"})
            return

        if status in (200, 201) and isinstance(result, dict):
            mode = "LIVE" if _alpaca_base().startswith("https://api.") else "paper"
            message = f"{mode} {side} {qty} {symbol} accepted"
            self._reply(200, {"message": message, "id": result.get("id")})
        else:
            message = result.get("message", "rejected") if isinstance(result, dict) else "rejected"
            self._reply(502, {"message": f"Alpaca: {message}"})

    def _reply(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
