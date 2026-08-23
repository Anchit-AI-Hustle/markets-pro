"""Feature counts and client errors — first-party, anonymous, best-effort.

Why this exists: eleven tabs shipped with no way to see which of them anyone
opens, which makes every roadmap decision a guess. Why it looks like this: the
page's CSP admits no third-party origin, so a hosted analytics script could
not load even if it were wanted.

What it deliberately does not do is identify anybody. No cookie, no session,
no user id, no IP, no page path — the payload is a list of short event names
and the row is a per-day counter. A reader cannot be picked out of it because
there is nothing in it to pick out.

Failure here is silent by design. A dropped count is worth nothing; a page
that breaks because its telemetry endpoint is down is worth less than that.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

#: Bounded so an event name cannot become a free-text channel for smuggling
#: anything person-shaped into the table.
EVENT_RE = re.compile(r"^[a-z0-9_.:-]{1,64}$")
MAX_EVENTS = 40
MAX_BODY = 8 * 1024
MAX_MESSAGE = 300


def _supabase(path: str, body: object) -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/") + path
    key = os.environ["SUPABASE_SERVICE_KEY"]
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode(),
        headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json", "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:  # noqa: BLE001 — telemetry never raises at the caller
        return 0


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — Vercel handler contract
        # 204 regardless of what happens below. The browser sends this with
        # keepalive on page hide and does nothing with the answer.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY or not os.environ.get("SUPABASE_SERVICE_KEY"):
                self._done()
                return
            body = json.loads(self.rfile.read(length) or b"{}")

            events = [
                e for e in (body.get("events") or [])[:MAX_EVENTS]
                if isinstance(e, str) and EVENT_RE.match(e)
            ]
            if events:
                _supabase("/rest/v1/rpc/mp_pulse_bump", {"events": events})

            errors = (body.get("errors") or [])[:5]
            rows = []
            for item in errors:
                if not isinstance(item, dict):
                    continue
                message = str(item.get("message") or "")[:MAX_MESSAGE]
                if not message:
                    continue
                rows.append({
                    "message": message,
                    "source": str(item.get("source") or "")[:200] or None,
                    "release": str(item.get("release") or "")[:40] or None,
                    # Coarse, and only to tell a browser-specific break from a
                    # general one. Not an identifier.
                    "agent": str(item.get("agent") or "")[:80] or None,
                })
            if rows:
                _supabase("/rest/v1/mp_error", rows)
        except Exception:  # noqa: BLE001 — never surface telemetry failure
            pass
        self._done()

    def _done(self) -> None:
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
