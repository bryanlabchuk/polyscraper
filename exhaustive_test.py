#!/usr/bin/env python3
"""Try every config combination. Uses batch post_orders (returns 200 with body, no 400)."""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, PostOrdersArgs, OrderType, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY

from config import BotConfig
from markets import fetch_btc_5m_markets
from client import fee_rate_available

def run():
    key = os.getenv("PRIVATE_KEY", "").strip()
    funder_env = os.getenv("FUNDER", "").strip()
    if not key:
        print("PRIVATE_KEY required")
        return

    cfg = BotConfig()
    mkts = fetch_btc_5m_markets(cfg)
    m = None
    for c in mkts:
        temp = ClobClient(cfg.clob_host, key=key, chain_id=cfg.chain_id)
        if fee_rate_available(temp, c.up_token_id):
            m = c
            break
    if not m:
        print("No market with fee rate")
        return

    wallet = ClobClient(cfg.clob_host, key=key, chain_id=cfg.chain_id).get_address()
    creds = ClobClient(cfg.clob_host, key=key, chain_id=cfg.chain_id).create_or_derive_api_creds()

    configs = [
        (0, None, "sig0 no funder"),
        (0, wallet, "sig0 funder=wallet"),
        (1, funder_env, "sig1 funder=profile"),
        (2, funder_env, "sig2 funder=profile"),
        (1, wallet, "sig1 funder=wallet"),
        (2, wallet, "sig2 funder=wallet"),
    ]

    opts = PartialCreateOrderOptions(tick_size=m.tick_size, neg_risk=True)

    for sig, funder, label in configs:
        if funder is None and sig in (1, 2):
            continue
        try:
            cli = ClobClient(
                cfg.clob_host, key=key, chain_id=cfg.chain_id,
                creds=creds, signature_type=sig, funder=funder,
            )
            order = cli.create_order(
                OrderArgs(token_id=m.up_token_id, price=0.48, size=2.0, side=BUY),
                opts,
            )
            args = PostOrdersArgs(order=order, orderType=OrderType.GTC)
            resp = cli.post_orders([args])
            if isinstance(resp, list) and resp:
                r0 = resp[0]
                err = r0.get("errorMsg", "") if isinstance(r0, dict) else ""
                oid = r0.get("orderID", "") if isinstance(r0, dict) else ""
                if oid:
                    print(f"SUCCESS: {label} -> orderID={oid}")
                    return True
                print(f"FAIL {label}: {err or r0}")
            else:
                print(f"FAIL {label}: {resp}")
        except Exception as e:
            print(f"FAIL {label}: {e}")
    return False

if __name__ == "__main__":
    ok = run()
    if ok:
        print("\n>>> Bot should work. Run: .venv/bin/python main.py")
    else:
        print("\n>>> All configs failed. Run set_allowances.py (needs POL), then retry.")
