"""Serve the dashboard on the ``/markets-pro`` route.

Standard-library ``http.server`` only. This exists so the route can be checked
locally exactly as it will be served in production, and so the same route logic
can back a container deploy. For a real deployment, prefer the static build
(:mod:`autotrader.web.build`) behind whatever already serves the domain.

Bound to localhost by default. It is a development server: no TLS, no auth, no
request limits. Do not expose it directly to the internet.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROUTE = "/markets-pro"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves one pre-rendered page at :data:`ROUTE`."""

    html: str = "<h1>markets-pro</h1><p>No report has been rendered yet.</p>"
    server_version = "markets-pro/0.1"

    def do_GET(self) -> None:                        # noqa: N802 - stdlib API
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path in (ROUTE, f"{ROUTE}/index.html"):
            self._send(200, self.html)
        elif path == "/healthz":
            self._send(200, "ok", content_type="text/plain; charset=utf-8")
        elif path == "/":
            self.send_response(302)
            self.send_header("Location", ROUTE)
            self.end_headers()
        else:
            self._send(
                404,
                f"<h1>404</h1><p>Nothing here. The dashboard lives at "
                f"<a href='{ROUTE}'>{ROUTE}</a>.</p>",
            )

    def _send(
        self, status: int, body: str, *, content_type: str = "text/html; charset=utf-8"
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The page inlines its CSS and its chart-zoom script and loads nothing
        # from the network, so everything stays blocked except inline style and
        # script. 'unsafe-inline' for script is required because the file is
        # static and has no server to mint a per-request nonce.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; img-src data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - noise
        return


def serve(html: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Block, serving ``html`` at :data:`ROUTE`."""
    DashboardHandler.html = html
    httpd = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"markets-pro serving at http://{host}:{port}{ROUTE}  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:                        # pragma: no cover - manual
        print("\nstopped")
    finally:
        httpd.server_close()


def _demo_html() -> str:
    """Render the bundled demo so `python -m autotrader.web.server` shows something."""
    from .build import run_demo_backtest
    from .render import render_dashboard

    report = run_demo_backtest()
    return render_dashboard(report, subtitle="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the markets-pro dashboard")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--file", type=Path, default=None,
        help="serve a pre-built HTML file instead of running the demo backtest",
    )
    args = parser.parse_args(argv)

    html = args.file.read_text(encoding="utf-8") if args.file else _demo_html()
    serve(html, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
