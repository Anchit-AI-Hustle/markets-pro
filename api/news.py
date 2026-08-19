"""Headline proxy for the watchlist and the market summary.

Same shape as the quote proxy and for the same reason: the page ships under a
strict CSP with ``connect-src 'self'``, so it cannot reach a news host itself,
and the feed sends no CORS headers anyway. One request here serves every
symbol the caller asks about, and the CDN cache keeps upstream traffic to
roughly one fetch per symbol per ten minutes however many people are reading.

Coverage is uneven and this endpoint does not pretend otherwise: some listings
carry a dozen stories and others none. A symbol with nothing is returned with
an empty list rather than being filled from somewhere less relevant.

Everything here is public headline metadata — a title, a link, a timestamp and
a publisher. No article text is copied, and nothing about the reader is sent
anywhere.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler

_FEED = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
         "?s={symbol}&region=US&lang=en-US")
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_SYMBOL_RE = re.compile(r"^[\^A-Z0-9][A-Z0-9.\-=]{0,14}$")
_MAX_SYMBOLS = 8
_PER_SYMBOL = 6


def _fetch(symbol: str) -> list[dict]:
    url = _FEED.format(symbol=urllib.parse.quote(symbol))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    stories = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        published = None
        raw_date = (item.findtext("pubDate") or "").strip()
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).astimezone(
                    timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                published = None
        stories.append({
            "title": title,
            "link": link,
            "published": published,
            "source": (item.findtext("source") or "").strip() or None,
        })
        if len(stories) >= _PER_SYMBOL:
            break
    return stories


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — Vercel handler contract
        query = urllib.parse.urlparse(self.path).query
        raw = urllib.parse.parse_qs(query).get("symbols", [""])[0]
        symbols = [s for s in raw.upper().split(",") if _SYMBOL_RE.match(s)][:_MAX_SYMBOLS]
        if not symbols:
            self._reply(400, {"error": "symbols parameter required"})
            return

        news, failed = {}, []
        for symbol in symbols:
            try:
                news[symbol] = _fetch(symbol)
            except Exception:  # noqa: BLE001 — one bad feed must not fail the rest
                failed.append(symbol)
                news[symbol] = []

        self._reply(
            200,
            {
                "news": news,
                "unavailable": failed,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            cache="public, s-maxage=600, max-age=300",
        )

    def _reply(self, status: int, body: dict, *, cache: str = "no-store") -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
