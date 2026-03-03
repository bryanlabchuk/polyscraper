"""
Data pipeline connector for the market maker bot.

Fetches signals from external data sources (HTTP API or local file) to inform
quote decisions: skew, spread adjustment, pause, and size scaling.

Expected signal format (JSON):
{
  "skew_bps": 10,        // positive = skew Up (bullish), negative = skew Down
  "spread_extra_bps": 5, // add to spread (widen when uncertain)
  "pause": false,        // if true, skip quoting this market
  "size_mult": 1.0,      // multiply order size (0.5 = half size)
  "confidence": 0.8      // optional, 0-1
}

Pipeline types:
- http: GET or POST to SEEKING_PIPELINE_URL. POST sends context as JSON body.
- file: Read from SEEKING_PIPELINE_FILE (path to JSON). Use for local scripts/analysis.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Cache to avoid hammering external pipelines
_cache: dict[str, tuple[float, "SeekingSignal"]] = {}
DEFAULT_CACHE_TTL = 30


@dataclass
class SeekingSignal:
    """Signal from external data pipeline."""
    skew_bps: float = 0.0      # positive = bullish on Up
    spread_extra_bps: float = 0.0
    pause: bool = False
    size_mult: float = 1.0
    confidence: float = 1.0
    source: str = "none"

    def apply_skew(self, mid: float) -> float:
        """Apply skew to midpoint. skew_bps > 0 raises mid (bullish)."""
        if self.skew_bps == 0:
            return mid
        adj = self.skew_bps / 10000
        return max(0.01, min(0.99, mid + adj))


def _neutral_signal() -> SeekingSignal:
    return SeekingSignal(source="neutral")


def _parse_signal(raw: dict) -> SeekingSignal:
    """Parse API response into SeekingSignal."""
    try:
        return SeekingSignal(
            skew_bps=float(raw.get("skew_bps", 0)),
            spread_extra_bps=float(raw.get("spread_extra_bps", 0)),
            pause=bool(raw.get("pause", False)),
            size_mult=max(0.1, min(2.0, float(raw.get("size_mult", 1.0)))),
            confidence=float(raw.get("confidence", 1.0)),
            source=raw.get("source", "pipeline"),
        )
    except (TypeError, ValueError):
        return _neutral_signal()


def _fetch_http(url: str, context: dict, timeout: float, method: str) -> Optional[dict]:
    """Fetch from HTTP endpoint. POST sends context as JSON."""
    try:
        import urllib.request
        body = json.dumps(context).encode("utf-8") if method.upper() == "POST" else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method.upper(),
            headers={"Content-Type": "application/json"} if body else {},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug("Seeking HTTP failed: %s", e)
        return None


def _fetch_file(path: str, context: dict) -> Optional[dict]:
    """Read signal from local JSON file. File can be static or written by another process."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        with open(p) as f:
            data = json.load(f)
        # If file is keyed by market, return market-specific signal
        slug = context.get("market_slug", "")
        if isinstance(data, dict) and slug and slug in data:
            return data[slug] if isinstance(data[slug], dict) else data
        if isinstance(data, dict) and "skew_bps" in data:
            return data
        if isinstance(data, dict) and "default" in data:
            return data["default"]
        return None
    except Exception as e:
        logger.debug("Seeking file read failed: %s", e)
        return None


def fetch_signal(
    market_slug: str,
    condition_id: str,
    mid: float,
    minutes_to_resolution: float,
    pipeline_url: Optional[str] = None,
    pipeline_file: Optional[str] = None,
    pipeline_method: str = "GET",
    timeout: float = 2.0,
    use_cache: bool = True,
    cache_ttl: int = 30,
) -> SeekingSignal:
    """
    Fetch signal from configured pipeline (URL or file).
    Returns neutral signal if pipeline is disabled or fails.
    """
    pipeline_url = pipeline_url or os.getenv("SEEKING_PIPELINE_URL", "").strip()
    pipeline_file = pipeline_file or os.getenv("SEEKING_PIPELINE_FILE", "").strip()

    if not pipeline_url and not pipeline_file:
        return _neutral_signal()

    ttl = cache_ttl or DEFAULT_CACHE_TTL
    cache_key = f"{condition_id}:{int(time.time()) // ttl}"
    if use_cache and cache_key in _cache:
        ts, sig = _cache[cache_key]
        if time.time() - ts < ttl:
            return sig

    context = {
        "market_slug": market_slug,
        "condition_id": condition_id,
        "mid": mid,
        "minutes_to_resolution": minutes_to_resolution,
        "ts": int(time.time()),
    }

    raw = None
    if pipeline_url:
        raw = _fetch_http(pipeline_url, context, timeout, pipeline_method)
    if raw is None and pipeline_file:
        raw = _fetch_file(pipeline_file, context)

    if raw is None:
        return _neutral_signal()

    sig = _parse_signal(raw)
    if use_cache:
        _cache[cache_key] = (time.time(), sig)
    return sig
