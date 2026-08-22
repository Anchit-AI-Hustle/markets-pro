"""Where a broker sends the reader back after they log in.

This is an unauthenticated GET — anyone can invoke it with anything. The
signed ``state`` is what makes that safe: it names the reader who began the
flow and the broker they began it with, it is signed with a key only the
deployment holds, and it expires. Without a valid one, nothing is stored.

The reader is redirected onward either way, with a short status in the query
string, because a blank page at the end of a broker login is indistinguishable
from a broken app.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from autotrader.broker import relay  # noqa: E402
from autotrader.broker.providers import CALLBACK_PATH, PROVIDERS  # noqa: E402


def _state_secret() -> str:
    return os.environ.get("BROKER_STATE_SECRET") or os.environ.get("SUPABASE_SERVICE_KEY", "")


def _site() -> str:
    return os.environ.get("SITE_URL", "https://markets-pro.anchit-tandon.com").rstrip("/")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — Vercel handler contract
        params = {
            k: v[0] for k, v in
            urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()
        }
        try:
            user_id, name = relay.verify_state(params.get("state", ""), _state_secret())
            provider = PROVIDERS.get(name)
            if provider is None:
                raise relay.RelayError(400, "unknown broker")

            if provider.exchanges_token:
                request = provider.exchange(
                    os.environ[provider.key_env], os.environ.get(provider.secret_env, ""),
                    params, _site() + CALLBACK_PATH,
                )
                status, payload = relay.fetch(request)
                if status not in (200, 201) or not isinstance(payload, dict):
                    detail = payload.get("message") if isinstance(payload, dict) else ""
                    raise relay.RelayError(
                        502, str(detail) or f"{provider.label} refused the login"
                    )
                token = provider.parse_token(payload) if provider.parse_token else {}
            else:
                # Angel One hands the token back in the redirect itself.
                token = provider.token_from_redirect(params) if provider.token_from_redirect else {}

            if not token.get("access_token"):
                raise relay.RelayError(502, f"{provider.label} returned no access token")
            relay.save_link(user_id, name, token)
            self._back(f"broker={name}&status=linked")
        except relay.RelayError as error:
            self._back(f"status=error&message={urllib.parse.quote(error.message)}")
        except Exception as error:  # noqa: BLE001
            self._back(f"status=error&message={urllib.parse.quote(str(error)[:200])}")

    def _back(self, query: str) -> None:
        self.send_response(302)
        self.send_header("Location", f"{_site()}/?{query}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
