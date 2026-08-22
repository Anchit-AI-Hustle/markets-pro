"""The broker relay: everything the serverless endpoints do, minus the HTTP.

The two functions under ``api/broker/`` are deliberately thin shells around
this module. Putting the logic here rather than in the handlers is what makes
it testable — the cap arithmetic, the state signing and the refusal rules are
the parts that matter, and none of them should require a deployment and four
sets of broker credentials to exercise.

The security model, in the order things would go wrong:

1. **A broker token never reaches a browser.** It is written to a table the
   publishable key cannot read, and every call that needs it is made from
   here. The page asks for *holdings*; it never asks for, and cannot obtain,
   the credential that produced them.
2. **The caller proves who they are to Supabase, not to us.** A request
   carries the reader's own Supabase access token, which this module exchanges
   for a user id by asking Supabase. There is no session of our own to forge.
3. **The state parameter is signed.** An OAuth callback is an unauthenticated
   GET that anyone can invoke; the signature is what ties a returning token to
   the reader who started the flow, and the expiry is what stops a captured
   link being replayed later.
4. **Orders are refused by default.** Live order placement needs an explicit
   environment flag, a per-currency cap, and a symbol that passes a whitelist.
   The cap is measured against the journal of what was actually placed, so a
   retried request cannot spend it twice.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .providers import PROVIDERS, Holding, Provider, Request

#: A tradingsymbol, bounded. Anything outside this grammar is refused before
#: it can reach a broker, rather than being escaped and hoped about.
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&._\-]{0,24}$")
MAX_QTY = 100_000
#: How long a signed OAuth state stays valid. Long enough to log in and clear
#: a two-factor prompt, short enough that a leaked callback URL is stale.
STATE_TTL = 900


class RelayError(Exception):
    """A refusal with an HTTP status attached. The message is shown to the reader."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Signed state
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_state(user_id: str, provider: str, secret: str, *, now: int | None = None) -> str:
    """Tie an outgoing OAuth request to the reader who started it."""
    issued = int(time.time()) if now is None else now
    payload = f"{user_id}|{provider}|{issued}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{_b64(payload.encode())}.{_b64(mac)}"


def verify_state(state: str, secret: str, *, now: int | None = None) -> tuple[str, str]:
    """``(user_id, provider)`` from a state we signed, or raise.

    Every failure here is the same refusal to the caller. Telling an attacker
    whether a state was malformed, forged or merely expired hands them a test
    oracle for free.
    """
    checked = int(time.time()) if now is None else now
    try:
        body, mac = state.split(".", 1)
        payload = _unb64(body)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        # compare_digest, not ==: a timing difference on the first wrong byte
        # is enough to forge a signature one byte at a time.
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise ValueError("bad signature")
        user_id, provider, issued = payload.decode().split("|")
        if checked - int(issued) > STATE_TTL:
            raise ValueError("expired")
    except Exception as error:  # noqa: BLE001 — one refusal for every cause
        raise RelayError(400, "this sign-in link is not valid any more") from error
    return user_id, provider


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch(request: Request, *, timeout: int = 15) -> tuple[int, object]:
    """Perform a described call. The only place this module opens a socket."""
    data = None
    headers = dict(request.headers)
    if request.body is not None:
        if request.form:
            data = urllib.parse.urlencode(request.body).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data = json.dumps(request.body).encode()
            headers.setdefault("Content-Type", "application/json")
    prepared = urllib.request.Request(
        request.url, method=request.method, data=data, headers=headers
    )
    try:
        with urllib.request.urlopen(prepared, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"message": raw[:200]}


def _supabase(path: str, *, method: str = "GET", body: object = None,
              prefer: str = "") -> tuple[int, object]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + path
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if prefer:
        headers["Prefer"] = prefer
    return fetch(Request(method, url, headers, body if body is not None else None))


def user_from_token(access_token: str) -> str:
    """The Supabase user id behind a caller's access token.

    Verified by asking Supabase rather than by checking a signature here: it
    is one call, and it means a signed-out or revoked session stops working
    immediately instead of when its token happens to expire.
    """
    if not access_token:
        raise RelayError(401, "sign in first")
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/user"
    status, payload = fetch(Request("GET", url, {
        "apikey": os.environ["SUPABASE_ANON_KEY"],
        "Authorization": f"Bearer {access_token}",
    }))
    if status != 200 or not isinstance(payload, dict) or not payload.get("id"):
        raise RelayError(401, "your session has expired — sign in again")
    return str(payload["id"])


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Link:
    provider: str
    access_token: str
    account: str
    expires_at: str | None

    def stale(self, *, now: datetime | None = None) -> bool:
        """Whether the broker has expired this token.

        Indian brokers expire API access daily by regulation. A link that has
        lapsed is reported as needing reconnection rather than being used to
        make a call that would fail with something unreadable.
        """
        if not self.expires_at:
            return False
        moment = now or datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(self.expires_at.replace("Z", "+00:00")) <= moment
        except ValueError:
            return False


def next_expiry(*, now: datetime | None = None) -> str:
    """6 AM IST tomorrow, in UTC — when an Indian broker token dies.

    Zerodha states this explicitly and the others behave the same way. It is
    computed rather than read from the broker because none of them return it.
    """
    moment = now or datetime.now(timezone.utc)
    # 06:00 IST is 00:30 UTC. timedelta, not fromordinal: the latter returns a
    # naive datetime, which drops the timezone and then cannot be compared
    # against the aware one it came from.
    expiry = moment.replace(hour=0, minute=30, second=0, microsecond=0)
    if expiry <= moment:
        expiry = expiry + timedelta(days=1)
    return expiry.isoformat()


def save_link(user_id: str, provider: str, token: dict) -> None:
    row = {
        "user_id": user_id,
        "provider": provider,
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token") or None,
        "account": token.get("account") or None,
        "expires_at": next_expiry(),
    }
    status, payload = _supabase(
        "/rest/v1/mp_broker_link?on_conflict=user_id,provider",
        method="POST", body=[row],
        prefer="resolution=merge-duplicates,return=minimal",
    )
    if status >= 400:
        raise RelayError(502, f"could not save the connection: {payload}")


def read_link(user_id: str, provider: str) -> Link | None:
    query = (f"/rest/v1/mp_broker_link?user_id=eq.{urllib.parse.quote(user_id)}"
             f"&provider=eq.{urllib.parse.quote(provider)}"
             "&select=provider,access_token,account,expires_at")
    status, rows = _supabase(query)
    if status >= 400 or not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    return Link(row["provider"], row["access_token"],
                row.get("account") or "", row.get("expires_at"))


def read_links(user_id: str) -> list[Link]:
    query = (f"/rest/v1/mp_broker_link?user_id=eq.{urllib.parse.quote(user_id)}"
             "&select=provider,account,expires_at,access_token")
    status, rows = _supabase(query)
    if status >= 400 or not isinstance(rows, list):
        return []
    return [Link(r["provider"], r["access_token"], r.get("account") or "",
                 r.get("expires_at")) for r in rows]


def delete_link(user_id: str, provider: str) -> None:
    query = (f"/rest/v1/mp_broker_link?user_id=eq.{urllib.parse.quote(user_id)}"
             f"&provider=eq.{urllib.parse.quote(provider)}")
    _supabase(query, method="DELETE")


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def holdings_for(provider: Provider, link: Link | None) -> list[Holding]:
    """One broker's holdings, or an empty list if it cannot be reached."""
    if provider.name == "alpaca":
        key = os.environ.get(provider.key_env, "")
        secret = os.environ.get(provider.secret_env, "")
        if not (key and secret):
            return []
        status, payload = fetch(provider.holdings(key, secret))
    else:
        if link is None or link.stale():
            return []
        status, payload = fetch(
            provider.holdings(os.environ.get(provider.key_env, ""), link.access_token)
        )
    if status != 200:
        raise RelayError(502, f"{provider.label} refused the request (HTTP {status})")
    return provider.parse_holdings(payload)


def portfolio(user_id: str) -> dict:
    """Every linked broker's holdings, plus why any of them are missing.

    A broker that fails is reported by name with its reason rather than
    silently contributing nothing: a portfolio that is quietly short one
    account is worse than one that says which account it could not read.
    """
    links = {link.provider: link for link in read_links(user_id)}
    accounts, problems = [], []
    for provider in PROVIDERS.values():
        if not provider.configured():
            continue
        link = links.get(provider.name)
        if provider.name != "alpaca":
            if link is None:
                continue
            if link.stale():
                problems.append({"provider": provider.name, "label": provider.label,
                                 "reason": "expired", "note": provider.token_note})
                continue
        try:
            rows = holdings_for(provider, link)
        except RelayError as error:
            problems.append({"provider": provider.name, "label": provider.label,
                             "reason": "error", "note": error.message})
            continue
        accounts.append({
            "provider": provider.name,
            "label": provider.label,
            "currency": provider.currency,
            "account": link.account if link else "",
            "holdings": [
                {"symbol": h.symbol, "quantity": str(h.quantity),
                 "average_price": str(h.average_price), "last_price": str(h.last_price),
                 "value": str(h.value), "pnl": str(h.pnl),
                 "currency": h.currency, "exchange": h.exchange}
                for h in rows
            ],
            "value": str(sum((h.value for h in rows), Decimal("0"))),
            "pnl": str(sum((h.pnl for h in rows), Decimal("0"))),
        })
    return {"accounts": accounts, "problems": problems}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def orders_live() -> bool:
    """Whether this deployment is allowed to place a real order at all."""
    return os.environ.get("BROKER_ORDERS_LIVE", "").lower() == "true"


def daily_cap(currency: str) -> Decimal:
    raw = os.environ.get(f"DAILY_CAP_{currency.upper()}", "0")
    try:
        return Decimal(raw)
    except Exception:  # noqa: BLE001
        return Decimal("0")


def spent_today(user_id: str, currency: str, *, now: datetime | None = None) -> Decimal:
    """Buy notional already committed today, from the journal.

    The journal, not the client's arithmetic and not an in-memory counter: a
    serverless function keeps nothing between invocations, so anything not
    written down does not survive to enforce the cap on the next request.
    """
    moment = now or datetime.now(timezone.utc)
    since = moment.date().isoformat()
    query = (f"/rest/v1/mp_broker_order?user_id=eq.{urllib.parse.quote(user_id)}"
             f"&currency=eq.{urllib.parse.quote(currency)}&side=eq.buy"
             f"&placed_at=gte.{since}T00:00:00Z&error=is.null&select=notional")
    status, rows = _supabase(query)
    if status >= 400 or not isinstance(rows, list):
        # Refusing to guess: an unreadable journal means the cap cannot be
        # enforced, and an unenforced cap is exactly the thing this protects.
        raise RelayError(502, "could not read today's orders — refusing to place more")
    return sum((Decimal(str(r.get("notional") or 0)) for r in rows), Decimal("0"))


def journal(user_id: str, provider: str, symbol: str, side: str, qty: int,
            notional: Decimal, currency: str, order_id: str = "",
            error: str = "") -> None:
    _supabase("/rest/v1/mp_broker_order", method="POST", prefer="return=minimal", body=[{
        "user_id": user_id, "provider": provider, "symbol": symbol, "side": side,
        "quantity": qty, "notional": str(notional), "currency": currency,
        "broker_order_id": order_id or None, "error": error or None,
    }])


def validate_order(symbol: str, qty: object, side: object) -> tuple[str, int, str]:
    """Coerce and bound an order, or refuse it."""
    symbol = str(symbol).upper().strip()
    if not SYMBOL_RE.match(symbol):
        raise RelayError(400, f"{symbol!r} is not a symbol this will send to a broker")
    if isinstance(qty, bool):
        raise RelayError(400, "quantity must be a whole number of shares")
    try:
        quantity = int(qty)
        # int(1.5) is 1. Truncating would send a broker an order for a
        # quantity nobody asked for, which is worse than refusing.
        if Decimal(str(qty)) != quantity:
            raise ValueError("fractional")
    except (TypeError, ValueError, InvalidOperation) as error:
        raise RelayError(400, "quantity must be a whole number of shares") from error
    if not 0 < quantity <= MAX_QTY:
        raise RelayError(400, f"quantity must be between 1 and {MAX_QTY:,}")
    direction = str(side).lower().strip()
    if direction not in ("buy", "sell"):
        raise RelayError(400, "side must be buy or sell")
    return symbol, quantity, direction


def place_order(user_id: str, provider_name: str, symbol: str, qty: object,
                side: object, price: object, exchange: str = "") -> dict:
    """Place one order, if every guard allows it.

    The guards run before the broker is contacted, in increasing order of what
    they cost to check, and the cap is the last of them because it is the one
    that needs a round trip.
    """
    provider = PROVIDERS.get(provider_name)
    if provider is None or provider.order is None:
        raise RelayError(400, "that broker cannot place orders from here")
    if not provider.configured():
        raise RelayError(503, f"{provider.label} is not configured on this deployment")
    if not orders_live():
        raise RelayError(
            403,
            "order placement is off. Set BROKER_ORDERS_LIVE=true in the "
            "deployment environment to arm it.",
        )

    symbol, quantity, direction = validate_order(symbol, qty, side)
    link = read_link(user_id, provider_name)
    if link is None:
        raise RelayError(403, f"connect {provider.label} first")
    if link.stale():
        raise RelayError(
            403,
            f"{provider.label} access has expired — reconnect. {provider.token_note}",
        )

    try:
        estimate = Decimal(str(price)) * quantity
    except Exception as error:  # noqa: BLE001
        raise RelayError(400, "a reference price is required to size against the cap") from error
    if estimate <= 0:
        raise RelayError(400, "a reference price is required to size against the cap")

    currency = provider.currency
    if direction == "buy":
        cap = daily_cap(currency)
        if cap <= 0:
            raise RelayError(403, f"no DAILY_CAP_{currency} is set — refusing to buy")
        spent = spent_today(user_id, currency)
        if spent + estimate > cap:
            raise RelayError(403, (
                f"daily cap: {spent:,.0f} already committed + {estimate:,.0f} "
                f"estimated exceeds {cap:,.0f} {currency}"
            ))

    request = provider.order(
        os.environ.get(provider.key_env, ""), link.access_token,
        symbol, quantity, direction, exchange,
    )
    status, payload = fetch(request)
    if status not in (200, 201) or not isinstance(payload, dict):
        detail = payload.get("message") if isinstance(payload, dict) else str(payload)
        # Journalled even though it failed: a rejection the reader cannot see
        # looks identical to an order that was never sent.
        journal(user_id, provider_name, symbol, direction, quantity,
                estimate, currency, error=str(detail)[:200])
        raise RelayError(502, f"{provider.label}: {detail or 'order rejected'}")

    order_id = provider.parse_order(payload) if provider.parse_order else ""
    journal(user_id, provider_name, symbol, direction, quantity,
            estimate if direction == "buy" else Decimal("0"), currency, order_id=order_id)
    return {
        "message": f"{direction} {quantity} {symbol} accepted by {provider.label}",
        "order_id": order_id,
        "provider": provider_name,
    }
