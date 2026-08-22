"""Capped auto-invest for India via Zerodha Kite Connect — opt-in, dry-run first.

What "automated" can honestly mean on Zerodha: order placement, holdings and
positions are free on the Kite Connect **Personal** tier — the ₹2,000 charge
that used to apply now buys market data, which this app does not need because
it has its own. What has not changed is that the access token expires at 6 AM
the next day by regulatory requirement, so Zerodha requires a fresh login each
trading morning and a fully hands-off loop is not possible for a retail
account. The supported flow is: log in once each
trading morning, export the access token, and let this module place the day's
fresh signals within the cap. SEBI's algo-trading framework applies to
API-driven retail orders; check your broker's approval requirements before
going live.

Safety model (same shape as the US executor):
- **Dry-run by default.** Without ``--live`` this only prints what it would do.
- **Live needs credentials AND intent**: ``KITE_API_KEY`` + ``KITE_ACCESS_TOKEN``
  in the environment, plus the explicit ``--live`` flag.
- **The daily cap survives restarts.** Every accepted order is journalled to
  ``data/executions/kite-YYYY-MM-DD.json``; the cap check reads the journal,
  so re-running the command cannot double-spend the cap.
- **Only fresh BUY signals from today's snapshot are eligible.** Sells,
  resting orders and anything not in the snapshot are refused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

KITE_ORDERS_URL = "https://api.kite.trade/orders/regular"


class ExecutionRefused(RuntimeError):
    """An order was refused before reaching the broker."""


def _journal_path(root: Path, day: date) -> Path:
    return root / "executions" / f"kite-{day.isoformat()}.json"


def read_spent(root: Path, day: date) -> Decimal:
    path = _journal_path(root, day)
    if not path.exists():
        return Decimal("0")
    records = json.loads(path.read_text())
    return sum((Decimal(r["notional"]) for r in records), Decimal("0"))


def append_journal(root: Path, day: date, record: dict) -> None:
    path = _journal_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(path.read_text()) if path.exists() else []
    records.append(record)
    path.write_text(json.dumps(records, indent=1) + "\n")


def eligible_orders(snapshot: dict) -> list[dict]:
    return [
        order
        for order in snapshot.get("orders", [])
        if order["region"] == "india" and order["fresh"] and order["side"] == "BUY"
    ]


def plan(snapshot: dict, cap: Decimal, spent: Decimal) -> tuple[list[dict], list[str]]:
    """Fit eligible orders under the remaining cap, in snapshot priority order."""
    accepted: list[dict] = []
    skipped: list[str] = []
    remaining = cap - spent
    for order in eligible_orders(snapshot):
        notional = Decimal(order["notional"] or "0")
        if notional <= 0:
            skipped.append(f"{order['symbol']}: no reference notional")
            continue
        if notional > remaining:
            skipped.append(
                f"{order['symbol']}: {notional:,.0f} INR exceeds remaining cap {remaining:,.0f}"
            )
            continue
        accepted.append(order)
        remaining -= notional
    return accepted, skipped


def place_order(order: dict, api_key: str, access_token: str) -> str:
    payload = dict(order["kite"])
    payload.pop("readonly", None)
    payload["validity"] = "DAY"
    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(
        KITE_ORDERS_URL,
        data=data,
        headers={
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("message", str(error))
        except Exception:  # noqa: BLE001
            detail = str(error)
        raise ExecutionRefused(f"Kite rejected {order['symbol']}: {detail}") from error
    order_id = body.get("data", {}).get("order_id")
    if not order_id:
        raise ExecutionRefused(f"Kite returned no order id for {order['symbol']}: {body}")
    return str(order_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Place today's fresh India BUY signals on Zerodha, within the daily cap"
    )
    parser.add_argument("--data", type=Path, default=Path("data/live"))
    parser.add_argument("--config", type=Path, default=Path("config/live.json"))
    parser.add_argument("--live", action="store_true",
                        help="actually place orders (default: dry run)")
    args = parser.parse_args(argv)

    from ..signals.live import generate, load_live_config

    live_config = load_live_config(args.config)
    cap = Decimal(str(live_config["daily_cap"].get("INR", "0")))
    if cap <= 0:
        print("daily_cap.INR is 0 in config — nothing to do", file=sys.stderr)
        return 1

    snapshot, _report = generate(args.data, args.config)
    today = date.today()
    as_of = snapshot["as_of"].get("india")
    if as_of != today.isoformat():
        print(
            f"note: latest India session in cache is {as_of}, today is {today} — "
            "signals fire at the NEXT open, so this is expected before close",
        )

    spent = read_spent(args.data, today)
    accepted, skipped = plan(snapshot, cap, spent)

    print(f"cap {cap:,.0f} INR, already spent today {spent:,.0f} INR")
    for line in skipped:
        print(f"skip  {line}")
    if not accepted:
        print("no orders fit under the cap today")
        return 0
    for order in accepted:
        print(
            f"plan  BUY {order['quantity']} {order['symbol']} "
            f"@ ~{order['reference_price']} = {Decimal(order['notional']):,.0f} INR"
        )

    if not args.live:
        print("\ndry run — pass --live with KITE_API_KEY and KITE_ACCESS_TOKEN set to execute")
        return 0

    api_key = os.environ.get("KITE_API_KEY", "")
    access_token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if not api_key or not access_token:
        print("KITE_API_KEY / KITE_ACCESS_TOKEN not set — refusing live run", file=sys.stderr)
        return 1

    failures = 0
    for order in accepted:
        try:
            order_id = place_order(order, api_key, access_token)
        except ExecutionRefused as error:
            failures += 1
            print(f"FAIL  {error}", file=sys.stderr)
            continue
        append_journal(
            args.data,
            today,
            {
                "order_id": order_id,
                "symbol": order["symbol"],
                "quantity": order["quantity"],
                "notional": order["notional"],
                "reference_price": order["reference_price"],
            },
        )
        print(f"sent  {order['symbol']} → Kite order {order_id}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
