#!/usr/bin/env python3
"""
Diagnostic script: post one order and inspect API responses.
Run: python diagnose_orders.py
Shows exactly what Polymarket returns and helps debug why orders don't appear.
"""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from config import BotConfig
from client import create_client, count_open_orders, fee_rate_available
from markets import fetch_btc_5m_markets
from py_clob_client.clob_types import OrderArgs, PostOrdersArgs, OrderType, PartialCreateOrderOptions, OpenOrderParams
from py_clob_client.order_builder.constants import BUY

def main():
    config = BotConfig()
    if config.dry_run:
        print("Set DRY_RUN=false to test real orders")
        return
    client = create_client(config, read_only=False)
    if not client:
        print("Failed to create client")
        return
    addr = client.get_address()
    print(f"Wallet: {addr}")
    print(f"Funder in config: {repr(config.funder)}")
    print()

    markets = fetch_btc_5m_markets(config)
    if not markets:
        print("No markets found")
        return
    m = None
    for candidate in markets:
        if fee_rate_available(client, candidate.up_token_id):
            m = candidate
            break
    if not m:
        print("No market with fee rate found (try again - markets rotate)")
        return
    print(f"Market: {m.event_slug}")
    print(f"Up token: {m.up_token_id[:20]}...")
    print()

    # Post one small bid
    size = 2.0  # Small test
    price = 0.48
    print(f"Posting 1 order: BUY {size} @ {price} on Up token...")
    opts = PartialCreateOrderOptions(neg_risk=True)
    order = client.create_order(OrderArgs(
        token_id=m.up_token_id,
        side=BUY,
        price=price,
        size=size,
    ), opts)
    args = PostOrdersArgs(order=order, orderType=OrderType.GTC)
    try:
        resp = client.post_orders([args])
        print(f"post_orders response type: {type(resp)}")
        print(f"post_orders response: {resp}")
        if isinstance(resp, list):
            for i, r in enumerate(resp):
                print(f"  [{i}]: {r}")
    except Exception as e:
        print(f"post_orders raised: {e}")
        import traceback
        traceback.print_exc()
        return

    # Check for invalid signature
    if isinstance(resp, list) and resp:
        r0 = resp[0] if isinstance(resp[0], dict) else {}
        if r0.get("errorMsg") and "invalid" in str(r0.get("errorMsg", "")).lower():
            print()
            print(">>> INVALID SIGNATURE - Set FUNDER in PMSC.env <<<")
            print("FUNDER must be your Polymarket PROFILE address (top-right of polymarket.com),")
            print("NOT your MetaMask address. Find it: go to polymarket.com, click your profile,")
            print("and check the URL (e.g. polymarket.com/profile/0x1234...).")
            print("If you use MetaMask with Polymarket proxy, try SIGNATURE_TYPE=2")
    print()

    # Fetch open orders
    print("Fetching open orders...")
    try:
        orders = client.get_orders(OpenOrderParams())
        print(f"get_orders returned: {len(orders) if isinstance(orders, list) else 'N/A'} orders")
        if isinstance(orders, list) and orders:
            print("First order:", orders[0])
        else:
            print("Raw:", orders)
    except Exception as e:
        print(f"get_orders raised: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
