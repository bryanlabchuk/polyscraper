"""Market discovery for Polymarket BTC 5-minute prediction markets."""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import requests

from config import BotConfig

logger = logging.getLogger(__name__)


@dataclass
class BTCMarket:
    """Represents a single BTC Up/Down 5m market."""

    event_id: str
    event_slug: str
    title: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    tick_size: str
    min_size: float
    end_date: str
    start_time: str
    accepting_orders: bool


def fetch_btc_5m_markets(config: BotConfig) -> list[BTCMarket]:
    """
    Fetch active BTC 5-minute Up/Down markets from Polymarket Gamma API.
    Returns markets that are currently accepting orders.
    """
    url = f"{config.gamma_host}/events"
    params = {
        "series_slug": config.btc_5m_series_slug,
        "active": "true",
        "closed": "false",
        "limit": 20,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        events = resp.json()
    except requests.RequestException as e:
        logger.error("Failed to fetch events: %s", e)
        return []

    markets: list[BTCMarket] = []
    for event in events:
        slug = event.get("slug", "")
        if not slug.startswith(config.btc_5m_slug_prefix):
            continue

        for m in event.get("markets", []):
            if not m.get("enableOrderBook") or not m.get("acceptingOrders", True):
                continue

            clob_ids = m.get("clobTokenIds")
            if not clob_ids:
                continue

            try:
                token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
            except json.JSONDecodeError:
                continue

            if len(token_ids) < 2:
                continue

            # Outcomes are ["Up", "Down"] - index 0 = Up, 1 = Down
            outcomes = json.loads(m["outcomes"]) if isinstance(m["outcomes"], str) else m["outcomes"]
            up_idx = 0 if (outcomes[0] == "Up" or outcomes[0].lower() == "up") else 1
            down_idx = 1 - up_idx

            markets.append(
                BTCMarket(
                    event_id=event["id"],
                    event_slug=slug,
                    title=event.get("title", m.get("question", "")),
                    condition_id=m["conditionId"],
                    up_token_id=str(token_ids[up_idx]),
                    down_token_id=str(token_ids[down_idx]),
                    tick_size=str(m.get("orderPriceMinTickSize", "0.001")),
                    min_size=float(m.get("orderMinSize", 5)),
                    end_date=m.get("endDate", ""),
                    start_time=event.get("startTime") or event.get("startDate", ""),
                    accepting_orders=m.get("acceptingOrders", True),
                )
            )

    return markets
