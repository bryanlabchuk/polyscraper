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
import random
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

# Reduce httpx/HTTP noise (400 on api-key is expected before derive)
logging.getLogger("httpx").setLevel(logging.WARNING)

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

    # Log wallet and links for viewing transactions
    try:
        from client import create_client
        _c = create_client(config, read_only=True)
        if _c and config.private_key:
            addr = _c.get_address()
            if addr:
                logger.info("Wallet: %s", addr)
                logger.info("View transactions: https://polygonscan.com/address/%s", addr)
    except Exception:
        pass

    # Auto-scale from wallet USDC (same as main_ws.py)
    if getattr(config, "auto_scale_from_balance", True):
        try:
            _c = create_client(config, read_only=False)
            if _c:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=config.signature_type)
                bal_resp = _c.get_balance_allowance(params)
                raw = float(bal_resp.get("balance") or bal_resp.get("currentBalance") or 0) if isinstance(bal_resp, dict) else float(getattr(bal_resp, "balance", 0) or 0)
                balance_usdc = raw / 1e6 if raw > 1e4 else raw
                if balance_usdc > 10:
                    effective = balance_usdc * 0.85
                    n = max(1, config.max_active_markets)
                    per_market = effective / n
                    config.max_total_capital = effective
                    config.max_position_per_market = max(10, min(config.max_position_per_market, per_market * 0.5))
                    config.order_size = max(5, min(config.order_size, per_market * 0.2))
                    config.inventory_cap_usd = effective * 0.25
                    logger.info("Auto-scale from $%.1f USDC: order_size=$%.1f max_pos=$%.1f", balance_usdc, config.order_size, config.max_position_per_market)
        except Exception as e:
            logger.debug("Auto-scale from balance: %s", e)

    j = getattr(config, "cycle_jitter_seconds", 0)
    logger.info("Starting BTC 5m market maker (cycle: %ds%s)",
               config.quote_refresh_seconds, f" + 0-{j}s jitter" if j > 0 else "")

    while not _shutdown:
        try:
            run_market_making_cycle(config)
        except Exception as e:
            logger.exception("Cycle error: %s", e)

        if _shutdown:
            break

        # Base interval + random jitter (anti-snipe: unpredictable cycle timing)
        base_sleep = config.quote_refresh_seconds
        jitter = random.randint(0, config.cycle_jitter_seconds) if config.anti_snipe_jitter else 0
        total_sleep = base_sleep + jitter
        for _ in range(total_sleep):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
