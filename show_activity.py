#!/usr/bin/env python3
"""
Show your Polymarket trading activity and wallet links.

Fetches recent trades from the CLOB API and prints:
- Your wallet address
- Polygonscan link (view all on-chain transactions)
- Polymarket portfolio link
- Recent trades with side, price, size, market, timestamp
"""

import sys
from datetime import datetime, timezone

from config import BotConfig
from client import create_client

# Polygonscan and Polymarket URLs
POLYGONSCAN_BASE = "https://polygonscan.com"
POLYMARKET_PORTFOLIO = "https://polymarket.com/portfolio"


def format_trade(t: dict) -> str:
    """Format a single trade for display."""
    side = t.get("side", "?")
    price = t.get("price")
    size = t.get("size")
    ts = t.get("timestamp")
    slug = t.get("eventSlug") or t.get("slug") or t.get("title") or "Unknown"
    outcome = t.get("outcome", "")
    tx = t.get("transactionHash", "")

    parts = []
    if ts:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        parts.append(dt.strftime("%Y-%m-%d %H:%M:%S UTC"))
    parts.append(f"{side:4}")
    if price is not None:
        parts.append(f"@ {float(price):.3f}")
    if size is not None:
        parts.append(f"size {float(size):.1f}")
    if outcome:
        parts.append(f"({outcome})")
    parts.append(f"| {slug[:40]}")

    line = "  ".join(parts)
    if tx:
        line += f"\n      tx: {POLYGONSCAN_BASE}/tx/{tx}"
    return line


def main():
    config = BotConfig()
    if not config.private_key:
        print("Set PRIVATE_KEY in PMSC.env to view activity.")
        sys.exit(1)

    client = create_client(config, read_only=False)
    if not client:
        print("Failed to create client. Check PRIVATE_KEY and API credentials.")
        sys.exit(1)

    address = client.get_address()
    if not address:
        address = "unknown"

    print("=" * 60)
    print("PMSC Market Maker – Activity")
    print("=" * 60)
    print()
    print("Wallet address:", address)
    print()
    print("View on-chain transactions (USDC, CTF transfers, trades):")
    print(f"  {POLYGONSCAN_BASE}/address/{address}")
    print()
    print("Polymarket portfolio (connect this wallet):")
    print(f"  {POLYMARKET_PORTFOLIO}")
    print()

    try:
        trades = client.get_trades(params=None)
    except Exception as e:
        print(f"Failed to fetch trades: {e}")
        sys.exit(1)

    if not trades:
        print("No trades found.")
        return

    print(f"Recent trades ({len(trades)}):")
    print("-" * 60)
    for t in trades[:50]:
        print(format_trade(t))
        print()
    if len(trades) > 50:
        print(f"... and {len(trades) - 50} more")


if __name__ == "__main__":
    main()
