"""What each broker's API looks like, as data rather than as four code paths.

Four brokers, one shape. Every provider here answers the same five questions —
where to send someone to log in, how to turn what comes back into a token, how
to ask for holdings, how to read the answer, and how to place an order — so the
serverless relay that uses them contains no broker-specific branching at all.

Two rules shape the whole module.

**No credential ever passes through this application.** Every provider uses a
redirect: the reader logs in on their broker's own domain, and what returns is
a token, never a password, PIN or TOTP. Angel One is the one that makes this
worth stating, because its SDK-facing login *does* take a client code, PIN and
TOTP directly — this uses its publisher-login redirect instead, precisely so
those never exist in this app's memory, logs, or database.

**Requests are built, not sent.** Every function here returns a description of
a call; nothing in this file opens a socket. That is what makes four brokers
testable without four sets of credentials and without the network: the exact
bytes that would go to Zerodha can be asserted on directly.

The api_key and secret for each broker live only in the deployment
environment. A provider whose credentials are absent reports itself
unconfigured and renders no button, so nothing is ever offered that cannot
work when pressed.
"""

from __future__ import annotations

import hashlib
import os
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

#: Where a broker sends the reader back. Registered with each broker, and
#: identical for all of them: the callback reads `state` to know which one it
#: is talking to, so there is one URL to register rather than four.
CALLBACK_PATH = "/api/broker/callback"


@dataclass(frozen=True)
class Request:
    """A call to make, described rather than performed."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    #: Form-encoded when ``form`` is true, JSON otherwise. None means no body.
    body: dict[str, Any] | None = None
    form: bool = False


@dataclass(frozen=True)
class Holding:
    """One position, in the shape the page already understands.

    ``symbol`` is the broker's own tradingsymbol. It is deliberately not
    translated into this app's universe keys here: a holding the app has never
    heard of must still be shown, because it is the reader's money whether or
    not the research engine covers it.
    """

    symbol: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal
    currency: str
    exchange: str = ""

    @property
    def value(self) -> Decimal:
        return self.quantity * self.last_price

    @property
    def pnl(self) -> Decimal:
        return (self.last_price - self.average_price) * self.quantity


def _decimal(value: Any) -> Decimal:
    """A number from a broker payload, or zero.

    Brokers disagree about whether a figure is a string, a float or absent,
    and one malformed field must not lose the reader an entire portfolio.
    """
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


# --------------------------------------------------------------------------
# Zerodha (Kite Connect)
#
# The Personal tier is free and carries orders, holdings, positions and funds
# -- everything below -- and excludes only market data, which this app already
# has from its own sources. Its access token expires at 6 AM the next day by
# regulatory requirement, so a link here is good for one trading day and the
# reader signs in again each morning. That is Zerodha's design, not a
# shortcoming of this integration, and the page says so rather than presenting
# a stale token as a live connection.
# --------------------------------------------------------------------------

def _kite_authorize(key: str, _redirect: str, state: str) -> str:
    return (
        "https://kite.zerodha.com/connect/login?v=3&api_key="
        + urllib.parse.quote(key)
        + "&redirect_params="
        + urllib.parse.quote(f"state={state}")
    )


def _kite_exchange(key: str, secret: str, params: dict[str, str], _redirect: str) -> Request:
    request_token = params.get("request_token", "")
    # Zerodha authenticates the exchange with a checksum rather than by
    # sending the secret: SHA-256 over the three values concatenated.
    checksum = hashlib.sha256((key + request_token + secret).encode()).hexdigest()
    return Request(
        "POST",
        "https://api.kite.trade/session/token",
        headers={"X-Kite-Version": "3"},
        body={"api_key": key, "request_token": request_token, "checksum": checksum},
        form=True,
    )


def _kite_token(payload: dict) -> dict[str, Any]:
    data = payload.get("data") or {}
    return {"access_token": data.get("access_token", ""), "account": data.get("user_id", "")}


def _kite_headers(key: str, token: str) -> dict[str, str]:
    return {"Authorization": f"token {key}:{token}", "X-Kite-Version": "3"}


def _kite_holdings(key: str, token: str) -> Request:
    return Request("GET", "https://api.kite.trade/portfolio/holdings", _kite_headers(key, token))


def _kite_parse_holdings(payload: dict) -> list[Holding]:
    return [
        Holding(
            symbol=row.get("tradingsymbol", ""),
            quantity=_decimal(row.get("quantity")),
            average_price=_decimal(row.get("average_price")),
            last_price=_decimal(row.get("last_price")),
            currency="INR",
            exchange=row.get("exchange", ""),
        )
        for row in (payload.get("data") or [])
    ]


def _kite_order(key: str, token: str, symbol: str, qty: int, side: str, exchange: str) -> Request:
    return Request(
        "POST",
        "https://api.kite.trade/orders/regular",
        headers=_kite_headers(key, token),
        body={
            "tradingsymbol": symbol,
            "exchange": exchange or "NSE",
            "transaction_type": side.upper(),
            "quantity": str(qty),
            "order_type": "MARKET",
            "product": "CNC",
            "validity": "DAY",
        },
        form=True,
    )


def _kite_order_id(payload: dict) -> str:
    return str((payload.get("data") or {}).get("order_id", ""))


# --------------------------------------------------------------------------
# Upstox
#
# Plain OAuth 2.0. Free, and its token also expires daily. Multi-user access
# needs Upstox's approval; a single reader's own account works without it,
# which is exactly the case this serves.
# --------------------------------------------------------------------------

def _upstox_authorize(key: str, redirect: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {"client_id": key, "redirect_uri": redirect, "response_type": "code", "state": state}
    )
    return "https://api.upstox.com/v2/login/authorization/dialog?" + query


def _upstox_exchange(key: str, secret: str, params: dict[str, str], redirect: str) -> Request:
    return Request(
        "POST",
        "https://api.upstox.com/v2/login/authorization/token",
        headers={"Accept": "application/json"},
        body={
            "code": params.get("code", ""),
            "client_id": key,
            "client_secret": secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        form=True,
    )


def _upstox_token(payload: dict) -> dict[str, Any]:
    return {
        "access_token": payload.get("access_token", ""),
        "account": payload.get("user_id") or payload.get("client_id") or "",
    }


def _upstox_headers(_key: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _upstox_holdings(key: str, token: str) -> Request:
    return Request(
        "GET",
        "https://api.upstox.com/v2/portfolio/long-term-holdings",
        _upstox_headers(key, token),
    )


def _upstox_parse_holdings(payload: dict) -> list[Holding]:
    return [
        Holding(
            symbol=row.get("tradingsymbol") or row.get("trading_symbol", ""),
            quantity=_decimal(row.get("quantity")),
            average_price=_decimal(row.get("average_price")),
            last_price=_decimal(row.get("last_price")),
            currency="INR",
            exchange=row.get("exchange", ""),
        )
        for row in (payload.get("data") or [])
    ]


def _upstox_order(key: str, token: str, symbol: str, qty: int, side: str, exchange: str) -> Request:
    return Request(
        "POST",
        "https://api.upstox.com/v2/order/place",
        headers={**_upstox_headers(key, token), "Content-Type": "application/json"},
        body={
            # Upstox addresses an instrument by its own key, which the caller
            # resolves; the bare symbol is passed through when that is what it
            # was given.
            "instrument_token": symbol,
            "quantity": qty,
            "product": "D",
            "validity": "DAY",
            "price": 0,
            "order_type": "MARKET",
            "transaction_type": side.upper(),
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        },
    )


def _upstox_order_id(payload: dict) -> str:
    return str((payload.get("data") or {}).get("order_id", ""))


# --------------------------------------------------------------------------
# Angel One (SmartAPI)
#
# Free, including historical data. Its publisher-login redirect returns the
# token directly in the callback query string, so there is no exchange step --
# the one provider here that skips it. Note that Angel One requires a
# registered static IP for *order placement* from April 2026, which serverless
# functions cannot provide; reads are unaffected. The relay surfaces that as a
# refusal from Angel One rather than pretending the order went through.
# --------------------------------------------------------------------------

def _angel_authorize(key: str, redirect: str, state: str) -> str:
    query = urllib.parse.urlencode({"api_key": key, "redirect_url": redirect, "state": state})
    return "https://smartapi.angelone.in/publisher-login?" + query


def _angel_token_from_redirect(params: dict[str, str]) -> dict[str, Any]:
    return {
        "access_token": params.get("auth_token", ""),
        "refresh_token": params.get("refresh_token", ""),
        "account": params.get("client_code", ""),
    }


def _angel_headers(key: str, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-PrivateKey": key,
        "Accept": "application/json",
        "X-SourceID": "WEB",
        "X-UserType": "USER",
        "Content-Type": "application/json",
    }


def _angel_holdings(key: str, token: str) -> Request:
    return Request(
        "GET",
        "https://apiconnect.angelone.in/rest/secure/angelbroking/portfolio/v1/getAllHolding",
        _angel_headers(key, token),
    )


def _angel_parse_holdings(payload: dict) -> list[Holding]:
    data = payload.get("data") or {}
    # Angel One returns either a bare list or an object carrying one.
    rows = data.get("holdings") if isinstance(data, dict) else data
    return [
        Holding(
            symbol=row.get("tradingsymbol", ""),
            quantity=_decimal(row.get("quantity")),
            average_price=_decimal(row.get("averageprice")),
            last_price=_decimal(row.get("ltp")),
            currency="INR",
            exchange=row.get("exchange", ""),
        )
        for row in (rows or [])
    ]


def _angel_order(key: str, token: str, symbol: str, qty: int, side: str, exchange: str) -> Request:
    return Request(
        "POST",
        "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/placeOrder",
        headers=_angel_headers(key, token),
        body={
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "transactiontype": side.upper(),
            "exchange": exchange or "NSE",
            "ordertype": "MARKET",
            "producttype": "DELIVERY",
            "duration": "DAY",
            "quantity": str(qty),
        },
    )


def _angel_order_id(payload: dict) -> str:
    return str((payload.get("data") or {}).get("orderid", ""))


# --------------------------------------------------------------------------
# Alpaca
#
# The odd one out and deliberately so: its keys belong to the deployment, not
# to a reader who logs in, because that is how the existing US executor is
# already armed. It is listed here so the portfolio view can show a US book
# beside an Indian one through the same code path.
# --------------------------------------------------------------------------

def _alpaca_base() -> str:
    if os.environ.get("ALPACA_LIVE", "").lower() == "true":
        return "https://api.alpaca.markets"
    return "https://paper-api.alpaca.markets"


def _alpaca_headers(key: str, secret: str) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type": "application/json",
    }


def _alpaca_holdings(key: str, secret: str) -> Request:
    return Request("GET", _alpaca_base() + "/v2/positions", _alpaca_headers(key, secret))


def _alpaca_parse_holdings(payload: Any) -> list[Holding]:
    rows = payload if isinstance(payload, list) else (payload.get("positions") or [])
    return [
        Holding(
            symbol=row.get("symbol", ""),
            quantity=_decimal(row.get("qty")),
            average_price=_decimal(row.get("avg_entry_price")),
            last_price=_decimal(row.get("current_price")),
            currency="USD",
            exchange=row.get("exchange", ""),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class Provider:
    """One broker, reduced to the five things the relay needs from it."""

    name: str
    label: str
    region: str
    currency: str
    #: Environment variables holding this broker's credentials.
    key_env: str
    secret_env: str
    #: Angel One returns its token in the redirect itself; the others need a
    #: second call to exchange what came back.
    exchanges_token: bool
    authorize: Callable[[str, str, str], str]
    holdings: Callable[[str, str], Request]
    parse_holdings: Callable[[Any], list[Holding]]
    order: Callable[..., Request] | None = None
    parse_order: Callable[[dict], str] | None = None
    exchange: Callable[[str, str, dict[str, str], str], Request] | None = None
    parse_token: Callable[[dict], dict[str, Any]] | None = None
    token_from_redirect: Callable[[dict[str, str]], dict[str, Any]] | None = None
    #: Stated plainly on the page. Every Indian broker here expires its token
    #: daily by regulation, and a reader who is not told that reads a dead
    #: link as a broken app.
    token_note: str = ""

    def configured(self) -> bool:
        """Whether this deployment holds the credentials to offer this broker."""
        if not os.environ.get(self.key_env):
            return False
        return bool(os.environ.get(self.secret_env)) if self.secret_env else True


PROVIDERS: dict[str, Provider] = {
    "kite": Provider(
        name="kite",
        label="Zerodha",
        region="india",
        currency="INR",
        key_env="KITE_API_KEY",
        secret_env="KITE_API_SECRET",
        exchanges_token=True,
        authorize=_kite_authorize,
        exchange=_kite_exchange,
        parse_token=_kite_token,
        holdings=_kite_holdings,
        parse_holdings=_kite_parse_holdings,
        order=_kite_order,
        parse_order=_kite_order_id,
        token_note="Zerodha expires API access at 6 AM daily, by regulation. "
                   "Reconnect each trading morning.",
    ),
    "upstox": Provider(
        name="upstox",
        label="Upstox",
        region="india",
        currency="INR",
        key_env="UPSTOX_API_KEY",
        secret_env="UPSTOX_API_SECRET",
        exchanges_token=True,
        authorize=_upstox_authorize,
        exchange=_upstox_exchange,
        parse_token=_upstox_token,
        holdings=_upstox_holdings,
        parse_holdings=_upstox_parse_holdings,
        order=_upstox_order,
        parse_order=_upstox_order_id,
        token_note="Upstox expires API access daily. Reconnect each trading morning.",
    ),
    "angelone": Provider(
        name="angelone",
        label="Angel One",
        region="india",
        currency="INR",
        key_env="ANGELONE_API_KEY",
        secret_env="",
        exchanges_token=False,
        authorize=_angel_authorize,
        token_from_redirect=_angel_token_from_redirect,
        holdings=_angel_holdings,
        parse_holdings=_angel_parse_holdings,
        order=_angel_order,
        parse_order=_angel_order_id,
        token_note="Angel One expires API access daily. Order placement also "
                   "requires a registered static IP from April 2026, which this "
                   "deployment does not have; holdings still read normally.",
    ),
    "alpaca": Provider(
        name="alpaca",
        label="Alpaca",
        region="us",
        currency="USD",
        key_env="ALPACA_KEY_ID",
        secret_env="ALPACA_SECRET_KEY",
        exchanges_token=False,
        # Armed by the deployment's own keys, so there is nothing to log in to.
        authorize=lambda *_: "",
        holdings=_alpaca_holdings,
        parse_holdings=_alpaca_parse_holdings,
        token_note="Armed by this deployment's Alpaca keys; no sign-in needed.",
    ),
}

#: Brokers a reader connects by logging in, as opposed to ones the deployment
#: arms on their behalf.
def linkable() -> list[Provider]:
    return [p for p in PROVIDERS.values() if p.name != "alpaca"]


def available() -> list[Provider]:
    """Providers this deployment actually holds credentials for."""
    return [p for p in PROVIDERS.values() if p.configured()]
