"""Market making strategy for BTC 5-minute prediction markets."""

import logging
import time
from datetime import datetime, timezone

from markets import BTCMarket, fetch_btc_5m_markets
from client import (
    create_client,
    get_midpoint,
    post_two_sided_quotes,
    cancel_market_orders,
    fee_rate_available,
)

from config import BotConfig

logger = logging.getLogger(__name__)

# Cooldown for markets that fail (e.g. fee-rate 404). condition_id -> retry_after_ts
_market_fail_cooldown: dict[str, float] = {}
COOLDOWN_SECONDS = 300  # 5 min


def compute_quotes(
    mid: float,
    spread_bps: int,
    tick_size: str,
) -> tuple[float, float]:
    """
    Compute bid and ask prices around midpoint.
    spread_bps: spread in basis points (e.g. 40 = 0.4%)
    Widens slightly near extremes (0.1, 0.9) to reduce adverse selection risk.
    """
    half_spread = (spread_bps / 10000) / 2
    # Near extremes, add 0.5% to each side for safety
    if mid < 0.15 or mid > 0.85:
        half_spread += 0.005
    bid = max(0.01, mid - half_spread)
    ask = min(0.99, mid + half_spread)
    return bid, ask


def _minutes_to_resolution(market: BTCMarket) -> float:
    """Minutes until market resolution. Negative if already past."""
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        return (end - datetime.now(timezone.utc)).total_seconds() / 60
    except Exception:
        return 0


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
    Skips markets with fee-rate 404, uses cooldown for failed markets,
    prioritizes markets with more time to resolution.
    """
    global _market_fail_cooldown

    client = create_client(config, read_only=False)
    if not client:
        logger.error("No client available")
        return

    markets = fetch_btc_5m_markets(config)
    if not markets:
        logger.info("No active BTC 5m markets found")
        return

    # Sort by time to resolution descending (most time first = less resolution risk)
    markets = sorted(
        markets,
        key=lambda m: _minutes_to_resolution(m),
        reverse=True,
    )
    markets = markets[: config.max_active_markets]

    # Prune expired cooldowns
    now = time.time()
    _market_fail_cooldown = {k: v for k, v in _market_fail_cooldown.items() if v > now}

    logger.info("Quoting %d active BTC 5m markets (max %d, $%.0f per market)",
                len(markets), config.max_active_markets, config.max_position_per_market)

    for market in markets:
        if not should_quote_market(market, config):
            continue

        # Skip markets in cooldown (recent failures)
        if market.condition_id in _market_fail_cooldown:
            continue

        # Pre-check fee rate to avoid 404 during order creation
        if not fee_rate_available(client, market.up_token_id):
            logger.debug("Skipping %s (fee rate not available)", market.event_slug[:30])
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
            continue

        # Cancel existing quotes before posting new ones
        cancel_market_orders(client, market.condition_id, config)

        mid = get_midpoint(client, market.up_token_id)
        if mid is None:
            continue

        bid, ask = compute_quotes(mid, config.spread_bps, market.tick_size)
        if bid >= ask:
            continue

        ok = post_two_sided_quotes(
            client, market, bid, ask, config.order_size, config
        )
        if not ok:
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
