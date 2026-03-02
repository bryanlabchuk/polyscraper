"""Configuration for the Polymarket BTC 5m Market Maker bot."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv("PMSC.env")


@dataclass
class BotConfig:
    """Bot configuration loaded from environment."""

    # Polymarket API
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137  # Polygon

    # Wallet
    private_key: str = ""
    funder: str = ""
    signature_type: int = 0  # 0=EOA, 1=Magic/email

    # Market maker params
    spread_bps: int = 40  # 0.4% spread (40 bps) - tighter = more fills, wider = less adverse selection
    order_size: float = 14.0  # USDC per side (~$14 max exposure per 5-min market)
    max_position_per_market: float = 14.0  # Max exposure per 5-min market
    max_total_capital: float = 72.0  # Total capital to work with
    max_active_markets: int = 5  # Max markets to quote (14 * 5 = 70, under 72)
    quote_refresh_seconds: int = 25  # How often to refresh quotes (faster = more competitive)
    minutes_before_resolution_to_stop: int = 2  # Stop quoting 2 min before resolution (safer)

    # BTC 5m market discovery
    btc_5m_series_slug: str = "btc-up-or-down-5m"
    btc_5m_slug_prefix: str = "btc-updown-5m"

    # Safety
    dry_run: bool = False

    def __post_init__(self):
        self.private_key = os.getenv("PRIVATE_KEY", "").strip()
        self.funder = os.getenv("FUNDER", "").strip()
        self.signature_type = int(os.getenv("SIGNATURE_TYPE", "0"))
        self.dry_run = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
        self.order_size = float(os.getenv("ORDER_SIZE", str(self.order_size)))
        self.max_position_per_market = float(os.getenv("MAX_POSITION_PER_MARKET", str(self.max_position_per_market)))
        self.max_total_capital = float(os.getenv("MAX_TOTAL_CAPITAL", str(self.max_total_capital)))
        self.max_active_markets = int(os.getenv("MAX_ACTIVE_MARKETS", str(self.max_active_markets)))
        self.spread_bps = int(os.getenv("SPREAD_BPS", str(self.spread_bps)))
        self.quote_refresh_seconds = int(os.getenv("QUOTE_REFRESH_SECONDS", str(self.quote_refresh_seconds)))
        self.minutes_before_resolution_to_stop = int(
            os.getenv("MINUTES_BEFORE_RESOLUTION_TO_STOP", str(self.minutes_before_resolution_to_stop))
        )
