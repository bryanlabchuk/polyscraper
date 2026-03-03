"""
Fill/trade logger for analysis.

Appends each trade to fills_log.csv so you can analyze:
- Which side (buy/sell) we're getting filled on
- Price and size
- Market
- Timestamp

Run periodically from the main loop. Uses client.get_trades() and deduplicates
by trade ID to avoid re-logging.
"""

import csv
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FILLS_LOG = Path(__file__).parent / "fills_log.csv"
_seen_ids: set[str] = set()
_MAX_SEEN = 5000  # Prevent unbounded growth


def _load_seen() -> set[str]:
    """Load previously seen trade IDs from log file."""
    s = set()
    if FILLS_LOG.exists():
        try:
            with open(FILLS_LOG) as f:
                r = csv.DictReader(f)
                for row in r:
                    tid = row.get("trade_id", "")
                    if tid:
                        s.add(tid)
        except Exception:
            pass
    return s


def log_fills(client) -> int:
    """
    Fetch recent trades from CLOB, append new ones to fills_log.csv.
    Returns count of newly logged fills.
    """
    global _seen_ids
    if not hasattr(client, "get_trades") or client.get_trades is None:
        return 0

    try:
        trades = client.get_trades(params=None) or []
    except Exception as e:
        logger.debug("Fill logger: get_trades failed: %s", e)
        return 0

    if not _seen_ids:
        _seen_ids = _load_seen()

    new_count = 0
    rows = []
    for t in trades:
        tid = str(t.get("id") or t.get("tradeID") or t.get("trade_id") or "")
        if not tid:
            # Fallback: composite key for dedup
            tid = f"{t.get('timestamp','')}_{t.get('side','')}_{t.get('price','')}_{t.get('size','')}_{(t.get('eventSlug') or t.get('slug') or '')[:30]}"
        if tid in _seen_ids:
            continue
        _seen_ids.add(tid)
        new_count += 1
        rows.append({
            "trade_id": tid,
            "timestamp": t.get("timestamp", ""),
            "side": t.get("side", "?"),
            "price": t.get("price", ""),
            "size": t.get("size", ""),
            "market_slug": (t.get("eventSlug") or t.get("slug") or t.get("market") or "?")[:60],
            "condition_id": (t.get("conditionId") or t.get("condition_id") or "")[:42],
        })

    if not rows:
        return 0

    # Trim seen set
    if len(_seen_ids) > _MAX_SEEN:
        _seen_ids = set(list(_seen_ids)[-_MAX_SEEN // 2 :])

    write_header = not FILLS_LOG.exists()
    try:
        with open(FILLS_LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["trade_id", "timestamp", "side", "price", "size", "market_slug", "condition_id"])
            if write_header:
                w.writeheader()
            w.writerows(rows)
    except Exception as e:
        logger.warning("Fill logger: write failed: %s", e)
        return 0

    if new_count > 0:
        logger.debug("Logged %d new fill(s) to %s", new_count, FILLS_LOG)
    return new_count
