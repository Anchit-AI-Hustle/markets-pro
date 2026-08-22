"""Indian mutual fund NAVs from AMFI — the industry's own daily publication.

AMFI is the association every Indian AMC reports to, and ``NAVAll.txt`` is the
file the whole industry quotes from. It is free, complete and published once a
day after valuation, which is exactly the cadence a NAV has — a fund does not
have an intraday price, and any site showing one is showing you an estimate.

The file is ~1.5 MB of semicolon-delimited rows interleaved with two kinds of
bare heading: a scheme category, then a fund house. Rows inherit whichever
headings last appeared above them, which is the only way to recover a scheme's
category — it is not on the row itself.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
_USER_AGENT = "MarketsPro/1.0 (anchit.tandon@gmail.com)"
CACHE_VERSION = 1

#: Schemes are dropped below this many rows per house to keep the payload
#: sane? No — nothing is dropped. Every scheme AMFI publishes is carried; the
#: page filters client-side. Truncating a fund list silently would make
#: "not found" indistinguishable from "does not exist".


class FundsError(RuntimeError):
    """The NAV file could not be fetched or parsed."""


def fetch_raw(timeout: float = 60.0) -> str:
    request = urllib.request.Request(NAV_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as error:  # noqa: BLE001
        raise FundsError(f"GET {NAV_URL} failed: {error}") from error


_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def _as_date(value: str) -> date | None:
    """Parse AMFI's ``21-Aug-2026`` form; None when it is not a date."""
    parts = value.split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[2]), _MONTHS[parts[1][:3].title()], int(parts[0]))
    except (KeyError, ValueError):
        return None


def _category_of(heading: str) -> tuple[str, str]:
    """Split "Open Ended Schemes(Equity Scheme - Large Cap Fund)" into parts."""
    structure, _, detail = heading.partition("(")
    detail = detail.rstrip(")").strip()
    kind, _, sub = detail.partition(" - ")
    return (kind.strip() or structure.strip(), sub.strip() or detail)


def parse(raw: str) -> dict:
    """Rows plus the headings they sit under, as one compact document."""
    schemes: list[dict] = []
    category = subcategory = house = ""
    latest_date = ""
    latest_parsed: date | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            # A bare line is a heading: a category if it names a scheme type,
            # otherwise the fund house whose rows follow.
            if "Scheme" in line and "(" in line:
                category, subcategory = _category_of(line)
            else:
                house = line
            continue
        parts = line.split(";")
        if len(parts) < 8 or parts[0].strip().lower() == "scheme code":
            continue
        code, isin_growth, _isin_reinv, name, plan, option, nav, day = parts[:8]
        try:
            nav_value = float(nav)
        except ValueError:
            continue                      # "N.A." for a scheme not yet valued
        day = day.strip()
        # Compare as dates, not strings: "31-Oct-2025" sorts above
        # "21-Aug-2026" alphabetically, which silently reported a NAV date
        # ten months stale.
        parsed = _as_date(day)
        if parsed and (latest_parsed is None or parsed > latest_parsed):
            latest_parsed, latest_date = parsed, day
        # Short keys and shared indices: the same document with readable
        # keys and repeated house strings is 3.4 MB, which is not a thing to
        # send to a phone.
        schemes.append({
            "c": code.strip(),
            "n": name.strip(),
            "h": house,
            "g": subcategory or category,
            "p": plan.strip(),
            "o": option.strip(),
            "v": round(nav_value, 4),
            "d": day,
        })

    houses: dict[str, int] = {}
    categories: dict[str, int] = {}
    for scheme in schemes:
        houses[scheme["h"]] = houses.get(scheme["h"], 0) + 1
        categories[scheme["g"]] = categories.get(scheme["g"], 0) + 1

    # Replace repeated house strings with an index into a shared list.
    house_list = sorted(houses)
    house_index = {name: i for i, name in enumerate(house_list)}
    category_list = sorted(categories)
    category_index = {name: i for i, name in enumerate(category_list)}
    for scheme in schemes:
        scheme["h"] = house_index[scheme["h"]]
        scheme["g"] = category_index[scheme["g"]]

    return {
        "version": CACHE_VERSION,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": latest_date,
        "count": len(schemes),
        "house_names": house_list,
        "category_names": category_list,
        "houses": sorted(houses.items(), key=lambda kv: -kv[1]),
        "categories": sorted(categories.items(), key=lambda kv: -kv[1]),
        "schemes": schemes,
    }


def refresh(root: Path) -> dict:
    document = parse(fetch_raw())
    if document["count"] < 1000:
        raise FundsError(
            f"only {document['count']} schemes parsed; AMFI publishes over 10,000 "
            "— refusing to overwrite the cache with a partial file"
        )
    path = root / "funds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, separators=(",", ":")) + "\n")
    return document


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh the AMFI mutual fund cache")
    parser.add_argument("--out", default="data/live")
    args = parser.parse_args(argv)
    document = refresh(Path(args.out))
    print(
        f"{document['count']:,} schemes from {len(document['houses'])} fund houses, "
        f"NAVs as of {document['as_of']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
