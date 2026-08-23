"""Broker link relay — the page's only route to a connected account.

A thin shell. Every rule this enforces lives in ``autotrader.broker.relay``,
where it can be tested without a deployment or four sets of broker
credentials; this file's whole job is to turn HTTP into a call and a refusal
into a status code.

Nothing here returns a broker token. The page can ask what is linked, ask for
holdings, and ask for an order to be placed. It cannot ask for the credential
that makes any of those possible, because that credential is in a table the
key inside the page cannot read.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from autotrader.broker import relay  # noqa: E402
from autotrader.broker.providers import CALLBACK_PATH, PROVIDERS, linkable  # noqa: E402

MAX_BODY = 16 * 1024


def _state_secret() -> str:
    """The key that signs OAuth state.

    Falls back to the service key when no dedicated secret is set: it is
    already a high-entropy value that only the deployment holds, and one fewer
    required variable is one fewer deployment that half-works.
    """
    return os.environ.get("BROKER_STATE_SECRET") or os.environ.get("SUPABASE_SERVICE_KEY", "")


def _site() -> str:
    return os.environ.get("SITE_URL", "https://markets-pro.anchit-tandon.com").rstrip("/")


def _providers_view(user_id: str | None) -> dict:
    linked = {link.provider: link for link in (relay.read_links(user_id) if user_id else [])}
    rows = []
    for provider in linkable():
        link = linked.get(provider.name)
        rows.append({
            "provider": provider.name,
            "label": provider.label,
            "region": provider.region,
            "currency": provider.currency,
            "configured": provider.configured(),
            "linked": link is not None,
            "stale": bool(link and link.stale()),
            "account": link.account if link else "",
            "note": provider.token_note,
        })
    alpaca = PROVIDERS["alpaca"]
    return {
        "providers": rows,
        "alpaca": {"configured": alpaca.configured(), "label": alpaca.label,
                   "note": alpaca.token_note},
        "orders_live": relay.orders_live(),
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — Vercel handler contract
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                raise ValueError("body too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            action = str(body.get("action", ""))
        except Exception:  # noqa: BLE001
            self._reply(400, {"message": "expected a JSON body with an action"})
            return

        if not os.environ.get("SUPABASE_SERVICE_KEY"):
            self._reply(503, {"message": "broker linking is not configured on this deployment"})
            return

        bearer = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        try:
            # "providers" is answerable signed out, so the page can show what
            # exists before asking anyone to sign in for it.
            user_id = relay.user_from_token(bearer) if bearer else None
            if action == "providers":
                self._reply(200, _providers_view(user_id))
                return
            if user_id is None:
                raise relay.RelayError(401, "sign in first")

            if action == "connect":
                name = str(body.get("provider", ""))
                provider = PROVIDERS.get(name)
                if provider is None or name == "alpaca":
                    raise relay.RelayError(400, "unknown broker")
                if not provider.configured():
                    raise relay.RelayError(
                        503,
                        f"{provider.label} is not configured on this deployment — "
                        f"its {provider.key_env} is not set.",
                    )
                state = relay.sign_state(user_id, name, _state_secret())
                url = provider.authorize(
                    os.environ[provider.key_env], _site() + CALLBACK_PATH, state
                )
                self._reply(200, {"url": url})
            elif action == "disconnect":
                relay.delete_link(user_id, str(body.get("provider", "")))
                self._reply(200, {"message": "disconnected"})
            elif action == "portfolio":
                self._reply(200, relay.portfolio(user_id))
            elif action == "order":
                self._reply(200, relay.place_order(
                    user_id, str(body.get("provider", "")), body.get("symbol", ""),
                    body.get("qty"), body.get("side"), body.get("price"),
                    str(body.get("exchange", "")),
                    str(body.get("idempotency_key", ""))[:64],
                ))
            else:
                raise relay.RelayError(400, "unknown action")
        except relay.RelayError as error:
            self._reply(error.status, {"message": error.message})
        except Exception as error:  # noqa: BLE001 — surfaced, never silent
            self._reply(502, {"message": f"relay error: {error}"})

    def _reply(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
