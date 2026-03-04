#!/usr/bin/env python3
"""
Polymarket BTC 5-Minute Market Maker Bot (WebSocket)

Event-driven market maker using Polymarket WebSocket for book and price_change.
Updates quotes only when a real price move occurs (no REST polling).

Setup: Same as main.py (PMSC.env, PRIVATE_KEY).
Run: python main_ws.py
"""

import asyncio
import logging
import signal
import sys

from config import BotConfig
from client import create_client, cancel_all_orders, count_open_orders
from markets import BTCMarket, fetch_btc_5m_markets
from strategy import run_single_market_quote, run_market_making_cycle, _minutes_to_resolution
from fill_logger import log_fills
from ws_client import WSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

_shutdown = False
_ws_client_ref = None  # Set when running for legacy signal handler
MARKET_REFRESH_SECONDS = 300  # 5 min
HEARTBEAT_LOG_SECONDS = 30  # Log alive status every N seconds


def _build_token_to_market(markets: list[BTCMarket]) -> dict[str, BTCMarket]:
    """Map up_token_id and down_token_id to market (quote updates use up_token_id)."""
    out: dict[str, BTCMarket] = {}
    for m in markets:
        out[m.up_token_id] = m
        out[m.down_token_id] = m
    return out


def _refresh_markets(config: BotConfig) -> tuple[list[BTCMarket], list[str]]:
    """Fetch markets and return (markets, all_token_ids)."""
    markets = fetch_btc_5m_markets(config)
    if not markets:
        return [], []
    all_markets = sorted(markets, key=lambda m: _minutes_to_resolution(m), reverse=True)
    active = all_markets[: config.max_active_markets]
    token_ids = list(dict.fromkeys(t for m in active for t in [m.up_token_id, m.down_token_id]))
    return active, token_ids


async def _market_refresh_loop(
    ws_client: WSClient,
    token_to_market: dict[str, BTCMarket],
    config: BotConfig,
) -> None:
    """Periodically refresh markets and update WS subscription."""
    while not _shutdown:
        await asyncio.sleep(MARKET_REFRESH_SECONDS)
        if _shutdown:
            break
        try:
            markets, token_ids = _refresh_markets(config)
            if not token_ids:
                continue
            mapping = _build_token_to_market(markets)
            token_to_market.clear()
            token_to_market.update(mapping)
            await ws_client.update_subscription(token_ids)
            logger.info("Markets refreshed, subscribed to %d tokens", len(token_ids))
        except Exception as e:
            logger.exception("Market refresh error: %s", e)


def _on_price_update_sync(
    client,
    token_to_market: dict[str, BTCMarket],
    config: BotConfig,
    books_cache: dict[str, dict],
    asset_id: str,
    mid: float,
    book_summary: dict,
) -> None:
    """Sync handler: run quote update for the market. Up token: use mid. Down token: mid_up = 1 - mid."""
    market = token_to_market.get(asset_id)
    if not market:
        return
    books_cache[asset_id] = book_summary
    if asset_id == market.up_token_id:
        run_single_market_quote(client, market, mid, book_summary, config, books_cache)
    else:
        mid_up = 1.0 - mid
        run_single_market_quote(client, market, mid_up, book_summary, config, books_cache)


async def main_async() -> None:
    config = BotConfig()

    if not config.private_key and not config.dry_run:
        logger.error("Set PRIVATE_KEY in PMSC.env or use DRY_RUN=true")
        sys.exit(1)

    if config.dry_run:
        logger.info("Running in DRY RUN mode - no real orders will be placed")

    client = create_client(config, read_only=False)
    if not client:
        logger.error("No client available")
        sys.exit(1)

    try:
        if config.private_key:
            addr = client.get_address()
            if addr:
                logger.info("Wallet: %s", addr)
    except Exception:
        pass

    markets, token_ids = _refresh_markets(config)
    if not token_ids:
        logger.info("No active BTC 5m markets found")
        return

    token_to_market = _build_token_to_market(markets)
    books_cache: dict[str, dict] = {}

    def on_price_update(asset_id: str, mid: float, book_summary: dict) -> None:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            _on_price_update_sync,
            client,
            token_to_market,
            config,
            books_cache,
            asset_id,
            mid,
            book_summary,
        )

    ws_client = WSClient(
        asset_ids=token_ids,
        on_price_update=on_price_update,
        heartbeat_interval=5.0,
    )
    global _ws_client_ref
    _ws_client_ref = ws_client

    logger.info(
        "Starting WebSocket market maker: %d markets, %d tokens, 5s heartbeat",
        len(markets),
        len(token_ids),
    )

    # Bootstrap: one full quote cycle to get orders in the book immediately
    logger.info("Bootstrap: posting initial quotes for %d markets...", len(markets))
    try:
        run_market_making_cycle(config)
        n = count_open_orders(client)
        if n >= 0:
            logger.info("Open orders on Polymarket: %d (if 0, check token approvals)", n)
    except Exception as e:
        logger.warning("Bootstrap cycle error: %s", e)

    if config.fill_logging_enabled:
        try:
            log_fills(client)
        except Exception:
            pass

    def _request_shutdown() -> None:
        global _shutdown
        _shutdown = True
        ws_client.stop()
        logger.info("Shutdown requested, cancelling orders...")
        if config.private_key and not config.dry_run:
            try:
                cancel_all_orders(client, config)
                logger.info("All orders cancelled")
            except Exception as e:
                logger.error("Failed to cancel on shutdown: %s", e)

    try:
        asyncio.get_running_loop().add_signal_handler(
            signal.SIGINT,
            _request_shutdown,
        )
        asyncio.get_running_loop().add_signal_handler(
            signal.SIGTERM,
            _request_shutdown,
        )
    except NotImplementedError:
        pass

    async def _heartbeat_log_loop() -> None:
        """Log periodic status so the terminal shows activity."""
        while not _shutdown:
            await asyncio.sleep(HEARTBEAT_LOG_SECONDS)
            if _shutdown:
                break
            n = len(token_to_market) // 2  # up+down per market
            logger.info("Heartbeat: WS connected, %d markets, %d tokens", n, len(token_to_market))

    refresh_task = asyncio.create_task(_market_refresh_loop(ws_client, token_to_market, config))
    heartbeat_task = asyncio.create_task(_heartbeat_log_loop())
    ws_task = asyncio.create_task(ws_client.run())

    done, pending = await asyncio.wait(
        [refresh_task, heartbeat_task, ws_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    for t in [refresh_task, heartbeat_task, ws_task]:
        try:
            await t
        except asyncio.CancelledError:
            pass
    ws_client.stop()


def _on_signal(signum, frame) -> None:
    global _shutdown
    _shutdown = True
    if _ws_client_ref:
        _ws_client_ref.stop()
    logger.info("Shutdown requested...")
    try:
        config = BotConfig()
        if config.private_key and not config.dry_run:
            client = create_client(config, read_only=False)
            if client:
                cancel_all_orders(client, config)
                logger.info("All orders cancelled")
    except Exception as e:
        logger.error("Failed to cancel on shutdown: %s", e)


def main() -> None:
    global _shutdown
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    asyncio.run(main_async())
    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
