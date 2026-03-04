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

    # Wallet (SIGNATURE_TYPE=2 if using delegated/auth that is working)
    private_key: str = ""
    funder: str = ""
    signature_type: int = 0  # 0=EOA, 1=Magic/email, 2=delegated (keep if auth works)

    # Market maker params — 2026 rebate: tight spread + time-on-book
    spread_bps: int = 50  # 0.5¢ total spread (Mid±0.0025) for maker rebate zone
    order_size: float = 50.0  # Size at touch (larger = more queue priority)
    max_position_per_market: float = 50.0
    max_total_capital: float = 150.0
    max_active_markets: int = 2
    quote_refresh_seconds: int = 5  # Fast cycle (REST); use main_ws.py for event-driven
    min_quote_interval_seconds: float = 15.0  # 15s time-on-book for 2026 Loyalty Multiplier
    minutes_before_resolution_to_stop: int = 1  # Stay in longer, more risk

    # BTC 5m market discovery
    btc_5m_series_slug: str = "btc-up-or-down-5m"
    btc_5m_slug_prefix: str = "btc-updown-5m"
    # Hot zone: only quote when mid in [0.40, 0.60]; stay in fee-curve peak for quadratic reward
    high_reward_mid_min: float = 0.40
    high_reward_mid_max: float = 0.60
    # Tight-spread bonus: 0.5¢ total (mid ± 0.0025) = 100% quadratic reward score
    rebate_tight_spread: bool = True

    # Safety
    dry_run: bool = False

    # Adaptive algorithms
    adaptive_momentum_skew: bool = True  # Skew toward recent price direction
    resolution_spread_widen: bool = True  # Widen spread in last minutes

    # Order-book-based pricing
    use_book_mid: bool = True
    join_book: bool = True  # Quote at touch (or 1 tick inside with improve_by_one_tick)
    improve_by_one_tick: bool = True  # When join_book: bid+1tick, ask-1tick for queue priority
    imbalance_skew_bps: int = 20
    # Drift: don't cancel/replace unless mid moves beyond this (build time-on-book for rebates)
    min_midpoint_drift: float = 0.0025  # 0.25¢; only update if price moves more (stay on book)
    trailing_mid_threshold_bps: int = 20  # Fallback: 0.2% when min_midpoint_drift not set
    depth_scale_threshold: float = 40.0  # Scale size down when book depth < this

    # Risk controls
    volatility_spread_extra_bps: int = 15  # Less widen = stay tighter
    min_book_depth: float = 15.0  # Accept thinner books for speed
    size_scale_near_resolution: bool = True
    # Inventory cap (anti-sweep): max notional per side; over cap = quote only reducing side
    inventory_cap_usd: float = 0.0  # 0 = use 25% of max_total_capital
    rebates_poll_interval_seconds: int = 3600  # Log rebated_fees_usdc from API (hourly)

    # Speed: minimal jitter and delays for max reactivity
    anti_snipe_jitter: bool = False  # Off = no random delay, deterministic speed
    spread_jitter_pct: int = 0
    size_jitter_pct: int = 0
    cancel_post_delay_min: float = 0.0
    cancel_post_delay_max: float = 0.0  # Zero delay between cancel and post
    market_stagger_min: float = 0.0  # No delay between markets
    market_stagger_max: float = 0.0
    cycle_jitter_seconds: int = 0  # Fixed cycle, no random wait

    # Seeking: external signals (optional; off by default for pure MM)
    seeking_enabled: bool = False
    seeking_pipeline_url: str = ""  # e.g. http://localhost:8000/signal
    seeking_pipeline_file: str = ""  # e.g. ./signals.json (written by your analysis)
    seeking_pipeline_method: str = "POST"  # GET or POST
    seeking_timeout: float = 2.0
    seeking_cache_ttl: int = 30  # seconds

    # Fill logging: append trades to fills_log.csv for analysis
    fill_logging_enabled: bool = True

    # Auto-scale: size from wallet USDC balance at startup (order_size, max_position, max_total_capital)
    auto_scale_from_balance: bool = True

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
        self.min_quote_interval_seconds = float(
            os.getenv("MIN_QUOTE_INTERVAL_SECONDS", str(self.min_quote_interval_seconds))
        )
        self.minutes_before_resolution_to_stop = int(
            os.getenv("MINUTES_BEFORE_RESOLUTION_TO_STOP", str(self.minutes_before_resolution_to_stop))
        )
        self.adaptive_momentum_skew = os.getenv("ADAPTIVE_MOMENTUM_SKEW", "true").lower() in ("true", "1", "yes")
        self.resolution_spread_widen = os.getenv("RESOLUTION_SPREAD_WIDEN", "true").lower() in ("true", "1", "yes")
        self.use_book_mid = os.getenv("USE_BOOK_MID", "true").lower() in ("true", "1", "yes")
        self.join_book = os.getenv("JOIN_BOOK", "true").lower() in ("true", "1", "yes")
        self.improve_by_one_tick = os.getenv("IMPROVE_BY_ONE_TICK", "true").lower() in ("true", "1", "yes")
        self.imbalance_skew_bps = int(os.getenv("IMBALANCE_SKEW_BPS", str(self.imbalance_skew_bps)))
        self.min_midpoint_drift = float(os.getenv("MIN_MIDPOINT_DRIFT", str(self.min_midpoint_drift)))
        self.trailing_mid_threshold_bps = int(os.getenv("TRAILING_MID_THRESHOLD_BPS", str(self.trailing_mid_threshold_bps)))
        self.high_reward_mid_min = float(os.getenv("HIGH_REWARD_MID_MIN", str(self.high_reward_mid_min)))
        self.high_reward_mid_max = float(os.getenv("HIGH_REWARD_MID_MAX", str(self.high_reward_mid_max)))
        self.rebate_tight_spread = os.getenv("REBATE_TIGHT_SPREAD", "true").lower() in ("true", "1", "yes")
        self.rebates_poll_interval_seconds = int(os.getenv("REBATES_POLL_INTERVAL_SECONDS", str(self.rebates_poll_interval_seconds)))
        self.inventory_cap_usd = float(os.getenv("INVENTORY_CAP_USD", str(self.inventory_cap_usd)))
        if self.inventory_cap_usd <= 0:
            self.inventory_cap_usd = 0.25 * self.max_total_capital
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
        self.seeking_enabled = os.getenv("SEEKING_ENABLED", "false").lower() in ("true", "1", "yes")
        self.seeking_pipeline_url = os.getenv("SEEKING_PIPELINE_URL", self.seeking_pipeline_url).strip()
        self.seeking_pipeline_file = os.getenv("SEEKING_PIPELINE_FILE", self.seeking_pipeline_file).strip()
        self.seeking_pipeline_method = os.getenv("SEEKING_PIPELINE_METHOD", self.seeking_pipeline_method).upper() or "POST"
        self.seeking_timeout = float(os.getenv("SEEKING_TIMEOUT", str(self.seeking_timeout)))
        self.seeking_cache_ttl = int(os.getenv("SEEKING_CACHE_TTL", str(self.seeking_cache_ttl)))
        self.fill_logging_enabled = os.getenv("FILL_LOGGING_ENABLED", "true").lower() in ("true", "1", "yes")
        self.auto_scale_from_balance = os.getenv("AUTO_SCALE_FROM_BALANCE", "true").lower() in ("true", "1", "yes")
