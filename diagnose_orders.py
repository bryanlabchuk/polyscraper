#!/usr/bin/env python3
"""
Diagnostic script: post one order and inspect API responses.
Run: python diagnose_orders.py
Shows exactly what Polymarket returns and helps debug why orders don't appear.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from config import BotConfig
from client import create_client, count_open_orders, fee_rate_available, _market_expiration_ts
from markets import fetch_btc_5m_markets, BTCMarket
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
    print(f"Signature type: {config.signature_type}")
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

    # Use GTD with expiration (like main bot) - required for event markets
    buffer_sec = getattr(config, "minutes_before_resolution_to_stop", 2) * 60
    exp_ts = _market_expiration_ts(m, buffer_sec)
    use_gtd = exp_ts is not None and exp_ts > int(datetime.now(timezone.utc).timestamp())
    price = 0.48
    size = max(5.0, float(m.min_size))  # API min is often 5
    # Use API neg_risk for this token (wrong value = invalid signature)
    neg_risk = client.get_neg_risk(m.up_token_id)
    print(f"Market neg_risk (from API): {neg_risk}")
    order_kw = dict(token_id=m.up_token_id, side=BUY, price=price, size=size)
    if use_gtd:
        order_kw["expiration"] = exp_ts
    print(f"Posting 1 order: BUY {size} @ {price} (GTD={use_gtd})...")
    opts = PartialCreateOrderOptions(neg_risk=neg_risk)
    order = client.create_order(OrderArgs(**order_kw), opts)
    args = PostOrdersArgs(order=order, orderType=OrderType.GTD if use_gtd else OrderType.GTC)
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

    # Check for invalid signature (not min-size or other validation)
    if isinstance(resp, list) and resp:
        r0 = resp[0] if isinstance(resp[0], dict) else {}
        err = str(r0.get("errorMsg", ""))
        if err and "invalid signature" in err.lower():
            print()
            print(">>> INVALID SIGNATURE - Try FUNDER=wallet + SIGNATURE_TYPE=0, or FUNDER=profile + TYPE=1/2")
        elif r0.get("orderID") or (err and "lower than the minimum" not in err and "success" in str(r0.get("success", ""))):
            print("Order response:", r0)
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
