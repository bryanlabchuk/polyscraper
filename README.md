# Polymarket BTC 5-Minute Market Maker Bot

A market maker bot for Polymarket's 5-minute Bitcoin Up/Down prediction markets. Posts two-sided quotes (bid/ask) around the midpoint to earn the spread. Focused on **spread capture** (2026 meta): no arb, no resolution plays—just quoting to make the spread.

## How It Works

- **Markets**: Polymarket runs recurring 5-minute markets: "Will Bitcoin go Up or Down in the next 5 minutes?" (resolved via Chainlink BTC/USD)
- **Strategy**: Quote both sides around the current midpoint with a configurable spread; capture spread when both sides fill
- **Cycle**: Refresh quotes every 15+ seconds (configurable); stop quoting before resolution

## Requirements

- **Python 3.9.10+** (py-clob-client requires 3.9.10)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Copy `.env.example` to `PMSC.env` and configure:

```bash
cp .env.example PMSC.env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `PRIVATE_KEY` | Yes* | Your wallet's private key (EOA) |
| `FUNDER` | No | For Magic/email wallets; your funded address |
| `SIGNATURE_TYPE` | No | `0` = EOA (default), `1` = Magic/email, `2` = delegated (keep if auth works) |
| `DRY_RUN` | No | `true` to skip placing real orders |

\* Not required if `DRY_RUN=true`

### 3. Wallet & Approvals

- **Private key**: See [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) for how to get your private key (MetaMask export, etc.).
- **FUNDER (critical)**: Set to your **Polymarket profile address** (top-right of polymarket.com), NOT your MetaMask address. Without this, orders fail with "invalid signature". Find it: click your profile → URL shows `polymarket.com/profile/0x...` — use that `0x...` as `FUNDER` in PMSC.env.
- **USDC.e on Polygon**: You need USDC.e to trade. Bridge from Ethereum or buy on Polygon.
- **Token Approvals**: EOA/MetaMask users must approve USDC and CTF tokens. See [Polymarket Token Allowances](https://github.com/Polymarket/py-clob-client#important-token-allowances-for-metamaskeoa-users).
- **If you get "invalid signature"**: (1) Use **FUNDER** = your **wallet** address (same as signer) and **SIGNATURE_TYPE=0** (EOA), or **SIGNATURE_TYPE=2** if you use delegated auth. (2) The bot sets **neg_risk** from the API per token (`get_neg_risk(token_id)`) for all btc-updown orders; keep this to avoid regression. Run `python verify_setup.py` and `python set_allowances.py` if needed. See [MAKE_IT_WORK.md](MAKE_IT_WORK.md).
- **Rate limiting (429 / Cloudflare 1015)**: Polymarket may temporarily block your IP. The bot will retry with backoff. To use a **different IP**: (1) **Mobile hotspot** — turn on hotspot on your phone, connect your computer to it, then run the bot; (2) **VPN** — connect to any VPN server and run the bot; (3) **Another network** — run from home, office, or a different Wi‑Fi. Or wait 15–30 minutes and try again from the same IP.
- **"No route to host" / No active markets**: Your network can't reach `gamma-api.polymarket.com` (market discovery). Some VPNs or firewalls block it. Try **without VPN**, or switch VPN server; if on VPN to fix 429, try disconnecting once CLOB works and use your normal connection for gamma.
- **POL for gas**: Cancels and other on-chain actions use Polygon gas. Keep **$5–$10 worth of POL** on your **signer address** (the wallet in `FUNDER` / the one that holds your private key) on Polygon so gas never blocks order cancellation. Check balance: [polygonscan.com/address/YOUR_ADDRESS](https://polygonscan.com).

**Suggested run plan:** Run with `MAX_TOTAL_CAPITAL=150` for **24 hours**. If logs show "Matched" or "Filled" with no persistent errors, scale by raising `MAX_TOTAL_CAPITAL` and `ORDER_SIZE` (e.g. to $1,000 total) in `PMSC.env` and restart the bot.

### 4. Run

**Fastest (recommended):** WebSocket-driven — reacts to book/price changes in real time (no polling delay):

```bash
.venv/bin/python main_ws.py
```

**Polling:** Fixed 5s cycle (good if you prefer simpler REST-only):

```bash
.venv/bin/python main.py
```

```bash
# Dry run first (no real orders)
DRY_RUN=true .venv/bin/python main.py
```

## Configuration

Edit `config.py` or set env vars:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `order_size` | 50 | Size per side per market ($) |
| `max_position_per_market` | 50 | Max $ exposure per 5-min market |
| `max_total_capital` | 150 | Total capital |
| `max_active_markets` | 2 | Markets to quote at once |
| `join_book` | true | Quote at best bid/ask (more fills) |
| `improve_by_one_tick` | true | When joining: bid+1tick, ask-1tick for queue priority |
| `quote_refresh_seconds` | 5 | REST cycle (use main_ws.py for event-driven) |
| `min_quote_interval_seconds` | 10 | Min time orders stay on book (10s for 2026 Loyalty Multiplier) |
| `spread_bps` | 50 | Total spread in bps (50 = 0.5¢ = Mid±0.0025 for rebate zone) |
| `MIN_MIDPOINT_DRIFT` | 0.002 | Only cancel/replace if mid moves &gt; 0.2¢ (reduces rate limits) |
| `HIGH_REWARD_MID_MIN` / `HIGH_REWARD_MID_MAX` | 0.45 / 0.55 | Only quote markets with mid in this range (max rebate near 50%) |
| `join_book` | true | Quote at touch; set `false` for strict 0.5¢ spread around mid |
| `cancel_post_delay_min` / `cancel_post_delay_max` | 0 | Delay between cancel and post (0 for speed) |
| `cycle_jitter_seconds` | 0 | Fixed cycle (no random wait) |
| `minutes_before_resolution_to_stop` | 1 | Stay in until 1 min to resolution |
| `minutes_before_resolution_to_stop` | 2 | Stop quoting N min before resolution |
| `volatility_spread_extra_bps` | 25 | Extra spread when mid moves a lot |
| `min_book_depth` | 25 | Skip market if book liquidity < $25 |
| `size_scale_near_resolution` | true | Reduce size when close to resolution |
| `anti_snipe_jitter` | true | Spread/size/timing jitter |
| `spread_jitter_pct` | 15 | Max ±% on spread |
| `size_jitter_pct` | 10 | Max ±% on order size |
| `cycle_jitter_seconds` | 2 | Random 0–2s added to cycle |

See [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) for the full setup flow.

## Optional: External Signals (Seeking)

Off by default. To use an external data pipeline for signals, set `SEEKING_ENABLED=true` and `SEEKING_PIPELINE_URL` and/or `SEEKING_PIPELINE_FILE`.

**Signal format (JSON):**
```json
{
  "skew_bps": 10,
  "spread_extra_bps": 5,
  "pause": false,
  "size_mult": 1.0,
  "confidence": 0.8
}
```

- `skew_bps`: positive = bullish (skew Up), negative = bearish
- `spread_extra_bps`: add to spread when uncertain
- `pause`: if true, skip quoting this market
- `size_mult`: multiply order size (0.5–2.0)

**HTTP API**: POST `market_slug`, `condition_id`, `mid`, `minutes_to_resolution` as JSON body.

**File**: Write a `signals.json` that your analysis pipeline updates. Use per-market keys or a `default` object.

## Adaptive Algorithms

- **Resolution spread widening**: Spread widens 2x in last minute, 2.5x in last 15 sec to reduce adverse selection.
- **Granular size scaling**: 5/4/3/2/1 min thresholds (100% → 95% → 85% → 70% → 50% → 25%).
- **Momentum skew**: Skews quotes toward recent price direction (±15 bps).
- **Volatility scaling**: Extra spread scales continuously with mid range (0.5–2%).
- **One-sided arb exit**: With 5–60 sec left, sell a losing one-sided position at best bid to cut losses.
- **Arb completion**: With 5–45 sec left, buy the cheap other side (<0.06) to complete a partial arb.

## Fill Logging

Trades are appended to `fills_log.csv` for analysis. Columns: `trade_id`, `timestamp`, `side`, `price`, `size`, `market_slug`, `condition_id`. Use this to understand which side you're getting filled on and tune strategy.

## Project Structure

```
.
├── main.py           # Entry point, runs the bot loop
├── config.py         # Configuration from env
├── markets.py        # Fetch BTC 5m markets from Gamma API
├── client.py         # Polymarket CLOB client wrapper
├── strategy.py       # Market making logic
├── seeking.py        # External data pipeline connector
├── adaptive.py       # Resolution spread/size, momentum, volatility
├── positions.py      # Estimate positions from trades
├── resolution_actions.py  # One-sided arb exit, arb completion
├── fill_logger.py    # Log trades to fills_log.csv
├── fills_log.csv     # Trade log (gitignored)
├── signals.json      # Optional: file-based seeking (gitignored)
├── SETUP_CHECKLIST.md
├── requirements.txt
└── README.md
```

## Dashboard

Run the web dashboard to monitor bot performance over time:

```bash
python dashboard.py
```

Open http://localhost:3099 for balance, trade count, volume, and a balance-over-time chart. Refreshes every 60s.

## Viewing Transactions & Activity

- **Polygonscan**: After the bot starts, it logs your wallet address and a Polygonscan link. Use it to see all on-chain activity (USDC transfers, CTF mints/redeems, etc.):  
  `https://polygonscan.com/address/YOUR_ADDRESS`

- **Activity script**: Run `python show_activity.py` to fetch recent trades from the CLOB API and print wallet links, Polygonscan URL, and a summary of recent fills.

- **Polymarket UI**: Connect the same wallet at [polymarket.com/portfolio](https://polymarket.com/portfolio) to see positions and activity in their UI.

## Risk & Fees

- **Crypto markets have taker fees** (1% as of 2026). Makers may have rebates; check [Polymarket Fees](https://docs.polymarket.com/trading/fees).
- **5-minute markets are volatile**. Use appropriate position limits.
- **Start with DRY_RUN** and small sizes when going live.

## Speed Optimizations (Institutional-Level)

- **Batch order book fetch**: One `get_order_books` API call for all markets (up + down tokens) instead of 2N per-cycle calls.
- **Arb check from cache**: Taker arb uses cached books—no extra API calls.
- **Reduced delays**: Cancel-post 0–30 ms; market stagger 10–60 ms.
- **Fast cycle**: `quote_refresh_seconds=0` runs near rate limit.

## Polymarket MCP

This project includes a Cursor rule (`.cursor/rules/polymarket-mcp.mdc`) that prompts the AI to use the **Polymarket MCP** when working on Polymarket code. The MCP provides `SearchPolymarketDocumentation` to query docs.polymarket.com for current API references and best practices.

Ensure the Polymarket MCP is enabled in Cursor (Settings → MCP → Polymarket Documentation).

## References

- [Polymarket CLOB API](https://docs.polymarket.com/developers/CLOB)
- [Market Maker Setup](https://docs.polymarket.com/developers/market-makers/setup)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
