# Gemini's Invalid Signature Checklist

Config changes already applied:
- ✅ SIGNATURE_TYPE=1 (Poly-Proxy)
- ✅ FORCE_DERIVE_API_KEY=false (fresh API creds)
- ✅ neg_risk=True in all order creation (already in place)

## Manual Steps to Try

### 1. MetaMask Network
- Open MetaMask → ensure you're on **Polygon Mainnet** (Chain ID 137)
- Wrong network = signature hash mismatch and rejection

### 2. Re-link Wallet to Proxy (Signer Permission)
- Go to [polymarket.com/settings](https://polymarket.com/settings)
- Look for **"Migrate Wallet"** or **"Upgrade Security"**
- Click it to re-link your MetaMask (0x680...) as authorized signer for the Proxy (0x697...)

### 3. USDC.e Allowance
- Open MetaMask → Activity
- Confirm you've approved the Polymarket Exchange contract to spend USDC.e
- No allowance can cause invalid sig on some client versions

### 4. Clear Stale Session (if you've been testing a lot)
- Log out of Polymarket in your browser
- Ensure PMSC.env has no old API_KEY, API_SECRET, API_PASSPHRASE (we don't store these; they're derived)
- Run the bot to generate fresh credentials

### 5. Address Match
- When you click your MetaMask extension, does it show exactly 0x680Ca2CCF78aE6DEa52CE18B47741d9D2AB7DE73?
