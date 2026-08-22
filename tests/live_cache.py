"""One snapshot, shared by every test that needs real data.

Generating a snapshot over 325 instruments takes seconds, and several modules
want the same one. Built once per process here rather than once per test
class — the difference on the full suite is minutes, and a suite people avoid
running is a suite that stops catching things.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"

_CACHE: tuple | None = None


def available() -> bool:
    """Whether this checkout has the committed cache these tests need."""
    return (LIVE / "benchmarks.json").exists()


def load() -> tuple[dict, dict | None, dict]:
    """``(snapshot, screener, stock_index)`` — built once, reused thereafter."""
    global _CACHE
    if _CACHE is None:
        from autotrader.signals.live import generate
        from autotrader.web.render import _stock_index

        snapshot, _report = generate(LIVE, ROOT / "config" / "live.json")
        path = LIVE / "screener.json"
        screener = json.loads(path.read_text()) if path.exists() else None
        _CACHE = (snapshot, screener, _stock_index(snapshot, screener))
    return _CACHE
