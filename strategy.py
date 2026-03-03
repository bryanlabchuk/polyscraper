"""Market making strategy for BTC 5-minute prediction markets."""

import logging
import random
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


def _jitter(value: float, pct: int, enabled: bool) -> float:
    """Apply ±pct% random jitter if enabled."""
    if not enabled or pct <= 0:
        return value
    mult = 1.0 + random.uniform(-pct / 100, pct / 100)
    return value * mult


def compute_quotes(
    mid: float,
    spread_bps: int,
    tick_size: str,
    config: BotConfig,
) -> tuple[float, float]:
    """
    Compute bid and ask prices around midpoint.
    spread_bps: spread in basis points (e.g. 40 = 0.4%)
    Widens slightly near extremes (0.1, 0.9) to reduce adverse selection risk.
    With anti_snipe_jitter: adds random spread/skew to reduce predictability.
    """
    half_spread = (spread_bps / 10000) / 2
    # Near extremes, add 0.5% to each side for safety
    if mid < 0.15 or mid > 0.85:
        half_spread += 0.005

    # Anti-snipe: random jitter on each side (asymmetric spread)
    if config.anti_snipe_jitter and config.spread_jitter_pct > 0:
        bid_half = _jitter(half_spread, config.spread_jitter_pct, True)
        ask_half = _jitter(half_spread, config.spread_jitter_pct, True)
    else:
        bid_half = ask_half = half_spread

    bid = max(0.01, mid - bid_half)
    ask = min(0.99, mid + ask_half)
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

    # Shuffle market order each cycle (anti-snipe: don't always quote same market first)
    if config.anti_snipe_jitter:
        random.shuffle(markets)

    for i, market in enumerate(markets):
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

        # Anti-snipe: random delay between cancel and post (breaks predictable timing)
        if config.anti_snipe_jitter and config.cancel_post_delay_max > 0:
            delay = random.uniform(config.cancel_post_delay_min, config.cancel_post_delay_max)
            time.sleep(delay)

        mid = get_midpoint(client, market.up_token_id)
        if mid is None:
            continue

        bid, ask = compute_quotes(mid, config.spread_bps, market.tick_size, config)
        if bid >= ask:
            continue

        # Anti-snipe: random jitter on order size
        size = config.order_size
        if config.anti_snipe_jitter and config.size_jitter_pct > 0:
            size = _jitter(size, config.size_jitter_pct, True)
            size = max(market.min_size, min(size, config.max_position_per_market))

        ok = post_two_sided_quotes(
            client, market, bid, ask, size, config
        )
        if not ok:
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS

        # Anti-snipe: stagger posting to different markets (don't blast all at once)
        if config.anti_snipe_jitter and i < len(markets) - 1:
            stagger = random.uniform(config.market_stagger_min, config.market_stagger_max)
            time.sleep(stagger)
