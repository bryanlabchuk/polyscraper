#!/usr/bin/env python3
"""
Test: place one small TAKER buy (hit the best ask) to verify we can execute a trade.
Spends ~$1–3 (min size often 5 shares × ask price). Run: .venv/bin/python test_taker_buy.py
"""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from config import BotConfig
from client import (
    create_client,
    fee_rate_available,
    get_best_ask,
    get_tick_size,
    round_to_tick,
    _market_expiration_ts,
)
from markets import fetch_btc_5m_markets
from py_clob_client.clob_types import OrderArgs, PostOrdersArgs, OrderType, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY

def main():
    config = BotConfig()
    if config.dry_run:
        print("Set DRY_RUN=false to test real purchase")
        return
    client = create_client(config, read_only=False)
    if not client:
        print("Failed to create client")
        return
    markets = fetch_btc_5m_markets(config)
    m = next((c for c in markets if fee_rate_available(client, c.up_token_id)), None)
    if not m:
        print("No market with fee rate")
        return

    best_ask = get_best_ask(client, m.up_token_id)
    if best_ask is None or best_ask <= 0:
        print("No best ask on this market")
        return

    tick_s = get_tick_size(client, m.up_token_id) or m.tick_size
    price = round_to_tick(best_ask, tick_s)
    # Min size (e.g. 5); ~$1 would be 1/price shares - use at least min_size
    size = max(float(m.min_size), 5.0)
    notional = size * price
    print(f"Market: {m.event_slug}")
    print(f"Best ask: {best_ask} -> rounded {price}")
    print(f"TAKER BUY: {size} shares @ {price} (~${notional:.2f} notional)")
    print("Submitting order (should fill immediately as taker)...")

    neg_risk = client.get_neg_risk(m.up_token_id)
    opts = PartialCreateOrderOptions(neg_risk=neg_risk)
    buffer_sec = getattr(config, "minutes_before_resolution_to_stop", 2) * 60
    exp_ts = _market_expiration_ts(m, buffer_sec)
    from datetime import datetime, timezone
    use_gtd = exp_ts is not None and exp_ts > int(datetime.now(timezone.utc).timestamp())
    order_kw = dict(token_id=m.up_token_id, side=BUY, price=price, size=size)
    if use_gtd:
        order_kw["expiration"] = exp_ts

    order = client.create_order(OrderArgs(**order_kw), opts)
    resp = client.post_orders([PostOrdersArgs(order=order, orderType=OrderType.GTD if use_gtd else OrderType.GTC)])
    if isinstance(resp, list) and resp:
        r = resp[0]
        err = r.get("errorMsg", "")
        oid = r.get("orderID", "")
        status = r.get("status", "")
        if err:
            print(f"Error: {err}")
            return
        print(f"Order ID: {oid}")
        print(f"Status: {status}")
        if status == "matched":
            print("SUCCESS: Order matched immediately (taker fill). Bot can execute trades.")
        else:
            print("Order accepted (live on book). If not matched, book may have moved.")
    else:
        print("Unexpected response:", resp)

if __name__ == "__main__":
    main()
