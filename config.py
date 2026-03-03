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

    # Market maker params ($150 USDC.e - tuned for time-on-book and maker rebates)
    spread_bps: int = 120  # 0.01 tick needs >100 bps; 120 = 0.6% each side for valid bid<ask
    order_size: float = 50.0  # Larger size = better book priority
    max_position_per_market: float = 50.0  # Max exposure per market
    max_total_capital: float = 150.0  # Total capital
    max_active_markets: int = 2  # Concentrate capital for better priority
    quote_refresh_seconds: int = 0  # 0 = fastest cycle (near rate limit)
    minutes_before_resolution_to_stop: int = 2  # 3x more trading time vs 4 min stop

    # BTC 5m market discovery
    btc_5m_series_slug: str = "btc-up-or-down-5m"
    btc_5m_slug_prefix: str = "btc-updown-5m"

    # Safety
    dry_run: bool = False

    # Arb / lock-in profit: buy both Up and Down at low prices for guaranteed payout
    arb_enabled: bool = True
    arb_bid_price: float = 0.485  # Tighter arb = more frequent fills (0.97 cost, $1 payout)
    arb_size: float = 6.0  # Smaller arb size (one-sided fill = directional risk)
    arb_bid_price_deep: float = 0.47
    arb_size_deep: float = 2.0  # Deep arb smaller
    arb_taker_min_edge: float = 0.012  # 1.2% min edge for taker arb
    arb_taker_size: float = 10.0  # Taker arb size

    # Resolution-phase actions (low risk)
    arb_exit_enabled: bool = True  # Sell one-sided loser when clearly losing, < 60s left
    arb_exit_size: float = 5.0
    arb_completion_enabled: bool = True  # Buy cheap other side to complete arb, < 45s left
    arb_completion_size: float = 3.0

    # Secondary quote level: disabled by default (was increasing adverse selection)
    secondary_level_enabled: bool = False
    secondary_spread_mult: float = 1.5  # 1.5× main spread
    secondary_size_mult: float = 0.4  # 40% of main size

    # Adaptive algorithms
    adaptive_momentum_skew: bool = True  # Skew toward recent price direction
    resolution_spread_widen: bool = True  # Widen spread in last minutes

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
    cancel_post_delay_min: float = 0.0  # Speed: minimal delay
    cancel_post_delay_max: float = 0.03  # Max 30ms between cancel and post
    market_stagger_min: float = 0.01  # Min 10ms between markets
    market_stagger_max: float = 0.06  # Max 60ms between markets
    cycle_jitter_seconds: int = 2

    # Seeking: connect to external data pipelines for analysis-driven signals
    seeking_enabled: bool = True
    seeking_pipeline_url: str = ""  # e.g. http://localhost:8000/signal
    seeking_pipeline_file: str = ""  # e.g. ./signals.json (written by your analysis)
    seeking_pipeline_method: str = "POST"  # GET or POST
    seeking_timeout: float = 2.0
    seeking_cache_ttl: int = 30  # seconds

    # Fill logging: append trades to fills_log.csv for analysis
    fill_logging_enabled: bool = True

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
        self.arb_exit_enabled = os.getenv("ARB_EXIT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.arb_exit_size = float(os.getenv("ARB_EXIT_SIZE", str(self.arb_exit_size)))
        self.arb_completion_enabled = os.getenv("ARB_COMPLETION_ENABLED", "true").lower() in ("true", "1", "yes")
        self.arb_completion_size = float(os.getenv("ARB_COMPLETION_SIZE", str(self.arb_completion_size)))
        self.secondary_level_enabled = os.getenv("SECONDARY_LEVEL_ENABLED", "true").lower() in ("true", "1", "yes")
        self.secondary_spread_mult = float(os.getenv("SECONDARY_SPREAD_MULT", str(self.secondary_spread_mult)))
        self.secondary_size_mult = float(os.getenv("SECONDARY_SIZE_MULT", str(self.secondary_size_mult)))
        self.adaptive_momentum_skew = os.getenv("ADAPTIVE_MOMENTUM_SKEW", "true").lower() in ("true", "1", "yes")
        self.resolution_spread_widen = os.getenv("RESOLUTION_SPREAD_WIDEN", "true").lower() in ("true", "1", "yes")
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
        self.seeking_enabled = os.getenv("SEEKING_ENABLED", "true").lower() in ("true", "1", "yes")
        self.seeking_pipeline_url = os.getenv("SEEKING_PIPELINE_URL", self.seeking_pipeline_url).strip()
        self.seeking_pipeline_file = os.getenv("SEEKING_PIPELINE_FILE", self.seeking_pipeline_file).strip()
        self.seeking_pipeline_method = os.getenv("SEEKING_PIPELINE_METHOD", self.seeking_pipeline_method).upper() or "POST"
        self.seeking_timeout = float(os.getenv("SEEKING_TIMEOUT", str(self.seeking_timeout)))
        self.seeking_cache_ttl = int(os.getenv("SEEKING_CACHE_TTL", str(self.seeking_cache_ttl)))
        self.fill_logging_enabled = os.getenv("FILL_LOGGING_ENABLED", "true").lower() in ("true", "1", "yes")
