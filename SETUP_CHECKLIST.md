# Polymarket BTC 5m Market Maker — Setup Checklist

Use this checklist to get the bot running with **$100 total capital** and **$20 max per 5‑minute market**.

---

## 1. Get Your Private Key

The bot needs an **EOA (Externally Owned Account) wallet** where you control the private key. Polymarket’s email/Magic login does **not** expose a private key.

### Option A: MetaMask (recommended)

1. Install MetaMask: [metamask.io](https://metamask.io)
2. Create a new wallet (or use an existing one)
3. Export the private key:
   - Click the three dots → **Account details**
   - Click **Show private key**
   - Enter your password and copy the key (starts with `0x`)
4. Add Polygon:
   - Visit [chainlist.org](https://chainlist.org)
   - Search “Polygon” and add **Polygon Mainnet** (Chain ID 137)

### Option B: Other wallet (Rabby, Rainbow, etc.)

Use your wallet’s “Export private key” or “Reveal secret key” flow and copy the hex string (usually starting with `0x`).

---

## 2. Fund the Wallet

- **Network:** Polygon
- **Asset:** USDC.e (bridged USDC)
- **Amount:** At least $100

Ways to get USDC.e on Polygon:

- Bridge from Ethereum (e.g. [wallet.polygon.technology](https://wallet.polygon.technology))
- Buy on a CEX and withdraw to Polygon
- Swap for USDC on a Polygon DEX

---

## 3. Set Token Approvals (MetaMask / EOA)

Polymarket needs approval to move USDC and conditional tokens. For EOAs, you must set this manually:

1. Visit Polymarket and connect the same MetaMask wallet
2. Place a small test trade — this usually triggers the approval prompts
3. Or use the [Polymarket allowance script](https://gist.github.com/poly-rodr/44313920481de58d5a3f6d1f8226bd5e) if you prefer doing it programmatically

Without approvals, the bot will fail when placing orders.

---

## 4. Configure the Bot

```bash
cp .env.example PMSC.env
```

Edit `PMSC.env`:

```bash
PRIVATE_KEY=0xYOUR_KEY_HERE
DRY_RUN=true
```

Optional (already set in code for $100 / $20 per market):

```bash
ORDER_SIZE=20
MAX_POSITION_PER_MARKET=20
MAX_TOTAL_CAPITAL=100
MAX_ACTIVE_MARKETS=5
```

---

## 5. Install and Run

```bash
pip install -r requirements.txt
```

**Dry run first (no real orders):**

```bash
DRY_RUN=true python main.py
```

You should see log lines like:

- `Found X active BTC 5m markets`
- `[DRY RUN] Would post: bid=X ask=Y...`

**Live trading:**

```bash
DRY_RUN=false python main.py
```

Or simply remove `DRY_RUN` or set `DRY_RUN=false`.

---

## Summary: Limits With Default Config

| Setting | Value |
|---------|-------|
| Total capital | $100 |
| Max per 5‑min market | $20 |
| Max markets quoted | 5 |
| Order size per side | $20 |
| Spread | 0.5% |
| Quote refresh | Every 30 seconds |

---

## Security

- Do **not** commit `PMSC.env` or share your private key
- `PMSC.env` is in `.gitignore`
- Use a dedicated wallet for the bot, not your main account
- Consider rotating the key if it’s ever exposed
