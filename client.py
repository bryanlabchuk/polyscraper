"""Polymarket CLOB client wrapper for market making."""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.exceptions import PolyApiException
from py_clob_client.clob_types import BookParams, OrderArgs, OrderType, PostOrdersArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL

from config import BotConfig
from markets import BTCMarket

logger = logging.getLogger(__name__)

# Reuse one client per run to avoid hitting key-derivation API every cycle (rate limits)
_cached_client: Optional[ClobClient] = None
_cached_client_key: Optional[str] = None


def clear_client_cache() -> None:
    """Clear cached client so next create_client() will re-derive API key (e.g. after 401)."""
    global _cached_client, _cached_client_key
    _cached_client = None
    _cached_client_key = None


def create_client(config: BotConfig, read_only: bool = False) -> Optional[ClobClient]:
    """Create and return an authenticated Polymarket CLOB client. Reuses cached client to avoid rate limits."""
    global _cached_client, _cached_client_key

    if not config.private_key and not read_only:
        logger.error("PRIVATE_KEY required for trading")
        return None

    if not read_only and _cached_client is not None:
        cache_key = f"{config.private_key[:16]}:{config.funder or ''}:{config.signature_type}"
        if _cached_client_key == cache_key:
            return _cached_client
        _cached_client = None
        _cached_client_key = None

    client = ClobClient(
        config.clob_host,
        key=config.private_key or "0x0000000000000000000000000000000000000000000000000000000000000001",
        chain_id=config.chain_id,
        signature_type=config.signature_type,
        funder=config.funder or None,
    )

    if not read_only and config.private_key:
        nonce = None
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
            addr = client.get_address()
            if addr and w3.is_connected():
                nonce = w3.eth.get_transaction_count(addr)
        except Exception:
            pass

        force_derive = os.environ.get("FORCE_DERIVE_API_KEY", "").lower() in ("true", "1", "yes")
        max_attempts = 3
        backoff_seconds = 60

        for attempt in range(max_attempts):
            try:
                if force_derive:
                    creds = client.derive_api_key(nonce=nonce)
                else:
                    creds = client.create_or_derive_api_creds(nonce=nonce)
                if creds:
                    client.set_api_creds(creds)
                    break
                raise ValueError("create_or_derive_api_creds returned None")
            except PolyApiException as e:
                if getattr(e, "status_code", None) == 429:
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "Polymarket rate limit (429). Waiting %ds then retry %d/%d. "
                            "If this persists, run from a different network (e.g. home) or wait 15–30 min.",
                            backoff_seconds, attempt + 2, max_attempts,
                        )
                        time.sleep(backoff_seconds)
                    else:
                        logger.error(
                            "Polymarket rate limit (429) after %d attempts. "
                            "Run from a different IP (e.g. home network or mobile hotspot) or wait 15–30 min.",
                            max_attempts,
                        )
                        return None
                else:
                    logger.error("Failed to derive API credentials: %s", e)
                    return None
            except Exception as e:
                logger.error("Failed to derive API credentials: %s", e)
                return None

    if not read_only and client is not None:
        _cached_client = client
        _cached_client_key = f"{config.private_key[:16]}:{config.funder or ''}:{config.signature_type}"
    return client


def get_midpoint(client: ClobClient, token_id: str) -> Optional[float]:
    """Get the midpoint price for a token."""
    try:
        raw = client.get_midpoint(token_id)
        if raw is None:
            return None
        if isinstance(raw, dict):
            mid = raw.get("mid") or raw.get("midpoint") or raw.get("price")
        else:
            mid = raw
        return float(mid) if mid is not None else None
    except Exception as e:
        logger.warning("Failed to get midpoint for %s: %s", token_id[:20], e)
        return None


def get_tick_size(client: ClobClient, token_id: str) -> Optional[str]:
    """Get tick size from CLOB (docs: validate before quoting)."""
    try:
        return client.get_tick_size(token_id)
    except Exception as e:
        logger.warning("Failed to get tick size for %s: %s", token_id[:20], e)
        return None


def fee_rate_available(client: ClobClient, token_id: str) -> bool:
    """
    Check if fee rate is available for this token (avoids 404 during order creation).
    Some newly listed markets don't have fee rate yet - skip them.
    """
    try:
        client.get_fee_rate_bps(token_id)
        return True
    except Exception as e:
        if hasattr(e, "status_code") and e.status_code == 404:
            return False
        err_str = str(e).lower()
        if "404" in err_str or "fee rate not found" in err_str:
            return False
        raise


def _market_expiration_ts(market: BTCMarket, buffer_seconds: int = 60) -> Optional[int]:
    """Unix timestamp when quotes should expire (market end minus buffer)."""
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        return int(end.timestamp()) - buffer_seconds
    except Exception:
        return None


def round_to_tick(price: float, tick_size: str) -> float:
    """Round price to the market's tick size."""
    tick = float(tick_size)
    return round(price / tick) * tick


def post_two_sided_quotes(
    client: ClobClient,
    market: BTCMarket,
    bid_price: float,
    ask_price: float,
    size: float,
    config: BotConfig,
) -> bool:
    """
    Post bid and ask orders on the Up token (we quote the Up side; Down = 1 - Up).
    Uses GTD to auto-expire before resolution (Polymarket best practice for events).
    Uses batch post for lower latency.
    """
    if config.dry_run:
        logger.info(
            "[DRY RUN] Would post: bid=%.3f ask=%.3f size=%.0f on %s",
            bid_price, ask_price, size, market.event_slug[:30],
        )
        return True

    tick_s = get_tick_size(client, market.up_token_id) or market.tick_size
    tick = float(tick_s)
    bid_price = round_to_tick(bid_price, tick_s)
    ask_price = round_to_tick(ask_price, tick_s)
    # Enforce bid < ask: 18 bps can round to same price with 0.01 tick
    if bid_price >= ask_price:
        ask_price = min(0.99, bid_price + tick)
    if bid_price >= ask_price:
        bid_price = max(0.01, ask_price - tick)
    size = max(size, market.min_size)

    buffer_sec = config.minutes_before_resolution_to_stop * 60
    exp_ts = _market_expiration_ts(market, buffer_sec)
    use_gtd = exp_ts is not None and exp_ts > int(datetime.now(timezone.utc).timestamp())

    orders = []
    try:
        bid_kw = dict(
            token_id=market.up_token_id,
            side=BUY,
            price=bid_price,
            size=size,
        )
        if use_gtd:
            bid_kw["expiration"] = exp_ts

        # Polymarket prediction markets use neg_risk=True (avoids 404 on some tokens)
        opts = PartialCreateOrderOptions(neg_risk=True)
        bid_order = client.create_order(OrderArgs(**bid_kw), opts)
        orders.append(
            PostOrdersArgs(
                order=bid_order,
                orderType=OrderType.GTD if use_gtd else OrderType.GTC,
            )
        )

        ask_kw = dict(
            token_id=market.up_token_id,
            side=SELL,
            price=ask_price,
            size=size,
        )
        if use_gtd:
            ask_kw["expiration"] = exp_ts

        ask_order = client.create_order(OrderArgs(**ask_kw), opts)
        orders.append(
            PostOrdersArgs(
                order=ask_order,
                orderType=OrderType.GTD if use_gtd else OrderType.GTC,
            )
        )

        resp = client.post_orders(orders)
        if isinstance(resp, list) and len(resp) > 0:
            # Batch endpoint returns list; check for invalid signature or other errors
            has_err = any(
                isinstance(r, dict) and (r.get("errorCode") or (r.get("errorMsg") and "invalid" in str(r.get("errorMsg", "")).lower()))
                for r in resp
            )
            if has_err:
                err_msg = resp[0].get("errorMsg", resp[0]) if isinstance(resp[0], dict) else resp
                logger.warning("Post orders failed: %s", err_msg)
                return False
            logger.info("Posted quotes: bid=%.3f ask=%.3f on %s", bid_price, ask_price, market.event_slug[:30])
            return True
        elif isinstance(resp, dict):
            if resp.get("errorCode") or resp.get("error"):
                logger.warning("Post orders failed: %s", resp)
                return False
            if resp.get("success") or resp.get("orderIDs") or resp.get("orderID"):
                logger.info("Posted quotes: bid=%.3f ask=%.3f on %s", bid_price, ask_price, market.event_slug[:30])
                return True
        logger.warning("Post orders unexpected response: %s", resp)
        return False
    except Exception as e:
        logger.error("Failed to post orders: %s", e)
        return False


def post_secondary_quotes(
    client: ClobClient,
    market: BTCMarket,
    mid: float,
    spread_bps: int,
    size: float,
    config: BotConfig,
) -> bool:
    """
    Post secondary level: wider spread (spread_mult × spread_bps), smaller size (size_mult × size).
    More fill opportunities without over-exposing.
    """
    if not config.secondary_level_enabled or config.secondary_size_mult <= 0:
        return True
    half = (spread_bps * config.secondary_spread_mult / 10000) / 2
    bid = max(0.01, mid - half)
    ask = min(0.99, mid + half)
    sec_size = size * config.secondary_size_mult
    return post_two_sided_quotes(client, market, bid, ask, sec_size, config)


def cancel_market_orders(client: ClobClient, condition_id: str, config: BotConfig) -> bool:
    """Cancel all orders for a given market."""
    if config.dry_run:
        logger.info("[DRY RUN] Would cancel orders for condition %s", condition_id[:20])
        return True
    try:
        client.cancel_market_orders(market=condition_id)
        return True
    except Exception as e:
        logger.error("Failed to cancel orders: %s", e)
        return False


def get_book_depth(client: ClobClient, token_id: str) -> Optional[float]:
    """Total size at best bid + best ask (USDC notional). None if unavailable."""
    try:
        book = client.get_order_book(token_id)
        if not book or (not book.bids and not book.asks):
            return None
        total = 0.0
        if book.bids:
            best_bid = max(book.bids, key=lambda b: float(b.price))
            total += float(best_bid.price or 0) * float(best_bid.size or 0)
        if book.asks:
            best_ask = min(book.asks, key=lambda a: float(a.price))
            total += float(best_ask.price or 0) * float(best_ask.size or 0)
        return total
    except Exception:
        return None


def _parse_book_to_summary(book) -> Optional[dict]:
    """Parse OrderBookSummary to our dict format. Returns None if empty."""
    if not book or (not book.bids and not book.asks):
        return None
    best_bid_p, best_bid_s = 0.0, 0.0
    best_ask_p, best_ask_s = 0.0, 0.0
    if book.bids:
        best_bid = max(book.bids, key=lambda b: float(b.price))
        best_bid_p = float(best_bid.price or 0)
        best_bid_s = float(best_bid.size or 0)
    if book.asks:
        best_ask = min(book.asks, key=lambda a: float(a.price))
        best_ask_p = float(best_ask.price or 0)
        best_ask_s = float(best_ask.size or 0)
    depth = best_bid_p * best_bid_s + best_ask_p * best_ask_s
    total_vol = best_bid_s + best_ask_s
    imbalance = best_bid_s / total_vol if total_vol > 0 else 0.5
    return {
        "best_bid": best_bid_p,
        "best_ask": best_ask_p,
        "bid_vol": best_bid_s,
        "ask_vol": best_ask_s,
        "depth": depth,
        "imbalance": imbalance,
    }


def get_order_books_batch(client: ClobClient, token_ids: list[str]) -> dict[str, Optional[dict]]:
    """
    Fetch order books for multiple tokens in ONE API call.
    Returns token_id -> book_summary (or None). Book summary has mid, depth, imbalance.
    """
    if not token_ids:
        return {}
    try:
        params = [BookParams(token_id=t) for t in token_ids]
        books = client.get_order_books(params)
    except Exception as e:
        logger.debug("Batch get_order_books failed: %s", e)
        return {t: None for t in token_ids}
    result = {}
    for i, book in enumerate(books):
        tid = token_ids[i] if i < len(token_ids) else ""
        s = _parse_book_to_summary(book)
        result[tid] = s
    return result


def get_order_book_summary(client: ClobClient, token_id: str) -> Optional[dict]:
    """Get book summary for one token (use get_order_books_batch for multiple)."""
    try:
        book = client.get_order_book(token_id)
        return _parse_book_to_summary(book)
    except Exception:
        return None


def mid_from_book_summary(s: dict) -> Optional[float]:
    """Compute midpoint from book summary if valid (best_bid < best_ask)."""
    if not s or s.get("best_bid", 0) <= 0 or s.get("best_ask", 0) <= 0:
        return None
    bb, ba = s["best_bid"], s["best_ask"]
    if bb >= ba:
        return None
    return (bb + ba) / 2


def get_midpoint_and_book(client: ClobClient, token_id: str) -> tuple[Optional[float], Optional[dict]]:
    """
    Get midpoint and order book summary in one flow.
    Uses (best_bid + best_ask)/2 when book is valid (best_bid < best_ask); else API midpoint.
    Returns (mid, book_summary). book_summary has: best_bid, best_ask, depth, imbalance.
    """
    s = get_order_book_summary(client, token_id)
    if s and s["best_bid"] > 0 and s["best_ask"] > 0 and s["best_bid"] < s["best_ask"]:
        mid = (s["best_bid"] + s["best_ask"]) / 2
        return mid, s
    mid = get_midpoint(client, token_id)
    return mid, s


def get_best_ask(client: ClobClient, token_id: str) -> Optional[float]:
    """Get best (lowest) ask price from order book."""
    try:
        book = client.get_order_book(token_id)
        if not book or not book.asks or len(book.asks) == 0:
            return None
        best = min(book.asks, key=lambda a: float(a.price))
        return float(best.price)
    except Exception as e:
        logger.debug("Failed to get best ask for %s: %s", token_id[:20], e)
        return None


def get_best_bid(client: ClobClient, token_id: str) -> Optional[float]:
    """Get best (highest) bid price from order book."""
    try:
        book = client.get_order_book(token_id)
        if not book or not book.bids or len(book.bids) == 0:
            return None
        best = max(book.bids, key=lambda b: float(b.price))
        return float(best.price)
    except Exception as e:
        logger.debug("Failed to get best bid for %s: %s", token_id[:20], e)
        return None


def post_sell_order(
    client: ClobClient,
    market: BTCMarket,
    token_id: str,
    price: float,
    size: float,
    config: BotConfig,
) -> bool:
    """Post a sell (ask) order - used for one-sided arb exit."""
    if config.dry_run:
        logger.info("[DRY RUN] Would sell %.3f size %.0f on token %s", price, size, token_id[:20])
        return True
    tick = get_tick_size(client, token_id) or market.tick_size
    price = round_to_tick(price, tick)
    size = max(size, market.min_size)
    buffer_sec = config.minutes_before_resolution_to_stop * 60
    exp_ts = _market_expiration_ts(market, buffer_sec)
    use_gtd = exp_ts is not None and exp_ts > int(datetime.now(timezone.utc).timestamp())
    try:
        opts = PartialCreateOrderOptions(neg_risk=True)
        ask_kw = dict(token_id=token_id, side=SELL, price=price, size=size)
        if use_gtd:
            ask_kw["expiration"] = exp_ts
        order = client.create_order(OrderArgs(**ask_kw), opts)
        resp = client.post_order(order, orderType=OrderType.GTD if use_gtd else OrderType.GTC)
        if resp and (isinstance(resp, list) or resp.get("orderID") or resp.get("success")):
            return True
        return False
    except Exception as e:
        logger.debug("Failed to post sell order: %s", e)
        return False


def post_bid_only(
    client: ClobClient,
    market: BTCMarket,
    token_id: str,
    price: float,
    size: float,
    config: BotConfig,
) -> bool:
    """Post a single bid order on a token (used for arb bids)."""
    if config.dry_run:
        logger.info("[DRY RUN] Would post arb bid %.3f size %.0f", price, size)
        return True
    tick = get_tick_size(client, token_id) or market.tick_size
    price = round_to_tick(price, tick)
    size = max(size, market.min_size)
    buffer_sec = config.minutes_before_resolution_to_stop * 60
    exp_ts = _market_expiration_ts(market, buffer_sec)
    use_gtd = exp_ts is not None and exp_ts > int(datetime.now(timezone.utc).timestamp())
    try:
        opts = PartialCreateOrderOptions(neg_risk=True)
        bid_kw = dict(token_id=token_id, side=BUY, price=price, size=size)
        if use_gtd:
            bid_kw["expiration"] = exp_ts
        order = client.create_order(OrderArgs(**bid_kw), opts)
        resp = client.post_order(order, orderType=OrderType.GTD if use_gtd else OrderType.GTC)
        if resp and (isinstance(resp, list) or resp.get("orderID") or resp.get("success")):
            return True
        return False
    except Exception as e:
        logger.debug("Failed to post arb bid: %s", e)
        return False


def get_arb_opportunity(
    client: ClobClient,
    market: BTCMarket,
    min_edge: float = 0.015,
    books_cache: Optional[dict] = None,
) -> tuple[bool, Optional[float], Optional[float], Optional[float]]:
    """
    Check if arb exists: best_ask(Up) + best_ask(Down) < (1 - min_edge).
    Returns (opportunity_exists, ask_up, ask_down, combined_cost).
    If books_cache provided, uses cached best_ask (avoids 2 API calls).
    """
    if books_cache:
        bu = books_cache.get(market.up_token_id)
        bd = books_cache.get(market.down_token_id)
        ask_up = float(bu["best_ask"]) if bu and bu.get("best_ask") else None
        ask_down = float(bd["best_ask"]) if bd and bd.get("best_ask") else None
    else:
        ask_up = get_best_ask(client, market.up_token_id)
        ask_down = get_best_ask(client, market.down_token_id)
    if ask_up is None or ask_down is None:
        return False, ask_up, ask_down, None
    combined = ask_up + ask_down
    threshold = 1.0 - min_edge
    return combined < threshold, ask_up, ask_down, combined


def post_arb_bids(client: ClobClient, market: BTCMarket, config: BotConfig, mid: Optional[float] = None) -> bool:
    """
    Post arb bids: primary at arb_bid_price (4%), deep at arb_bid_price_deep (6%) when mid ~0.5.
    Aggressive tier (uses aggressive_capital): deeper bids at aggressive_arb_bid_price (12% edge).
    If both sides fill, lock in profit.
    """
    if not config.arb_enabled:
        return False
    ok = True
    if config.arb_size > 0:
        price = config.arb_bid_price
        size = config.arb_size
        ok1 = post_bid_only(client, market, market.up_token_id, price, size, config)
        ok2 = post_bid_only(client, market, market.down_token_id, price, size, config)
        ok = ok1 and ok2
    # Deep arb (0.47): 6% profit when both fill; only when mid in range
    if mid is not None and 0.35 <= mid <= 0.65 and config.arb_size_deep > 0:
        price_deep = getattr(config, "arb_bid_price_deep", 0.47)
        size_deep = getattr(config, "arb_size_deep", 4.0)
        post_bid_only(client, market, market.up_token_id, price_deep, size_deep, config)
        post_bid_only(client, market, market.down_token_id, price_deep, size_deep, config)
    # Aggressive tier ($12): deeper bids for higher edge, more risky (less fill probability)
    agg_cap = getattr(config, "aggressive_capital", 0)
    agg_size = getattr(config, "aggressive_arb_size", 0)
    agg_price = getattr(config, "aggressive_arb_bid_price", 0.44)
    if mid is not None and 0.35 <= mid <= 0.65 and agg_cap > 0 and agg_size > 0:
        post_bid_only(client, market, market.up_token_id, agg_price, agg_size, config)
        post_bid_only(client, market, market.down_token_id, agg_price, agg_size, config)
        logger.info("Aggressive arb bids: %.2f @ %.2f (12%% edge pool)", agg_size, agg_price)
    return ok


def execute_arb_taker(
    client: ClobClient,
    market: BTCMarket,
    ask_up: float,
    ask_down: float,
    size: float,
    config: BotConfig,
) -> bool:
    """
    Execute arb by taking both sides at ask prices (taker - pays fees, but locks in edge).
    Uses aggressive limit orders at ask price to cross the spread.
    """
    if config.dry_run:
        logger.info("[DRY RUN] Would execute arb taker: buy Up@%.3f Down@%.3f size %.0f", ask_up, ask_down, size)
        return True
    try:
        # Place two limit buy orders at ask prices (we cross = taker)
        ok1 = post_bid_only(client, market, market.up_token_id, ask_up, size, config)
        ok2 = post_bid_only(client, market, market.down_token_id, ask_down, size, config)
        if ok1 and ok2:
            logger.info("Arb taker: bought Up@%.3f Down@%.3f (combined %.3f) size %.0f",
                        ask_up, ask_down, ask_up + ask_down, size)
        return ok1 and ok2
    except Exception as e:
        logger.warning("Arb taker failed: %s", e)
        return False


def count_open_orders(client: ClobClient) -> int:
    """Return count of open orders (diagnostic: verify orders reach Polymarket)."""
    try:
        from py_clob_client.clob_types import OpenOrderParams
        orders = client.get_orders(OpenOrderParams())
        return len(orders) if isinstance(orders, list) else 0
    except Exception as e:
        logger.debug("Failed to get open orders: %s", e)
        return -1


def cancel_all_orders(client: ClobClient, config: BotConfig) -> bool:
    """Kill switch: cancel all open orders."""
    if config.dry_run:
        logger.info("[DRY RUN] Would cancel all orders")
        return True
    try:
        client.cancel_all()
        return True
    except Exception as e:
        logger.error("Failed to cancel all: %s", e)
        return False
