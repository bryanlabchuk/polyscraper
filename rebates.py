"""
Poll Polymarket rebates API for maker rebated_fees_usdc (2026 rebate tracking).
GET /rebates/current?date=YYYY-MM-DD&maker_address=0x...
"""

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


def fetch_rebates_today(maker_address: str, clob_host: str = "https://clob.polymarket.com") -> float:
    """
    Fetch today's rebated fees (USDC) for the maker address.
    Returns total rebated_fees_usdc across all entries, or 0.0 on error.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"{clob_host.rstrip('/')}/rebates/current"
    params = {"date": today, "maker_address": maker_address}
    try:
        resp = requests.get(url, params=params, timeout=15, headers={"User-Agent": "PolymarketBot/1.0"})
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return 0.0
        total = 0.0
        for entry in data:
            try:
                total += float(entry.get("rebated_fees_usdc", 0) or 0)
            except (TypeError, ValueError):
                continue
        return total
    except requests.RequestException as e:
        logger.debug("Rebates API request failed: %s", e)
        return 0.0
    except Exception as e:
        logger.debug("Rebates parse error: %s", e)
        return 0.0


def log_rebates_today(maker_address: str, clob_host: str) -> None:
    """Fetch and log today's rebated USDC to terminal."""
    total = fetch_rebates_today(maker_address, clob_host)
    logger.info("Rebates today (rebated_fees_usdc): $%.2f | wallet %s", total, maker_address[:10] + "..." if len(maker_address) > 10 else maker_address)
