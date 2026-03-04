"""Market making strategy for BTC 5-minute prediction markets."""

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from markets import BTCMarket, fetch_btc_5m_markets
from client import (
    create_client,
    get_midpoint,
    get_midpoint_and_book,
    get_order_books_batch,
    mid_from_book_summary,
    get_book_depth,
    post_two_sided_quotes,
    post_sell_order,
    post_bid_only,
    cancel_market_orders,
    fee_rate_available,
    round_to_tick,
)
from positions import estimate_positions

from config import BotConfig
from seeking import fetch_signal, SeekingSignal
from fill_logger import log_fills
from adaptive import (
    record_mid,
    get_resolution_spread_mult,
    get_resolution_size_mult,
    get_momentum_skew_bps,
    get_volatility_extra_bps,
    get_fair_price,
    get_inventory_skew,
    FAIR_PRICE_GAP_THRESHOLD,
)
logger = logging.getLogger(__name__)

# Cooldown for markets that fail (e.g. fee-rate 404). condition_id -> retry_after_ts
_market_fail_cooldown: dict[str, float] = {}
# Trailing midpoint: don't update quotes until mid moves enough. condition_id -> last_quoted_mid
_last_quoted_mid: dict[str, float] = {}
# Throttle: condition_id -> last quote timestamp (let orders sit on book long enough to get filled)
_last_quote_ts: dict[str, float] = {}
# Per-market lock: prevents overlapping cancel/post when WS fires for same market (up + down token)
_order_locks: dict[str, threading.Lock] = {}
_lock_factory = threading.Lock()
COOLDOWN_SECONDS = 300  # 5 min
MIN_QUOTE_INTERVAL_SECONDS = 2.5  # Don't cancel/repost same market more than once per 2.5s
ORDER_LOCK_TIMEOUT = 5  # Max seconds to wait for another update to finish (then skip)


def _order_lock_for(condition_id: str) -> threading.Lock:
    """Per-market lock so we never run overlapping cancel/post for the same market."""
    with _lock_factory:
        if condition_id not in _order_locks:
            _order_locks[condition_id] = threading.Lock()
        return _order_locks[condition_id]


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


def run_single_market_quote(
    client,
    market: BTCMarket,
    mid: float,
    book_summary: dict,
    config: BotConfig,
    books_cache: Optional[dict] = None,
) -> bool:
    """
    Update quotes for a single market (used by WS event-driven flow).
    Call when book or price_change indicates a real price move.
    Returns True if quotes were posted.
    """
    global _market_fail_cooldown, _last_quote_ts, _last_quoted_mid
    now = time.time()
    if market.condition_id in _market_fail_cooldown:
        return False
    # Hot zone: if mid outside [0.30, 0.70], cancel orders and don't repost (rotate off)
    mid_min = getattr(config, "high_reward_mid_min", 0.30)
    mid_max = getattr(config, "high_reward_mid_max", 0.70)
    if mid < mid_min or mid > mid_max:
        cancel_market_orders(client, market.condition_id, config)
        return False
    # Anti-manipulation: if book mid is far from fair price (our fills), use fair price
    fair = get_fair_price(client, market.event_slug)
    if fair is not None and abs(mid - fair) > FAIR_PRICE_GAP_THRESHOLD:
        mid = fair
    # Throttle: keep orders on book at least min_quote_interval (e.g. 10s for Loyalty Multiplier)
    min_interval = getattr(config, "min_quote_interval_seconds", MIN_QUOTE_INTERVAL_SECONDS)
    last_ts = _last_quote_ts.get(market.condition_id, 0)
    if now - last_ts < min_interval:
        return False
    if not should_quote_market(market, config):
        return False
    if not fee_rate_available(client, market.up_token_id):
        _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
        return False
    # Drift threshold: do not cancel or update unless mid moved > MIN_MIDPOINT_DRIFT (build time-on-book)
    drift_threshold = getattr(config, "min_midpoint_drift", None)
    if drift_threshold is None or drift_threshold <= 0:
        drift_threshold = config.trailing_mid_threshold_bps / 10000
    last = _last_quoted_mid.get(market.condition_id)
    drift = abs(mid - last) if last is not None else float("inf")
    if last is not None and drift < drift_threshold:
        return False  # Price hasn't moved enough; stay on book for rebates

    # Serialize cancel+post for this market (WS can fire for up and down token; only one update at a time)
    lock = _order_lock_for(market.condition_id)
    if not lock.acquire(blocking=True, timeout=ORDER_LOCK_TIMEOUT):
        logger.debug("Skip quote update for %s (lock timeout)", market.condition_id[:20])
        return False
    try:
        # Re-check drift after acquiring lock (other thread may have just updated)
        last = _last_quoted_mid.get(market.condition_id)
        if last is not None and abs(mid - last) < drift_threshold:
            return False
        logger.info("Significant drift detected (%.4f). Updating quotes for %s...", drift, market.event_slug[:30])
        # Cancel-then-post: only post new order after cancel is confirmed (avoids "shadow" orders)
        if not cancel_market_orders(client, market.condition_id, config):
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
            return False
        if config.anti_snipe_jitter and getattr(config, "cancel_post_delay_max", 0) > 0:
            delay = random.uniform(config.cancel_post_delay_min, config.cancel_post_delay_max)
            time.sleep(delay)

        mins_left = _minutes_to_resolution(market)
        record_mid(market.condition_id, mid)

        depth = book_summary.get("depth") or 0
        if depth > 0 and config.min_book_depth > 0 and depth < config.min_book_depth:
            return False

        seeking_signal = None
        if config.seeking_enabled and (config.seeking_pipeline_url or config.seeking_pipeline_file):
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
            if seeking_signal and seeking_signal.pause:
                return False

        imbalance = book_summary.get("imbalance")
        tick = float(market.tick_size)
        if getattr(config, "join_book", False) and book_summary:
            bb = book_summary.get("best_bid")
            ba = book_summary.get("best_ask")
            if bb is not None and ba is not None and 0 < float(bb) < float(ba) < 1:
                bbf, baf = float(bb), float(ba)
                spread_ticks = (baf - bbf) / tick
                improve = getattr(config, "improve_by_one_tick", False) and spread_ticks >= 2.0
                if improve:
                    bid = round_to_tick(bbf + tick, market.tick_size)
                    ask = round_to_tick(baf - tick, market.tick_size)
                else:
                    bid = round_to_tick(bbf, market.tick_size)
                    ask = round_to_tick(baf, market.tick_size)
                if bid >= ask:
                    ask = min(0.99, bid + tick)
            else:
                bid, ask = None, None
        else:
            bid, ask = None, None
        if bid is None or ask is None:
            min_spread_bps = max(config.spread_bps, int(tick * 13000))
            bid, ask = compute_quotes(
                mid, min_spread_bps, market.tick_size, config, market.condition_id, imbalance, seeking_signal, mins_left
            )
        # Tight-spread bonus: 0.5¢ total = 100% quadratic reward score (2026)
        if getattr(config, "rebate_tight_spread", False):
            bid = round_to_tick(mid - 0.0025, market.tick_size)
            ask = round_to_tick(mid + 0.0025, market.tick_size)
            if bid >= ask:
                ask = min(0.99, bid + tick)
        # Inventory skew: lean quotes to reduce position when over $100 or 20% of cap
        try:
            positions = estimate_positions(client, [market])
            pu, pd = positions.get(market.condition_id, (0.0, 0.0))
            bd, ad = get_inventory_skew(pu, pd, mid, config)
            if bd != 0 or ad != 0:
                bid = round_to_tick(bid + bd, market.tick_size)
                ask = round_to_tick(ask + ad, market.tick_size)
        except Exception:
            pass
        if bid >= ask:
            return False

        size = config.order_size
        if config.anti_snipe_jitter and getattr(config, "size_jitter_pct", 0) > 0:
            size = _jitter(size, config.size_jitter_pct, True)
        if depth > 0 and config.depth_scale_threshold > 0:
            size *= min(1.0, depth / config.depth_scale_threshold)
        if config.size_scale_near_resolution:
            size *= get_resolution_size_mult(mins_left, config)
        if seeking_signal and seeking_signal.size_mult != 1.0:
            size *= seeking_signal.size_mult
        per_market_cap = config.max_total_capital / max(1, config.max_active_markets)
        size = max(market.min_size, min(size, config.max_position_per_market, per_market_cap))

        # Inventory cap (anti-sweep): if over cap on one side, only quote the reducing side
        cap_usd = getattr(config, "inventory_cap_usd", 0) or (0.25 * config.max_total_capital)
        ok = False
        if cap_usd > 0:
            try:
                positions = estimate_positions(client, [market])
                pu, pd = positions.get(market.condition_id, (0.0, 0.0))
                notional_up = pu * mid
                notional_down = pd * (1.0 - mid)
                if notional_up > cap_usd:
                    ok = post_sell_order(client, market, market.up_token_id, ask, size, config)
                    if ok:
                        logger.info("Inventory cap: ask-only (reduce Up) on %s", market.event_slug[:30])
                elif notional_down > cap_usd:
                    ok = post_bid_only(client, market, market.up_token_id, bid, size, config)
                    if ok:
                        logger.info("Inventory cap: bid-only (reduce Down) on %s", market.event_slug[:30])
                else:
                    ok = post_two_sided_quotes(client, market, bid, ask, size, config)
            except Exception as e:
                logger.debug("Inventory/position check failed: %s", e)
                ok = post_two_sided_quotes(client, market, bid, ask, size, config)
        else:
            ok = post_two_sided_quotes(client, market, bid, ask, size, config)
        if ok:
            _last_quoted_mid[market.condition_id] = mid  # Only after confirmed post (avoid "shadow" orders)
            _last_quote_ts[market.condition_id] = now
        else:
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
            return False
        return True
    finally:
        lock.release()


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
    global _market_fail_cooldown, _last_quote_ts, _last_quoted_mid

    client = create_client(config, read_only=False)
    if not client:
        logger.error("No client available (often 429 rate limit). Backing off 60s.")
        time.sleep(60)
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

    # Batch-fetch order books (1 API call for all up+down tokens)
    token_ids = []
    for m in markets:
        token_ids.append(m.up_token_id)
        token_ids.append(m.down_token_id)
    token_ids = list(dict.fromkeys(token_ids))
    books_cache = get_order_books_batch(client, token_ids)

    # Shuffle market order each cycle (anti-snipe)
    if config.anti_snipe_jitter:
        random.shuffle(markets)

    drift_threshold = getattr(config, "min_midpoint_drift", None)
    if drift_threshold is None or drift_threshold <= 0:
        drift_threshold = config.trailing_mid_threshold_bps / 10000
    min_interval = getattr(config, "min_quote_interval_seconds", MIN_QUOTE_INTERVAL_SECONDS)
    mid_min = getattr(config, "high_reward_mid_min", 0.30)
    mid_max = getattr(config, "high_reward_mid_max", 0.70)

    for i, market in enumerate(markets):
        if not should_quote_market(market, config):
            continue
        if market.condition_id in _market_fail_cooldown:
            continue
        if not fee_rate_available(client, market.up_token_id):
            logger.debug("Skipping %s (fee rate not available)", market.event_slug[:30])
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
            continue

        # Get mid first (before any cancel) for drift and high-reward filter
        book_summary = books_cache.get(market.up_token_id)
        mid = mid_from_book_summary(book_summary) if (config.use_book_mid and book_summary) else None
        if mid is None:
            mid = get_midpoint(client, market.up_token_id)
        if mid is None:
            continue
        # Hot zone: outside [0.30, 0.70] = cancel and skip (rotate off)
        if mid < mid_min or mid > mid_max:
            cancel_market_orders(client, market.condition_id, config)
            continue
        # Anti-manipulation: use fair price (median of our fills) if book mid is skewed
        fair = get_fair_price(client, market.event_slug)
        if fair is not None and abs(mid - fair) > FAIR_PRICE_GAP_THRESHOLD:
            mid = fair
        # Time-on-book: don't replace if we quoted recently (Loyalty Multiplier)
        last_ts = _last_quote_ts.get(market.condition_id, 0)
        if now - last_ts < min_interval:
            continue
        # Drift: don't cancel/replace unless mid moved beyond threshold
        last = _last_quoted_mid.get(market.condition_id)
        if last is not None and abs(mid - last) < drift_threshold:
            continue

        # Cancel-then-post: only post after cancel is confirmed (avoids rate limits)
        if not cancel_market_orders(client, market.condition_id, config):
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS
            continue
        if getattr(config, "cancel_post_delay_max", 0) > 0:
            delay = random.uniform(config.cancel_post_delay_min, config.cancel_post_delay_max)
            time.sleep(delay)

        mins_left = _minutes_to_resolution(market)
        record_mid(market.condition_id, mid)
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
        # Join book: at touch or 1 tick inside for queue priority (improve_by_one_tick)
        if getattr(config, "join_book", False) and book_summary:
            bb = book_summary.get("best_bid")
            ba = book_summary.get("best_ask")
            if bb is not None and ba is not None and 0 < float(bb) < float(ba) < 1:
                bbf, baf = float(bb), float(ba)
                spread_ticks = (baf - bbf) / tick
                improve = getattr(config, "improve_by_one_tick", False) and spread_ticks >= 2.0
                if improve:
                    bid = round_to_tick(bbf + tick, market.tick_size)
                    ask = round_to_tick(baf - tick, market.tick_size)
                else:
                    bid = round_to_tick(bbf, market.tick_size)
                    ask = round_to_tick(baf, market.tick_size)
                if bid >= ask:
                    ask = min(0.99, bid + tick)
        else:
            bid, ask = None, None
        if bid is None or ask is None:
            min_spread_bps = max(config.spread_bps, int(tick * 13000))
            bid, ask = compute_quotes(
                mid, min_spread_bps, market.tick_size, config, market.condition_id, imbalance, seeking_signal, mins_left
            )
        if getattr(config, "rebate_tight_spread", False):
            bid = round_to_tick(mid - 0.0025, market.tick_size)
            ask = round_to_tick(mid + 0.0025, market.tick_size)
            if bid >= ask:
                ask = min(0.99, bid + tick)
        # Inventory skew (REST): lean quotes when position > $100 or 20% of cap
        try:
            pos_rest = estimate_positions(client, markets)
            pu, pd = pos_rest.get(market.condition_id, (0.0, 0.0))
            bd, ad = get_inventory_skew(pu, pd, mid, config)
            if bd != 0 or ad != 0:
                bid = round_to_tick(bid + bd, market.tick_size)
                ask = round_to_tick(ask + ad, market.tick_size)
        except Exception:
            pass
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
        # Seeking: scale size by pipeline signal (when enabled)
        if seeking_signal and seeking_signal.size_mult != 1.0:
            size *= seeking_signal.size_mult
        per_market_cap = config.max_total_capital / max(1, config.max_active_markets)
        size = max(market.min_size, min(size, config.max_position_per_market, per_market_cap))

        cap_usd = getattr(config, "inventory_cap_usd", 0) or (0.25 * config.max_total_capital)
        if cap_usd > 0:
            try:
                positions = estimate_positions(client, markets)
                pu, pd = positions.get(market.condition_id, (0.0, 0.0))
                notional_up = pu * mid
                notional_down = pd * (1.0 - mid)
                if notional_up > cap_usd:
                    ok = post_sell_order(client, market, market.up_token_id, ask, size, config)
                elif notional_down > cap_usd:
                    ok = post_bid_only(client, market, market.up_token_id, bid, size, config)
                else:
                    ok = post_two_sided_quotes(client, market, bid, ask, size, config)
            except Exception:
                ok = post_two_sided_quotes(client, market, bid, ask, size, config)
        else:
            ok = post_two_sided_quotes(client, market, bid, ask, size, config)
        if ok:
            _last_quote_ts[market.condition_id] = now
        else:
            _market_fail_cooldown[market.condition_id] = now + COOLDOWN_SECONDS

        # Stagger between markets (only if configured > 0)
        if i < len(markets) - 1 and getattr(config, "market_stagger_max", 0) > 0:
            stagger = random.uniform(config.market_stagger_min, config.market_stagger_max)
            time.sleep(stagger)
