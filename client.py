"""Polymarket CLOB client wrapper for market making."""

import logging
from datetime import datetime, timezone
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, PostOrdersArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL

from config import BotConfig
from markets import BTCMarket

logger = logging.getLogger(__name__)


def create_client(config: BotConfig, read_only: bool = False) -> Optional[ClobClient]:
    """Create and return an authenticated Polymarket CLOB client."""
    if not config.private_key and not read_only:
        logger.error("PRIVATE_KEY required for trading")
        return None

    client = ClobClient(
        config.clob_host,
        key=config.private_key or "0x0000000000000000000000000000000000000000000000000000000000000001",
        chain_id=config.chain_id,
        signature_type=config.signature_type,
        funder=config.funder or None,
    )

    if not read_only and config.private_key:
        try:
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)
        except Exception as e:
            logger.error("Failed to derive API credentials: %s", e)
            return None

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

    # Prefer tick size from CLOB (docs: look up before quoting)
    tick = get_tick_size(client, market.up_token_id) or market.tick_size
    bid_price = round_to_tick(bid_price, tick)
    ask_price = round_to_tick(ask_price, tick)
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
            # Batch endpoint returns list of order responses
            logger.info("Posted quotes: bid=%.3f ask=%.3f on %s", bid_price, ask_price, market.event_slug[:30])
            return True
        elif isinstance(resp, dict) and (resp.get("success") or resp.get("orderIDs") or resp.get("orderID")):
            logger.info("Posted quotes: bid=%.3f ask=%.3f on %s", bid_price, ask_price, market.event_slug[:30])
            return True
        logger.warning("Post orders response: %s", resp)
        return False
    except Exception as e:
        logger.error("Failed to post orders: %s", e)
        return False


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
