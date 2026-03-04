#!/usr/bin/env python3
"""
Bot performance dashboard - web UI on localhost:3099.

Shows trades, balance over time, and basic stats. Run alongside the bot:
  python dashboard.py

Open http://localhost:3099 in a browser.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template_string

# Suppress Flask and CLI noise
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)
DATA_FILE = Path(__file__).parent / "dashboard_data.json"
POLL_INTERVAL = 30  # seconds between API polls
PORT = 3099

# In-memory cache, updated by background thread
_stats = {
    "address": "",
    "balance_usdc": None,
    "trade_count": 0,
    "total_volume_usd": 0.0,
    "snapshots": [],
    "recent_trades": [],
    "last_updated": None,
    "error": None,
}


def _load_snapshots():
    """Load persisted snapshots from disk."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
                return data.get("snapshots", [])[-500:]  # Keep last 500
        except Exception:
            pass
    return []


def _save_snapshots(snapshots):
    """Persist snapshots to disk."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({"snapshots": snapshots[-500:]}, f, indent=0)
    except Exception:
        pass


def _fetch_data():
    """Fetch trades and balance from Polymarket API."""
    try:
        from config import BotConfig
        from client import create_client
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        config = BotConfig()
        if not config.private_key:
            return {"error": "No PRIVATE_KEY in PMSC.env"}

        client = create_client(config, read_only=False)
        if not client:
            return {"error": "Failed to create API client"}

        address = client.get_address() or "unknown"

        # Balance (CLOB balance/allowance for collateral)
        balance = None
        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=config.signature_type,
            )
            bal_resp = client.get_balance_allowance(params)
            if isinstance(bal_resp, dict):
                raw = float(
                    bal_resp.get("balance") or bal_resp.get("currentBalance") or 0
                )
            else:
                raw = float(getattr(bal_resp, "balance", 0) or 0)
            # USDC has 6 decimals
            balance = raw / 1e6 if raw > 1e4 else raw
        except Exception:
            pass

        # Trades
        trades = []
        try:
            trades = client.get_trades(params=None) or []
        except Exception:
            pass

        # Compute stats from trades
        trade_count = len(trades)
        total_vol = 0.0
        for t in trades:
            p = float(t.get("price") or 0)
            s = float(t.get("size") or 0)
            total_vol += p * s

        recent = []
        for t in trades[:30]:
            ts = t.get("timestamp")
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "?"
            recent.append({
                "time": dt,
                "side": t.get("side", "?"),
                "price": float(t.get("price") or 0),
                "size": float(t.get("size") or 0),
                "slug": (t.get("eventSlug") or t.get("slug") or "?")[:35],
            })

        return {
            "address": address,
            "balance_usdc": balance,
            "trade_count": trade_count,
            "total_volume_usd": round(total_vol, 2),
            "recent_trades": recent,
            "snapshot": {
                "ts": int(time.time()),
                "balance": balance,
                "trade_count": trade_count,
                "volume": round(total_vol, 2),
            },
        }
    except Exception as e:
        return {"error": str(e)}


def _poll_loop():
    """Background thread: poll API and update stats."""
    snapshots = _load_snapshots()
    while True:
        data = _fetch_data()
        if "error" in data:
            _stats["error"] = data["error"]
            _stats["last_updated"] = datetime.now(timezone.utc).isoformat()
        else:
            _stats["error"] = None
            _stats["address"] = data["address"]
            _stats["balance_usdc"] = data["balance_usdc"]
            _stats["trade_count"] = data["trade_count"]
            _stats["total_volume_usd"] = data["total_volume_usd"]
            _stats["recent_trades"] = data["recent_trades"]
            _stats["last_updated"] = datetime.now(timezone.utc).isoformat()

            snap = data.get("snapshot")
            if snap and (not snapshots or snapshots[-1]["trade_count"] != snap["trade_count"] or
                        (snap["balance"] is not None and
                         (not snapshots or snapshots[-1].get("balance") != snap["balance"]))):
                snapshots.append(snap)
                _save_snapshots(snapshots)

        _stats["snapshots"] = snapshots[-100:]  # Last 100 for chart
        time.sleep(POLL_INTERVAL)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>PMSC Bot Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
      background: #0d1117;
      color: #e6edf3;
      margin: 0;
      padding: 24px;
      max-width: 900px;
      margin-left: auto;
      margin-right: auto;
    }
    h1 { font-size: 1.25rem; color: #58a6ff; margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 16px;
    }
    .card-label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; margin-bottom: 4px; }
    .card-value { font-size: 1.5rem; font-weight: 600; }
    .card-value.positive { color: #3fb950; }
    .card-value.negative { color: #f85149; }
    .chart-wrap { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 24px; height: 220px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #30363d; }
    th { color: 8b949e; font-weight: 500; }
    .meta { font-size: 0.75rem; color: #8b949e; margin-top: 24px; }
    .err { color: #f85149; background: #2d1f1f; padding: 12px; border-radius: 8px; margin-bottom: 16px; }
    a { color: #58a6ff; }
  </style>
</head>
<body>
  <h1>PMSC Market Maker – Dashboard</h1>

  {% if stats.error %}
  <div class="err">{{ stats.error }}</div>
  {% endif %}

  <div class="grid">
    <div class="card">
      <div class="card-label">Balance (USDC)</div>
      <div class="card-value">{{ stats.balance_usdc if stats.balance_usdc is not none else "—" }}{% if stats.balance_usdc is not none %} ${% endif %}</div>
    </div>
    <div class="card">
      <div class="card-label">Total Trades</div>
      <div class="card-value">{{ stats.trade_count }}</div>
    </div>
    <div class="card">
      <div class="card-label">Volume (USD)</div>
      <div class="card-value">{{ "%.1f"|format(stats.total_volume_usd) }} $</div>
    </div>
    <div class="card">
      <div class="card-label">Last Updated</div>
      <div class="card-value" style="font-size: 0.9rem;">{{ (stats.last_updated or "—")[:19] }}</div>
    </div>
  </div>

  {% if stats.snapshots %}
  <div class="chart-wrap">
    <canvas id="chart"></canvas>
  </div>
  {% endif %}

  <div class="card" style="margin-bottom: 8px;">
    <div class="card-label">Wallet</div>
    <a href="https://polygonscan.com/address/{{ stats.address }}" target="_blank">{{ stats.address }}</a>
  </div>

  <div class="card">
    <div class="card-label">Recent Trades</div>
    {% if stats.recent_trades %}
    <table>
      <thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Size</th><th>Market</th></tr></thead>
      <tbody>
      {% for t in stats.recent_trades %}
      <tr>
        <td>{{ t.time }}</td>
        <td>{{ t.side }}</td>
        <td>{{ "%.3f"|format(t.price) }}</td>
        <td>{{ "%.1f"|format(t.size) }}</td>
        <td>{{ t.slug }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="color: #8b949e;">No trades yet. Dashboard refreshes every 60s.</p>
    {% endif %}
  </div>

  <div class="meta">Data from Polymarket CLOB API. Auto-refresh: 30s.</div>

  {% if stats.snapshots %}
  <script>
    const snapshots = {{ stats.snapshots | tojson }};
    const ctx = document.getElementById('chart').getContext('2d');
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: snapshots.map(s => new Date(s.ts*1000).toLocaleTimeString()),
        datasets: [
          {
            label: 'Balance (USDC)',
            data: snapshots.map(s => s.balance),
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88,166,255,0.1)',
            fill: true,
            tension: 0.2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { grid: { color: '#30363d' }, ticks: { color: '#8b949e' } },
          x: { grid: { color: '#30363d' }, ticks: { color: '#8b949e', maxTicksLimit: 8 } }
        }
      }
    });
  </script>
  {% endif %}
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, stats=_stats)


def main():
    # Fetch once immediately
    data = _fetch_data()
    if "error" in data:
        _stats["error"] = data["error"]
    else:
        _stats.update({
            "address": data.get("address", ""),
            "balance_usdc": data.get("balance_usdc"),
            "trade_count": data.get("trade_count", 0),
            "total_volume_usd": data.get("total_volume_usd", 0),
            "recent_trades": data.get("recent_trades", []),
        })
        snap = data.get("snapshot")
        if snap:
            snapshots = _load_snapshots()
            snapshots.append(snap)
            _save_snapshots(snapshots)
            _stats["snapshots"] = snapshots[-100:]
    _stats["last_updated"] = datetime.now(timezone.utc).isoformat()

    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

    print(f"Dashboard: http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
