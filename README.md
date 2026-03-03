# Polymarket BTC 5-Minute Market Maker Bot

A market maker bot for Polymarket's 5-minute Bitcoin Up/Down prediction markets. Posts two-sided quotes (bid/ask) around the midpoint to earn the spread.

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
| `order_size` | 14 | Max exposure per side per market (~$14) |
| `max_position_per_market` | 14 | Max $ per 5-min market |
| `max_total_capital` | 72 | Total capital to work with |
| `max_active_markets` | 5 | Max markets quoted at once |
| `spread_bps` | 40 | Spread in basis points (0.4%; tighter = more fills) |
| `quote_refresh_seconds` | 0 | Base seconds between cycles (0 = near rate limit) |
| `minutes_before_resolution_to_stop` | 2 | Stop quoting N min before resolution (safer) |
| `arb_enabled` | true | Enable arb: lock-in profit by buying both Up+Down when cheap |
| `arb_bid_price` | 0.48 | Bid on both sides (0.48+0.48=0.96 cost, $1 payout) |
| `arb_size` | 5 | Size per arb bid ($) |
| `arb_taker_min_edge` | 0.015 | Min edge (1.5%) to execute taker arb |
| `anti_snipe_jitter` | true | Enable spread/size/timing jitter (harder to snipe) |
| `spread_jitter_pct` | 15 | Max ±% random on spread |
| `size_jitter_pct` | 10 | Max ±% random on order size |
| `cycle_jitter_seconds` | 2 | Add 0–2s random to each cycle interval |

See [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) for the full setup flow.

## Project Structure

```
.
├── main.py           # Entry point, runs the bot loop
├── config.py         # Configuration from env
├── markets.py        # Fetch BTC 5m markets from Gamma API
├── client.py         # Polymarket CLOB client wrapper
├── strategy.py       # Market making logic
├── SETUP_CHECKLIST.md # Step-by-step setup (incl. private key)
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

## Polymarket MCP

This project includes a Cursor rule (`.cursor/rules/polymarket-mcp.mdc`) that prompts the AI to use the **Polymarket MCP** when working on Polymarket code. The MCP provides `SearchPolymarketDocumentation` to query docs.polymarket.com for current API references and best practices.

Ensure the Polymarket MCP is enabled in Cursor (Settings → MCP → Polymarket Documentation).

## References

- [Polymarket CLOB API](https://docs.polymarket.com/developers/CLOB)
- [Market Maker Setup](https://docs.polymarket.com/developers/market-makers/setup)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
