"""
Resolution-phase actions: one-sided arb exit, arb completion.

Runs only when seconds_to_resolution is in a narrow window (e.g. < 60s)
and we have position data. Conservative: only act when conditions are clear.
"""

import logging
from typing import Optional

from client import get_best_bid, get_best_ask, post_sell_order, post_bid_only
from config import BotConfig
from markets import BTCMarket

logger = logging.getLogger(__name__)


def try_one_sided_arb_exit(
    client,
    market: BTCMarket,
    pos_up: float,
    pos_down: float,
    mid_up: float,
    config: BotConfig,
) -> bool:
    """
    If we're long one side only and it's clearly losing (< 0.18), try to sell at best bid.
    Reduces loss vs holding to 0.
    """
    if not config.arb_exit_enabled or config.dry_run:
        return False
    sec_left = _seconds_to_resolution(market)
    if sec_left > 60 or sec_left < 5:
        return False  # Too early or too late
    if pos_up > 1 and pos_down <= 0:
        # Long Up only. Up is losing if mid_up < 0.2
        if mid_up < 0.18:
            bid = get_best_bid(client, market.up_token_id)
            if bid and bid >= 0.01:
                size = min(pos_up, config.arb_exit_size or 5)
                ok = post_sell_order(client, market, market.up_token_id, bid, size, config)
                if ok:
                    logger.info("Arb exit: selling Up (loser) @ %.3f size %.0f, %ds left", bid, size, sec_left)
                return ok
    if pos_down > 1 and pos_up <= 0:
        # Long Down only. Down is losing if mid_up > 0.82 (Down price = 1 - Up)
        if mid_up > 0.82:
            bid = get_best_bid(client, market.down_token_id)
            if bid and bid >= 0.01:
                size = min(pos_down, config.arb_exit_size or 5)
                ok = post_sell_order(client, market, market.down_token_id, bid, size, config)
                if ok:
                    logger.info("Arb exit: selling Down (loser) @ %.3f size %.0f, %ds left", bid, size, sec_left)
                return ok
    return False


def try_arb_completion(
    client,
    market: BTCMarket,
    pos_up: float,
    pos_down: float,
    config: BotConfig,
) -> bool:
    """
    If we have one side filled and the other is very cheap (< 0.06) with < 45s left,
    buy the cheap side to complete the arb.
    """
    if not config.arb_completion_enabled or config.dry_run:
        return False
    sec_left = _seconds_to_resolution(market)
    if sec_left > 45 or sec_left < 5:
        return False
    ask_up = get_best_ask(client, market.up_token_id)
    ask_down = get_best_ask(client, market.down_token_id)
    if ask_up is None or ask_down is None:
        return False
    size = config.arb_completion_size or 3
    if pos_up > 1 and pos_down <= 0:
        if ask_down < 0.06:
            ok = post_bid_only(client, market, market.down_token_id, ask_down, size, config)
            if ok:
                logger.info("Arb completion: buying Down @ %.3f (had Up), %ds left", ask_down, sec_left)
            return ok
    if pos_down > 1 and pos_up <= 0:
        if ask_up < 0.06:
            ok = post_bid_only(client, market, market.up_token_id, ask_up, size, config)
            if ok:
                logger.info("Arb completion: buying Up @ %.3f (had Down), %ds left", ask_up, sec_left)
            return ok
    return False


def _seconds_to_resolution(market: BTCMarket) -> float:
    from datetime import datetime, timezone
    try:
        end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        return (end - datetime.now(timezone.utc)).total_seconds()
    except Exception:
        return 999
