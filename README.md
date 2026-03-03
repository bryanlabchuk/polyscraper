# Polymarket BTC 5-Minute Market Maker Bot

A market maker bot for Polymarket's 5-minute Bitcoin Up/Down prediction markets. Posts two-sided quotes (bid/ask) around the midpoint to earn the spread.

**Preset:** Default config targets **$150 USDC.e** — 6 markets × $25 each, larger arb, stricter risk controls.

## How It Works

- **Markets**: Polymarket runs recurring 5-minute markets: "Will Bitcoin go Up or Down in the next 5 minutes?" (resolved via Chainlink BTC/USD)
- **Strategy**: Quote both sides around the current midpoint with a configurable spread
- **Cycle**: Refresh quotes every 30 seconds (configurable); stop quoting 1 minute before resolution

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
| `SIGNATURE_TYPE` | No | `0` = EOA (default), `1` = Magic/email |
| `DRY_RUN` | No | `true` to skip placing real orders |

\* Not required if `DRY_RUN=true`

### 3. Wallet & Approvals

- **Private key**: See [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) for how to get your private key (MetaMask export, etc.).
- **USDC.e on Polygon**: You need USDC.e to trade. Bridge from Ethereum or buy on Polygon.
- **Token Approvals**: EOA/MetaMask users must approve USDC and CTF tokens. See [Polymarket Token Allowances](https://github.com/Polymarket/py-clob-client#important-token-allowances-for-metamaskeoa-users).

### 4. Run

```bash
# Dry run first (no real orders)
DRY_RUN=true python main.py

# Live trading
python main.py
```

## Configuration

Edit `config.py` or set env vars:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `order_size` | 25 | Max exposure per side per market (~$25) |
| `max_position_per_market` | 25 | Max $ per 5-min market |
| `max_total_capital` | 150 | Total capital (6 × $25) |
| `max_active_markets` | 6 | Markets to quote (diversification) |
| `spread_bps` | 38 | Spread in basis points |
| `quote_refresh_seconds` | 0 | Base seconds between cycles (0 = near rate limit) |
| `minutes_before_resolution_to_stop` | 2 | Stop quoting N min before resolution (safer) |
| `arb_enabled` | true | Enable arb: lock-in profit by buying both Up+Down when cheap |
| `arb_bid_price` | 0.48 | Bid on both sides (0.48+0.48=0.96 cost, $1 payout) |
| `arb_size` | 10 | Size per arb bid ($) |
| `arb_taker_min_edge` | 0.012 | Min edge (1.2%) to execute taker arb |
| `volatility_spread_extra_bps` | 25 | Extra bps when mid moves >1.5% in 2 min |
| `min_book_depth` | 25 | Skip market if best bid+ask liquidity < $25 |
| `size_scale_near_resolution` | true | Reduce order size when <4 min to resolution |
| `anti_snipe_jitter` | true | Enable spread/size/timing jitter (harder to snipe) |
| `spread_jitter_pct` | 15 | Max ±% random on spread |
| `size_jitter_pct` | 10 | Max ±% random on order size |
| `cycle_jitter_seconds` | 2 | Add 0–2s random to each cycle interval |

See [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) for the full setup flow.

## Seeking: External Data Pipelines

The bot can connect to external data sources for analysis-driven signals. Set `SEEKING_PIPELINE_URL` (HTTP API) and/or `SEEKING_PIPELINE_FILE` (local JSON). If both are set, HTTP is tried first.

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
