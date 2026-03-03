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

    # Market maker params ($150 USDC.e preset)
    spread_bps: int = 36  # Tighter spread for more fills; volatility filter widens when needed
    order_size: float = 21.0  # USDC per side (7 × $21 ≈ $147)
    max_position_per_market: float = 21.0  # Max exposure per 5-min market
    max_total_capital: float = 150.0  # Total capital
    max_active_markets: int = 7  # More diversification (7 × $21)
    quote_refresh_seconds: int = 0  # Base seconds between cycles (0 = run immediately, near rate limit)
    minutes_before_resolution_to_stop: int = 2  # Stop quoting 2 min before resolution (safer)

    # BTC 5m market discovery
    btc_5m_series_slug: str = "btc-up-or-down-5m"
    btc_5m_slug_prefix: str = "btc-updown-5m"

    # Safety
    dry_run: bool = False

    # Arb / lock-in profit: buy both Up and Down at low prices for guaranteed payout
    arb_enabled: bool = True  # Post arb bids + take arb when book allows
    arb_bid_price: float = 0.48  # Primary arb (4% profit when both fill)
    arb_size: float = 10.0  # Primary arb size
    arb_bid_price_deep: float = 0.47  # Deep arb (6% profit); smaller size
    arb_size_deep: float = 4.0  # Deep arb size
    arb_taker_min_edge: float = 0.012  # 1.2% min edge for taker arb
    arb_taker_size: float = 10.0  # Taker arb size

    # Secondary quote level: wider spread, smaller size (more fill opportunities)
    secondary_level_enabled: bool = True
    secondary_spread_mult: float = 1.5  # 1.5× main spread
    secondary_size_mult: float = 0.4  # 40% of main size

    # Order-book-based pricing
    use_book_mid: bool = True  # Use (best_bid+best_ask)/2 when valid
    imbalance_skew_bps: int = 20  # Max skew from book imbalance (e.g. 20 = ±0.2%)
    trailing_mid_threshold_bps: int = 30  # Don't update quotes until mid moves 0.3%
    depth_scale_threshold: float = 40.0  # Scale size down when book depth < this

    # Risk controls (stricter with larger size)
    volatility_spread_extra_bps: int = 25  # Widen more when volatile
    min_book_depth: float = 25.0  # Require deeper books for larger orders
    size_scale_near_resolution: bool = True  # Reduce order size when < 4 min to resolution

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
        self.arb_enabled = os.getenv("ARB_ENABLED", "true").lower() in ("true", "1", "yes")
        self.arb_bid_price = float(os.getenv("ARB_BID_PRICE", str(self.arb_bid_price)))
        self.arb_size = float(os.getenv("ARB_SIZE", str(self.arb_size)))
        self.arb_bid_price_deep = float(os.getenv("ARB_BID_PRICE_DEEP", str(self.arb_bid_price_deep)))
        self.arb_size_deep = float(os.getenv("ARB_SIZE_DEEP", str(self.arb_size_deep)))
        self.arb_taker_min_edge = float(os.getenv("ARB_TAKER_MIN_EDGE", str(self.arb_taker_min_edge)))
        self.arb_taker_size = float(os.getenv("ARB_TAKER_SIZE", str(self.arb_taker_size)))
        self.secondary_level_enabled = os.getenv("SECONDARY_LEVEL_ENABLED", "true").lower() in ("true", "1", "yes")
        self.secondary_spread_mult = float(os.getenv("SECONDARY_SPREAD_MULT", str(self.secondary_spread_mult)))
        self.secondary_size_mult = float(os.getenv("SECONDARY_SIZE_MULT", str(self.secondary_size_mult)))
        self.use_book_mid = os.getenv("USE_BOOK_MID", "true").lower() in ("true", "1", "yes")
        self.imbalance_skew_bps = int(os.getenv("IMBALANCE_SKEW_BPS", str(self.imbalance_skew_bps)))
        self.trailing_mid_threshold_bps = int(os.getenv("TRAILING_MID_THRESHOLD_BPS", str(self.trailing_mid_threshold_bps)))
        self.depth_scale_threshold = float(os.getenv("DEPTH_SCALE_THRESHOLD", str(self.depth_scale_threshold)))
        self.volatility_spread_extra_bps = int(
            os.getenv("VOLATILITY_SPREAD_EXTRA_BPS", str(self.volatility_spread_extra_bps))
        )
        self.min_book_depth = float(os.getenv("MIN_BOOK_DEPTH", str(self.min_book_depth)))
        self.size_scale_near_resolution = os.getenv(
            "SIZE_SCALE_NEAR_RESOLUTION", "true"
        ).lower() in ("true", "1", "yes")
        self.anti_snipe_jitter = os.getenv("ANTI_SNIPE_JITTER", "true").lower() in ("true", "1", "yes")
        self.spread_jitter_pct = int(os.getenv("SPREAD_JITTER_PCT", str(self.spread_jitter_pct)))
        self.size_jitter_pct = int(os.getenv("SIZE_JITTER_PCT", str(self.size_jitter_pct)))
        self.cancel_post_delay_min = float(os.getenv("CANCEL_POST_DELAY_MIN", str(self.cancel_post_delay_min)))
        self.cancel_post_delay_max = float(os.getenv("CANCEL_POST_DELAY_MAX", str(self.cancel_post_delay_max)))
        self.market_stagger_min = float(os.getenv("MARKET_STAGGER_MIN", str(self.market_stagger_min)))
        self.market_stagger_max = float(os.getenv("MARKET_STAGGER_MAX", str(self.market_stagger_max)))
        self.cycle_jitter_seconds = int(os.getenv("CYCLE_JITTER_SECONDS", str(self.cycle_jitter_seconds)))
