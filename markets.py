"""Market discovery for Polymarket BTC 5-minute prediction markets."""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

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


def _resolve_token_ids_from_clob(
    condition_id: str, config: BotConfig, outcomes: list, up_idx: int, down_idx: int
) -> Optional[Tuple[str, str]]:
    """Resolve token IDs from CLOB API when Gamma returns '0xaddr-number' format."""
    try:
        resp = requests.get(
            f"{config.clob_host}/markets/{condition_id}",
            timeout=10,
            headers={"User-Agent": "PolymarketBot/1.0"},
        )
        resp.raise_for_status()
        market = resp.json()
        tokens = market.get("tokens", market.get("clobTokenIds", []))
        if isinstance(tokens, str):
            tokens = json.loads(tokens) if tokens else []
        if not tokens or len(tokens) < 2:
            return None
        up_outcome = outcomes[up_idx] if up_idx < len(outcomes) else "Up"
        down_outcome = outcomes[down_idx] if down_idx < len(outcomes) else "Down"
        up_tid = down_tid = None
        for t in tokens:
            if isinstance(t, dict):
                outcome = t.get("outcome", "")
                tid = t.get("token_id", t.get("tokenId", str(t)))
            else:
                outcome = ""
                tid = str(t)
            if outcome and outcome.lower() == up_outcome.lower():
                up_tid = str(tid)
            elif outcome and outcome.lower() == down_outcome.lower():
                down_tid = str(tid)
        if up_tid and down_tid and "-" not in up_tid and "-" not in down_tid:
            return up_tid, down_tid
        if len(tokens) >= 2:
            t0 = tokens[up_idx]
            t1 = tokens[down_idx]
            sid0 = str(t0.get("token_id", t0.get("tokenId", t0))) if isinstance(t0, dict) else str(t0)
            sid1 = str(t1.get("token_id", t1.get("tokenId", t1))) if isinstance(t1, dict) else str(t1)
            if "-" not in sid0 and "-" not in sid1:
                return sid0, sid1
    except Exception as e:
        logger.debug("Resolve token IDs from CLOB failed: %s", e)
    return None


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
        logger.error("Failed to fetch series from gamma-api.polymarket.com: %s", e)
        if "No route to host" in str(e) or "Failed to establish" in str(e):
            logger.error("Network can't reach Polymarket Gamma API. Try without VPN or use a different network.")
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

            up_tid = str(token_ids[up_idx])
            down_tid = str(token_ids[down_idx])
            # Gamma sometimes returns "0xaddr-number" format; order creation needs uint256 decimal string
            if "-" in up_tid or "-" in down_tid:
                resolved = _resolve_token_ids_from_clob(cond_id, config, outcomes, up_idx, down_idx)
                if resolved:
                    up_tid, down_tid = resolved
                else:
                    logger.debug("Skipping market %s: could not resolve token IDs from CLOB", cond_id[:20])
                    continue

            markets.append(
                BTCMarket(
                    event_id=event["id"],
                    event_slug=event.get("slug", ""),
                    title=event.get("title", m.get("question", "")),
                    condition_id=cond_id,
                    up_token_id=up_tid,
                    down_token_id=down_tid,
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
