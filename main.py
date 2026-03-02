#!/usr/bin/env python3
"""
Polymarket BTC 5-Minute Market Maker Bot

A market maker that posts two-sided quotes on Polymarket's 5-minute Bitcoin
Up/Down prediction markets. Earns the spread by providing liquidity.

Setup:
  1. Copy .env.example to PMSC.env
  2. Set PRIVATE_KEY (your Polygon wallet with USDC.e)
  3. Ensure token approvals are set (see README)
  4. Run: python main.py

Use DRY_RUN=true to test without placing real orders.
"""

import logging
import signal
import sys
import time

from config import BotConfig
from client import create_client, cancel_all_orders
from strategy import run_market_making_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_shutdown = False


def _on_signal(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("Shutdown requested, cancelling all orders...")
    try:
        config = BotConfig()
        if config.private_key and not config.dry_run:
            client = create_client(config, read_only=False)
            if client:
                cancel_all_orders(client, config)
                logger.info("All orders cancelled")
    except Exception as e:
        logger.error("Failed to cancel on shutdown: %s", e)


def main():
    config = BotConfig()

    if not config.private_key and not config.dry_run:
        logger.error("Set PRIVATE_KEY in PMSC.env or use DRY_RUN=true")
        sys.exit(1)

    if config.dry_run:
        logger.info("Running in DRY RUN mode - no real orders will be placed")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info("Starting BTC 5m market maker (refresh every %ds)", config.quote_refresh_seconds)

    while not _shutdown:
        try:
            run_market_making_cycle(config)
        except Exception as e:
            logger.exception("Cycle error: %s", e)

        if _shutdown:
            break

        for _ in range(config.quote_refresh_seconds):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
