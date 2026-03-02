"""Market making strategy for BTC 5-minute prediction markets."""

import logging
from datetime import datetime, timezone

from markets import BTCMarket, fetch_btc_5m_markets
from client import (
    create_client,
    get_midpoint,
    post_two_sided_quotes,
    cancel_market_orders,
)

from config import BotConfig

logger = logging.getLogger(__name__)


def compute_quotes(
    mid: float,
    spread_bps: int,
    tick_size: str,
) -> tuple[float, float]:
    """
    Compute bid and ask prices around midpoint.
    spread_bps: spread in basis points (e.g. 50 = 0.5%)
    """
    half_spread = (spread_bps / 10000) / 2
    bid = max(0.01, mid - half_spread)
    ask = min(0.99, mid + half_spread)
    return bid, ask


def should_quote_market(market: BTCMarket, config: BotConfig) -> bool:
    """
    Decide if we should quote this market.
    Skip if too close to resolution.
    """
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        mins_left = (end - now).total_seconds() / 60
        if mins_left < config.minutes_before_resolution_to_stop:
            return False
    except Exception:
        pass
    return market.accepting_orders


def run_market_making_cycle(config: BotConfig) -> None:
    """
    One cycle: discover markets, get midpoints, post/cancel quotes.
    """
    client = create_client(config, read_only=False)
    if not client:
        logger.error("No client available")
        return

    markets = fetch_btc_5m_markets(config)
    if not markets:
        logger.info("No active BTC 5m markets found")
        return

    # Limit to max_active_markets to stay under max_total_capital
    markets = markets[: config.max_active_markets]
    logger.info("Quoting %d active BTC 5m markets (max %d, $%.0f per market)",
                len(markets), config.max_active_markets, config.max_position_per_market)

    for market in markets:
        if not should_quote_market(market, config):
            continue

        # Cancel existing quotes before posting new ones
        cancel_market_orders(client, market.condition_id, config)

        mid = get_midpoint(client, market.up_token_id)
        if mid is None:
            continue

        bid, ask = compute_quotes(mid, config.spread_bps, market.tick_size)
        if bid >= ask:
            continue

        post_two_sided_quotes(
            client, market, bid, ask, config.order_size, config
        )
