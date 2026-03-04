# Invalid Signature Troubleshooting

The bot gets `errorMsg: 'invalid signature'` when posting orders. Orders never reach Polymarket's book.

## What We've Tried

- ✅ **FUNDER** = Polymarket profile address (0x697...)
- ✅ **FUNDER** = MetaMask address (0x680...)
- ✅ **FUNDER** = empty (EOA default)
- ✅ **SIGNATURE_TYPE** = 0, 1, 2
- ✅ **Nonce** from Web3 (tx count) when deriving API creds
- ✅ **FORCE_DERIVE_API_KEY=true** (derive instead of create)
- ✅ **py-clob-client** 0.34.x
- ✅ **minimal_first_order.py** – exact doc flow, all configs

All combinations still return invalid signature.

## Likely Cause

Polymarket uses different auth flows:
- **EOA (MetaMask)**: Your wallet = signer = maker. FUNDER can be empty.
- **Proxy (Polymarket profile)**: Profile address 0x0cA78 holds funds; MetaMask 0xB1ad controls it. Order maker = 0x0cA78, signer = 0xB1ad.

The py-clob-client may not fully support the proxy flow for API trading, or your account setup may need a different configuration.

## Next Steps

1. **Polymarket Discord**: https://discord.gg/polymarket — Ask in the dev/API channel: "invalid signature when posting orders via py-clob-client with FUNDER set to profile address"

2. **Verify wallet link**: On Polymarket, Settings → Linked Wallets. Confirm 0xB1ad... is linked to profile 0x0cA78.

3. **Fresh account**: Some users fixed this by creating a new Polymarket account.

4. **Polygonscan**: Check if 0xB1ad has any transactions/contract interactions with 0x0cA78 (proxy setup).

## Run Diagnostics

```bash
python diagnose_orders.py
```

Shows the raw API response. Add to PMSC.env to try:
- `FORCE_DERIVE_API_KEY=true`
