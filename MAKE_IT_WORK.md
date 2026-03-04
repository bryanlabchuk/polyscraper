# Make the Bot Work – Step by Step

Your balance/allowance check shows **allowances are 0** for the exchange contracts. That can cause "invalid signature" (Polymarket sometimes returns this when the real issue is approvals).

## Critical: Set Allowances

Your signer (0x680...) has ~150 USDC but **0 allowances**. The exchange contracts cannot spend your tokens.

**Run this (requires POL for gas):**
```bash
.venv/bin/python set_allowances.py
```

- Uses your `PRIVATE_KEY` from PMSC.env
- Signs from your MetaMask address
- Approves USDC.e and CTF tokens for the Polymarket exchange contracts
- Needs ~0.01 POL for gas

If RPC fails, add to PMSC.env:
```
POLYGON_RPC=https://polygon-rpc.com
```

Or try another RPC: https://chainlist.org/chain/137

## Then Run

```bash
# Test one order
.venv/bin/python minimal_first_order.py

# Or run everything
./run_all.sh
```

## If It Still Fails

1. **Account match**: MetaMask Account 3 address must match 0x680Ca2CCF78aE6DEa52CE18B47741d9D2AB7DE73 (from PRIVATE_KEY)
2. **Polymarket settings**: polymarket.com/settings → Migrate Wallet or Upgrade Security
3. **Place a trade in browser** first (triggers proxy approvals if using profile 0x697)
4. **Polymarket Discord**: discord.gg/polymarket #dev
