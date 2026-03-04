"""
WebSocket client for Polymarket Market Channel.

Subscribes to book and price_change events for configured token IDs.
Only triggers quote updates when real price moves occur (event-driven).
"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional

import websockets
from websockets.connection import State

logger = logging.getLogger(__name__)

WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
HEARTBEAT_INTERVAL = 5  # seconds


def _book_to_summary(bids: list, asks: list) -> Optional[dict]:
    """Build book summary from WS book/price_change payload."""
    best_bid_p, best_bid_s = 0.0, 0.0
    best_ask_p, best_ask_s = 0.0, 0.0
    if bids:
        best = max(bids, key=lambda x: float(x.get("price", 0)))
        best_bid_p = float(best.get("price", 0))
        best_bid_s = float(best.get("size", 0))
    if asks:
        best = min(asks, key=lambda x: float(x.get("price", 1)))
        best_ask_p = float(best.get("price", 1))
        best_ask_s = float(best.get("size", 0))
    if best_bid_p <= 0 or best_ask_p <= 0 or best_bid_p >= best_ask_p:
        return None
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


def _extract_mid_and_book(msg: dict) -> tuple[Optional[str], Optional[float], Optional[dict]]:
    """
    Extract (asset_id, mid, book_summary) from WS message.
    Returns (asset_id, mid, book_summary) or (None, None, None) if not usable.
    """
    event_type = msg.get("event_type")
    if event_type == "book":
        asset_id = msg.get("asset_id")
        bids = msg.get("bids") or []
        asks = msg.get("asks") or []
        s = _book_to_summary(bids, asks)
        if s:
            mid = (s["best_bid"] + s["best_ask"]) / 2
            return asset_id, mid, s
    elif event_type == "price_change":
        for pc in msg.get("price_changes") or []:
            asset_id = pc.get("asset_id")
            bb = pc.get("best_bid")
            ba = pc.get("best_ask")
            if asset_id and bb is not None and ba is not None:
                try:
                    best_bid = float(bb)
                    best_ask = float(ba)
                    if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                        mid = (best_bid + best_ask) / 2
                        s = {
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "bid_vol": 0,
                            "ask_vol": 0,
                            "depth": 0,
                            "imbalance": 0.5,
                        }
                        return asset_id, mid, s
                except (TypeError, ValueError):
                    pass
    elif event_type == "best_bid_ask":
        asset_id = msg.get("asset_id")
        bb = msg.get("best_bid")
        ba = msg.get("best_ask")
        if asset_id and bb is not None and ba is not None:
            try:
                best_bid = float(bb)
                best_ask = float(ba)
                if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                    mid = (best_bid + best_ask) / 2
                    s = {
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "bid_vol": 0,
                        "ask_vol": 0,
                        "depth": 0,
                        "imbalance": 0.5,
                    }
                    return asset_id, mid, s
            except (TypeError, ValueError):
                pass
    return None, None, None


class WSClient:
    """
    Polymarket Market Channel WebSocket client.
    Subscribes to book and price_change for given asset IDs.
    """

    def __init__(
        self,
        asset_ids: list[str],
        on_price_update: Callable[[str, float, dict], None],
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
    ):
        self.asset_ids = list(set(asset_ids))
        self.on_price_update = on_price_update
        self.heartbeat_interval = heartbeat_interval
        self._ws = None
        self._running = False
        self._subscribed = set()
        self.last_activity_ts: float = 0.0  # Watchdog: updated on every message/PONG

    async def connect(self) -> bool:
        """Connect and subscribe."""
        try:
            self._ws = await websockets.connect(
                WS_MARKET_URL,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=5,
            )
            self._running = True
            self.last_activity_ts = time.time()
            await self._subscribe()
            return True
        except Exception as e:
            logger.error("WS connect failed: %s", e)
            return False

    async def _subscribe(self) -> None:
        sub = {
            "assets_ids": self.asset_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }
        await self._ws.send(json.dumps(sub))
        self._subscribed = set(self.asset_ids)
        logger.info("WS subscribed to %d assets", len(self.asset_ids))

    def _is_open(self) -> bool:
        return self._ws is not None and self._ws.state == State.OPEN

    async def _heartbeat_loop(self) -> None:
        while self._running and self._is_open():
            await asyncio.sleep(self.heartbeat_interval)
            if not self._running or not self._is_open():
                break
            try:
                await self._ws.send("PING")
            except Exception as e:
                logger.debug("WS heartbeat failed: %s", e)
                break

    async def run(self) -> None:
        """Run the WebSocket loop (connect, heartbeat, receive)."""
        if not await self.connect():
            return
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            async for raw in self._ws:
                self.last_activity_ts = time.time()
                if not self._running:
                    break
                try:
                    msg = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    if raw == "PONG":
                        continue
                    continue
                if not isinstance(msg, dict):
                    continue
                asset_id, mid, book_summary = _extract_mid_and_book(msg)
                if asset_id and mid is not None and book_summary and asset_id in self._subscribed:
                    logger.info("Price update: %s mid=%.4f", asset_id[:16] + "...", mid)
                    try:
                        self.on_price_update(asset_id, mid, book_summary)
                    except Exception as e:
                        logger.exception("on_price_update error: %s", e)
        except websockets.ConnectionClosed as e:
            logger.info("WS connection closed: %s", e)
        except Exception as e:
            logger.exception("WS error: %s", e)
        finally:
            self._running = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    def stop(self) -> None:
        self._running = False

    async def update_subscription(self, asset_ids: list[str]) -> None:
        """Add new assets to subscription."""
        new_ids = [a for a in asset_ids if a not in self._subscribed]
        if not new_ids:
            return
        msg = {"assets_ids": new_ids, "operation": "subscribe", "custom_feature_enabled": True}
        if self._is_open():
            await self._ws.send(json.dumps(msg))
            self._subscribed.update(new_ids)
            logger.info("WS subscribed to %d more assets", len(new_ids))
