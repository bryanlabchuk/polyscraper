"""
Estimate positions from trade history for resolution actions.

Maps trades to condition_id and token (Up vs Down) to compute net position.
Used for: one-sided arb exit, arb completion.
"""

import logging
from typing import Optional

from markets import BTCMarket

logger = logging.getLogger(__name__)

# condition_id -> (position_up, position_down) in shares
# Positive = long, negative = short
_cached: dict[str, tuple[float, float]] = {}
_cache_ts: float = 0
CACHE_TTL = 10  # seconds


def _infer_outcome(trade: dict, market: BTCMarket) -> Optional[str]:
    """
    Infer whether trade was on Up or Down from trade dict.
    Trades may have: outcome, asset_id, token_id, or we match by market.
    """
    outcome = (trade.get("outcome") or trade.get("side") or "").lower()
    asset = str(trade.get("asset_id") or trade.get("assetId") or trade.get("token_id") or "")
    if asset and market.up_token_id and asset == market.up_token_id:
        return "up"
    if asset and market.down_token_id and asset == market.down_token_id:
        return "down"
    if "up" in outcome or "yes" in outcome:
        return "up"
    if "down" in outcome or "no" in outcome:
        return "down"
    return None


def estimate_positions(
    client,
    markets: list[BTCMarket],
) -> dict[str, tuple[float, float]]:
    """
    Estimate (position_up, position_down) per condition_id from trades.
    Buy = +size, Sell = -size.
    """
    import time
    try:
        trades = client.get_trades(params=None) or []
    except Exception:
        return {}

    slug_to_market = {m.event_slug: m for m in markets}
    pos: dict[str, tuple[float, float]] = {}

    for t in trades:
        slug = t.get("eventSlug") or t.get("slug") or ""
        if not slug or slug not in slug_to_market:
            continue
        market = slug_to_market[slug]
        cid = market.condition_id
        if cid not in pos:
            pos[cid] = (0.0, 0.0)
        pu, pd = pos[cid]
        side = (t.get("side") or "").lower()
        size = float(t.get("size") or 0)
        if size <= 0:
            continue
        outcome = _infer_outcome(t, market)
        is_buy = side.lower() in ("buy", "b")
        if outcome == "up":
            pu += size if is_buy else -size
        elif outcome == "down":
            pd += size if is_buy else -size
        else:
            # Can't infer: skip
            continue
        pos[cid] = (pu, pd)
    return pos
