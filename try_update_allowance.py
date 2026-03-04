#!/usr/bin/env python3
"""Call Polymarket update_balance_allowance - refreshes CLOB's view of your allowances."""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

def main():
    key = os.getenv("PRIVATE_KEY", "").strip()
    funder = os.getenv("FUNDER", "").strip()
    sig = int(os.getenv("SIGNATURE_TYPE", "1"))
    if not key:
        print("PRIVATE_KEY required")
        return

    host = "https://clob.polymarket.com"
    cli = ClobClient(host, key=key, chain_id=137, signature_type=sig, funder=funder or None)
    creds = cli.create_or_derive_api_creds()
    cli.set_api_creds(creds)

    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, token_id="", signature_type=-1)
    try:
        r = cli.update_balance_allowance(params)
        print("update_balance_allowance:", r)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
