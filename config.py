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
    quote_refresh_seconds: int = 0  # Base seconds between cycles (0 = run immediately, near rate limit)
    minutes_before_resolution_to_stop: int = 2  # Stop quoting 2 min before resolution (safer)

    # BTC 5m market discovery
    btc_5m_series_slug: str = "btc-up-or-down-5m"
    btc_5m_slug_prefix: str = "btc-updown-5m"

    # Safety
    dry_run: bool = False

    # Anti-snipe / anti-predictability (makes strategy harder to exploit)
    anti_snipe_jitter: bool = True  # Enable spread, size, timing jitter
    spread_jitter_pct: int = 15  # Max ±% random on spread (e.g. 15 = ±15%)
    size_jitter_pct: int = 10  # Max ±% random on order size
    cancel_post_delay_min: float = 0.05  # Min seconds between cancel and post (aggressive)
    cancel_post_delay_max: float = 0.25  # Max seconds between cancel and post
    market_stagger_min: float = 0.05  # Min seconds between posting to different markets
    market_stagger_max: float = 0.35  # Max seconds between posting to different markets
    cycle_jitter_seconds: int = 2  # Add 0 to N seconds random to each cycle (keeps some unpredictability)

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
        self.anti_snipe_jitter = os.getenv("ANTI_SNIPE_JITTER", "true").lower() in ("true", "1", "yes")
        self.spread_jitter_pct = int(os.getenv("SPREAD_JITTER_PCT", str(self.spread_jitter_pct)))
        self.size_jitter_pct = int(os.getenv("SIZE_JITTER_PCT", str(self.size_jitter_pct)))
        self.cancel_post_delay_min = float(os.getenv("CANCEL_POST_DELAY_MIN", str(self.cancel_post_delay_min)))
        self.cancel_post_delay_max = float(os.getenv("CANCEL_POST_DELAY_MAX", str(self.cancel_post_delay_max)))
        self.market_stagger_min = float(os.getenv("MARKET_STAGGER_MIN", str(self.market_stagger_min)))
        self.market_stagger_max = float(os.getenv("MARKET_STAGGER_MAX", str(self.market_stagger_max)))
        self.cycle_jitter_seconds = int(os.getenv("CYCLE_JITTER_SECONDS", str(self.cycle_jitter_seconds)))
