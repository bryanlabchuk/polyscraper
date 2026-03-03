"""
Adaptive algorithms for the market maker.

- Resolution-aware: spread widen and size scaling as resolution approaches
- Momentum skew: skew quotes toward recent price direction
- Volatility scaling: continuous spread adjustment based on mid range
"""

from collections import deque
from typing import Optional

from config import BotConfig

# Midpoint history: condition_id -> deque of (ts, mid) for momentum/volatility
_midpoint_history: dict[str, deque] = {}
MID_HISTORY_LEN = 20
MOMENTUM_WINDOW_SEC = 90


def record_mid(condition_id: str, mid: float) -> None:
    """Record midpoint for adaptive calculations."""
    import time
    if condition_id not in _midpoint_history:
        _midpoint_history[condition_id] = deque(maxlen=MID_HISTORY_LEN)
    _midpoint_history[condition_id].append((time.time(), mid))


def get_resolution_spread_mult(minutes_left: float, config: BotConfig) -> float:
    """
    Spread multiplier as resolution approaches. More time = 1.0, less = wider.
    Last minute = 2x spread to reduce adverse selection.
    """
    if minutes_left > 2:
        return 1.0
    if minutes_left > 1:
        return 1.0 + (2.0 - minutes_left)  # 1.0 -> 2.0 as we go from 2 to 1 min
    if minutes_left > 0.25:  # 15 sec
        return 2.0
    return 2.5  # Last 15 sec: very wide


def get_resolution_size_mult(minutes_left: float, config: BotConfig) -> float:
    """
    Granular size scaling by time to resolution.
    5+ min: 1.0, 4: 0.95, 3: 0.85, 2: 0.7, 1: 0.5, <1: 0.3
    """
    if minutes_left >= 5:
        return 1.0
    if minutes_left >= 4:
        return 0.95
    if minutes_left >= 3:
        return 0.85
    if minutes_left >= 2:
        return 0.70
    if minutes_left >= 1:
        return 0.50
    if minutes_left >= 0.5:
        return 0.35
    return 0.25


def get_momentum_skew_bps(condition_id: str, mid: float, config: BotConfig) -> float:
    """
    Skew midpoint toward recent price direction. If mid has been rising, skew up slightly.
    Returns bps to add to mid (positive = bullish skew).
    """
    import time
    if condition_id not in _midpoint_history:
        return 0.0
    q = _midpoint_history[condition_id]
    now = time.time()
    # Recent points within momentum window
    recent = [(t, m) for t, m in q if now - t < MOMENTUM_WINDOW_SEC]
    if len(recent) < 4:
        return 0.0
    first_mid = recent[0][1]
    last_mid = recent[-1][1]
    delta = last_mid - first_mid
    # Max skew ±15 bps from momentum
    max_skew_bps = 15
    if abs(delta) < 0.005:
        return 0.0
    # Scale: delta 0.02 -> ~10 bps skew
    skew = max(-max_skew_bps, min(max_skew_bps, delta * 500))
    return skew


def get_volatility_extra_bps(condition_id: str, mid: float, config: BotConfig) -> int:
    """
    Extra spread bps from recent volatility. Continuous: scale by actual range.
    """
    import time
    if config.volatility_spread_extra_bps <= 0:
        return 0
    if condition_id not in _midpoint_history:
        return 0
    q = _midpoint_history[condition_id]
    now = time.time()
    recent = [(t, m) for t, m in q if now - t < 120]
    if len(recent) < 3:
        return 0
    mids = [m for _, m in recent]
    r = max(mids) - min(mids)
    # Range > 1.5%: full extra. Linear scale below
    if r > 0.02:
        return config.volatility_spread_extra_bps
    if r > 0.015:
        return int(config.volatility_spread_extra_bps * 0.8)
    if r > 0.01:
        return int(config.volatility_spread_extra_bps * 0.5)
    return 0
