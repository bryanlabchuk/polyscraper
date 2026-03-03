"""Market making strategy for BTC 5-minute prediction markets."""

import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

from markets import BTCMarket, fetch_btc_5m_markets
from client import (
    create_client,
    get_midpoint,
    get_midpoint_and_book,
    get_book_depth,
    post_two_sided_quotes,
    post_secondary_quotes,
    cancel_market_orders,
    fee_rate_available,
    get_arb_opportunity,
    post_arb_bids,
    execute_arb_taker,
)

from config import BotConfig
from seeking import fetch_signal, SeekingSignal
from fill_logger import log_fills
from adaptive import (
    record_mid,
    get_resolution_spread_mult,
    get_resolution_size_mult,
    get_momentum_skew_bps,
    get_volatility_extra_bps,
)
from positions import estimate_positions
from resolution_actions import try_one_sided_arb_exit, try_arb_completion

logger = logging.getLogger(__name__)

# Cooldown for markets that fail (e.g. fee-rate 404). condition_id -> retry_after_ts
_market_fail_cooldown: dict[str, float] = {}
# Trailing midpoint: don't update quotes until mid moves enough. condition_id -> last_quoted_mid
_last_quoted_mid: dict[str, float] = {}
COOLDOWN_SECONDS = 300  # 5 min


def _jitter(value: float, pct: int, enabled: bool) -> float:
    """Apply ±pct% random jitter if enabled."""
    if not enabled or pct <= 0:
        return value
    mult = 1.0 + random.uniform(-pct / 100, pct / 100)
    return value * mult


def _imbalance_skew(imbalance: float, config: BotConfig) -> float:
    """Skew mid by book imbalance: bid-heavy -> skew up, ask-heavy -> skew down."""
    if config.imbalance_skew_bps <= 0:
        return 0.0
    # imbalance > 0.5 = more bids than asks -> price may drift up
    skew = (imbalance - 0.5) * (config.imbalance_skew_bps / 10000) * 2  # ±imbalance_skew_bps
    return skew


def compute_quotes(
    mid: float,
    spread_bps: int,
    tick_size: str,
    config: BotConfig,
    condition_id: str = "",
    imbalance: Optional[float] = None,
    seeking_signal: Optional[SeekingSignal] = None,
    minutes_left: Optional[float] = None,
) -> tuple[float, float]:
    """
    Compute bid and ask prices around midpoint.
    spread_bps: spread in basis points (e.g. 40 = 0.4%)
    Widens slightly near extremes (0.1, 0.9) to reduce adverse selection risk.
    With anti_snipe_jitter: adds random spread/skew to reduce predictability.
    With volatility: adds extra spread when mid has been moving.
    imbalance: bid_vol/(bid_vol+ask_vol); if provided, skews mid toward imbalance.
    minutes_left: for resolution-aware spread widening.
    """
    # Seeking pipeline skew
    if seeking_signal and seeking_signal.skew_bps != 0:
        mid = seeking_signal.apply_skew(mid)
    # Book imbalance skew
    if imbalance is not None:
        mid = mid + _imbalance_skew(imbalance, config)
        mid = max(0.01, min(0.99, mid))
    # Momentum skew: toward recent price direction (adaptive)
    if condition_id and getattr(config, "adaptive_momentum_skew", True):
        mom = get_momentum_skew_bps(condition_id, mid, config)
        if mom != 0:
            mid = mid + mom / 10000
            mid = max(0.01, min(0.99, mid))
    half_spread = (spread_bps / 10000) / 2
    # Resolution: widen spread in last minutes (adaptive)
    if minutes_left is not None and getattr(config, "resolution_spread_widen", True):
        mult = get_resolution_spread_mult(minutes_left, config)
        half_spread *= mult
    # Seeking pipeline: add extra spread
    if seeking_signal and seeking_signal.spread_extra_bps > 0:
        half_spread += (seeking_signal.spread_extra_bps / 10000) / 2
    # Volatility: adaptive scaling from mid range
    if condition_id:
        extra = get_volatility_extra_bps(condition_id, mid, config)
        if extra > 0:
            half_spread += (extra / 10000) / 2
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


def _seconds_to_resolution(market: BTCMarket) -> float:
    """Seconds until market resolution."""
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        return (end - datetime.now(timezone.utc)).total_seconds()
    except Exception:
        return 999


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

    # Log new fills to fills_log.csv for analysis
    if config.fill_logging_enabled:
        try:
            log_fills(client)
        except Exception:
            pass

    markets = fetch_btc_5m_markets(config)
    if not markets:
        logger.info("No active BTC 5m markets found")
        return

    # Sort by time to resolution descending (most time first)
    all_markets = sorted(markets, key=lambda m: _minutes_to_resolution(m), reverse=True)
    markets = all_markets[: config.max_active_markets]

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

        # Midpoint: use book-based when valid, else API
        book_summary = None
        if config.use_book_mid:
            mid, book_summary = get_midpoint_and_book(client, market.up_token_id)
        else:
            mid = get_midpoint(client, market.up_token_id)
        if mid is None:
            continue

        mins_left = _minutes_to_resolution(market)
        record_mid(market.condition_id, mid)

        # Trailing midpoint: don't chase small moves (reduces churn and adverse selection)
        threshold = config.trailing_mid_threshold_bps / 10000
        last = _last_quoted_mid.get(market.condition_id, mid)
        if abs(mid - last) < threshold:
            mid = last  # Use stale mid; avoid constant reposting
        else:
            _last_quoted_mid[market.condition_id] = mid

        # Thin book: skip markets with very low liquidity (high adverse selection risk)
        depth = (book_summary.get("depth") if book_summary else None) or get_book_depth(client, market.up_token_id)
        if config.min_book_depth > 0 and depth is not None and depth < config.min_book_depth:
            continue

        # Seeking: fetch signal from external data pipelines (optional)
        seeking_signal: Optional[SeekingSignal] = None
        if config.seeking_enabled and (config.seeking_pipeline_url or config.seeking_pipeline_file):
            mins_left = _minutes_to_resolution(market)
            seeking_signal = fetch_signal(
                market_slug=market.event_slug,
                condition_id=market.condition_id,
                mid=mid,
                minutes_to_resolution=mins_left,
                pipeline_url=config.seeking_pipeline_url or None,
                pipeline_file=config.seeking_pipeline_file or None,
                pipeline_method=config.seeking_pipeline_method,
                timeout=config.seeking_timeout,
                use_cache=True,
                cache_ttl=config.seeking_cache_ttl,
            )
            if seeking_signal.pause:
                continue

        imbalance = book_summary.get("imbalance") if book_summary else None
        tick = float(market.tick_size)
        # Enforce min spread = 1 tick so bid/ask stay distinct after rounding
        # 0.01 tick needs >0.006 each side (0.505 rounds to 0.50) -> 130 bps min
        min_spread_bps = max(config.spread_bps, int(tick * 13000))
        bid, ask = compute_quotes(
            mid, min_spread_bps, market.tick_size, config, market.condition_id, imbalance, seeking_signal, mins_left
        )
        if bid >= ask:
            continue

        # Anti-snipe: random jitter on order size
        size = config.order_size
        if config.anti_snipe_jitter and config.size_jitter_pct > 0:
            size = _jitter(size, config.size_jitter_pct, True)
        # Depth-scaled size
        if depth is not None and config.depth_scale_threshold > 0:
            scale = min(1.0, depth / config.depth_scale_threshold)
            size *= scale
        # Granular resolution size scaling (5,4,3,2,1 min thresholds)
        if config.size_scale_near_resolution:
            size *= get_resolution_size_mult(mins_left, config)
        # Seeking: scale size by pipeline signal
        if seeking_signal and seeking_signal.size_mult != 1.0:
            size *= seeking_signal.size_mult
        # Cap by per-market limit and capital budget (max_total / num markets)
        per_market_cap = config.max_total_capital / max(1, config.max_active_markets)
        size = max(market.min_size, min(size, config.max_position_per_market, per_market_cap))

        ok = post_two_sided_quotes(client, market, bid, ask, size, config)
        if ok and config.secondary_level_enabled:
            post_secondary_quotes(client, market, mid, config.spread_bps, size, config)
        if not ok:
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS

        # Arb: lock-in profit opportunities
        if config.arb_enabled and ok:
            # 1) Taker arb: if book offers both sides for < (1 - edge), take it
            opp, ask_up, ask_down, combined = get_arb_opportunity(
                client, market, config.arb_taker_min_edge
            )
            if opp and ask_up is not None and ask_down is not None:
                execute_arb_taker(
                    client, market, ask_up, ask_down,
                    min(config.arb_taker_size, size * 0.5),
                    config,
                )
            # 2) Arb bids: primary 0.48 + deep 0.47 when mid ~0.5
            if 0.35 <= mid <= 0.65:
                post_arb_bids(client, market, config, mid=mid)

        # Anti-snipe: stagger posting to different markets
        if config.anti_snipe_jitter and i < len(markets) - 1:
            stagger = random.uniform(config.market_stagger_min, config.market_stagger_max)
            time.sleep(stagger)

    # Resolution pass: one-sided arb exit, arb completion (5–90 sec to resolution)
    try:
        resolution_markets = [
            m for m in all_markets
            if 5 < _seconds_to_resolution(m) < 90
        ]
        if resolution_markets:
            positions = estimate_positions(client, resolution_markets)
            for m in resolution_markets:
                pos = positions.get(m.condition_id, (0, 0))
                if pos[0] == 0 and pos[1] == 0:
                    continue
                mid = get_midpoint(client, m.up_token_id)
                if mid is None:
                    continue
                try_one_sided_arb_exit(client, m, pos[0], pos[1], mid, config)
                try_arb_completion(client, m, pos[0], pos[1], config)
    except Exception as e:
        logger.debug("Resolution pass: %s", e)
