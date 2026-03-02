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
    Uses /series to get event slugs, then /events/slug/{slug} for full details.
    """
    # 1. Get series with active event slugs
    series_url = f"{config.gamma_host}/series"
    try:
        series_resp = requests.get(
            series_url,
            params={"slug": config.btc_5m_series_slug, "closed": "false"},
            timeout=10,
            headers={"User-Agent": "PolymarketBot/1.0"},
        )
        series_resp.raise_for_status()
        series_data = series_resp.json()
    except requests.RequestException as e:
        logger.error("Failed to fetch series: %s", e)
        return []

    if not series_data:
        return []

    events_brief = [
        e
        for e in series_data[0].get("events", [])
        if e.get("active") and not e.get("closed")
    ]
    # Sort by slug (timestamp) descending to get upcoming/current first
    events_brief.sort(key=lambda x: x.get("slug", ""), reverse=True)

    markets: list[BTCMarket] = []
    seen_conditions = set()

    # 2. Fetch full event details for the next few (current/upcoming windows)
    for event_brief in events_brief[: min(10, config.max_active_markets * 2)]:
        slug = event_brief.get("slug", "")
        if not slug.startswith(config.btc_5m_slug_prefix):
            continue

        try:
            event_resp = requests.get(
                f"{config.gamma_host}/events/slug/{slug}",
                timeout=10,
                headers={"User-Agent": "PolymarketBot/1.0"},
            )
            event_resp.raise_for_status()
            event_list = event_resp.json()
        except requests.RequestException as e:
            logger.debug("Failed to fetch event %s: %s", slug[:30], e)
            continue

        if not event_list:
            continue

        event = event_list[0] if isinstance(event_list, list) else event_list

        for m in event.get("markets", []):
            if not m.get("enableOrderBook") or not m.get("acceptingOrders", True):
                continue

            cond_id = m.get("conditionId")
            if cond_id in seen_conditions:
                continue
            seen_conditions.add(cond_id)

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
                    event_slug=event.get("slug", ""),
                    title=event.get("title", m.get("question", "")),
                    condition_id=cond_id,
                    up_token_id=str(token_ids[up_idx]),
                    down_token_id=str(token_ids[down_idx]),
                    tick_size=str(m.get("orderPriceMinTickSize", "0.001")),
                    min_size=float(m.get("orderMinSize", 5)),
                    end_date=m.get("endDate", ""),
                    start_time=event.get("startTime") or event.get("startDate", ""),
                    accepting_orders=m.get("acceptingOrders", True),
                )
            )
            # Fetch extra pool for strategy to sort by time-to-resolution
            if len(markets) >= config.max_active_markets * 2:
                break
        if len(markets) >= config.max_active_markets * 2:
            break

    return markets
