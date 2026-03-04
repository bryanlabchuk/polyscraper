#!/usr/bin/env python3
"""
Verify setup: print addresses, checksums, and test balance/allowance endpoints.
"""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from py_clob_client.client import ClobClient
from eth_account import Account

KEY = os.getenv("PRIVATE_KEY", "").strip()
FUNDER = os.getenv("FUNDER", "").strip()

def main():
    if not KEY:
        print("PRIVATE_KEY not set")
        return

    acc = Account.from_key(KEY)
    signer_addr = acc.address
    print("From PRIVATE_KEY:")
    print(f"  Signer address: {signer_addr}")
    print(f"  Checksummed:    {signer_addr}")
    print()
    print("From PMSC.env FUNDER:")
    print(f"  Raw: {repr(FUNDER)}")
    print(f"  Len: {len(FUNDER)}, strip: {len(FUNDER.strip())}")
    if FUNDER:
        from eth_utils import to_checksum_address
        try:
            cs = to_checksum_address(FUNDER.strip())
            print(f"  Checksummed: {cs}")
        except Exception as e:
            print(f"  Checksum error: {e}")
    print()

    host = "https://clob.polymarket.com"
    client = ClobClient(host, key=KEY, chain_id=137)
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)

    # Try balance/allowance - uses L2 auth, doesn't need order sig
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, token_id="")
        bal = client.get_balance_allowance(params)
        print("Balance/allowance (L2):", bal)
        if isinstance(bal, dict):
            allowances = bal.get("allowances", {})
            if allowances and all(v == "0" for v in allowances.values()):
                print("\n!!! ALLOWANCES ARE 0 - Run: python set_allowances.py")
                print("    (Requires POL for gas. Approves USDC + CTF for exchange contracts.)")
    except Exception as e:
        print("Balance/allowance error:", e)

if __name__ == "__main__":
    main()
