#!/usr/bin/env python3
"""
Debug script: try neg_risk vs non-neg_risk, batch vs single, and capture full request info.
"""
import os
import json
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, PostOrdersArgs, OrderType, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY
import requests

KEY = os.getenv("PRIVATE_KEY", "").strip()
FUNDER = os.getenv("FUNDER", "").strip()
SIG_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

def get_markets():
    """Get one neg_risk and one non-neg_risk token."""
    resp = requests.get(f"{HOST}/markets", params={"limit": 100}, timeout=10)
    data = resp.json()
    markets = data.get("data", [])
    neg, non_neg = None, None
    for m in markets:
        if not m.get("accepting_orders"):
            continue
        tokens = m.get("tokens", [])
        if not tokens:
            continue
        tid = tokens[0].get("token_id")
        tick = str(m.get("minimum_tick_size", "0.01"))
        nr = m.get("neg_risk", False)
        if nr and neg is None:
            neg = (tid, tick, True)
        elif not nr and non_neg is None:
            non_neg = (tid, tick, False)
        if neg and non_neg:
            break
    return neg, non_neg

def try_order(client, token_id, tick, neg_risk, label, use_batch=True):
    """Try posting order, return (ok, msg)."""
    try:
        opts = PartialCreateOrderOptions(tick_size=tick, neg_risk=neg_risk)
        order = client.create_order(
            OrderArgs(token_id=token_id, price=0.48, size=2.0, side=BUY),
            opts,
        )
        if use_batch:
            args = PostOrdersArgs(order=order, orderType=OrderType.GTC)
            resp = client.post_orders([args])
            if isinstance(resp, list) and resp:
                r0 = resp[0]
                if isinstance(r0, dict):
                    err = r0.get("errorMsg", "")
                    oid = r0.get("orderID", "")
                    if oid:
                        return True, f"SUCCESS orderID={oid}"
                    return False, err or str(r0)
        else:
            resp = client.post_order(order, OrderType.GTC)
            if isinstance(resp, dict) and resp.get("orderID"):
                return True, f"SUCCESS orderID={resp['orderID']}"
            return False, str(resp)
    except Exception as e:
        return False, str(e)

def main():
    if not KEY:
        print("PRIVATE_KEY required")
        return

    neg, non_neg = get_markets()
    print("Markets:", "neg_risk=", neg is not None, "non_neg_risk=", non_neg is not None)
    if not neg:
        print("No neg_risk market - using non_neg only")
    if not non_neg:
        print("No non_neg_risk market - using neg only")

    temp = ClobClient(HOST, key=KEY, chain_id=CHAIN_ID)
    creds = temp.create_or_derive_api_creds()
    client = ClobClient(
        HOST, key=KEY, chain_id=CHAIN_ID,
        creds=creds, signature_type=SIG_TYPE,
        funder=FUNDER if FUNDER else None,
    )
    print(f"Signer: {client.get_address()}, Funder: {FUNDER or '(default)'}, SigType: {SIG_TYPE}\n")

    results = []
    if non_neg:
        tid, tick, nr = non_neg
        ok, msg = try_order(client, tid, tick, nr, "non_neg_risk", use_batch=True)
        results.append(("non_neg_risk (batch)", ok, msg))
        print(f"non_neg_risk batch: {'OK' if ok else 'FAIL'} - {msg}")

    if neg:
        tid, tick, nr = neg
        ok, msg = try_order(client, tid, tick, nr, "neg_risk", use_batch=True)
        results.append(("neg_risk (batch)", ok, msg))
        print(f"neg_risk batch: {'OK' if ok else 'FAIL'} - {msg}")

    if any(r[1] for r in results):
        print("\n>>> At least one config worked!")
    else:
        print("\n>>> All failed - trying single-order endpoint for neg_risk...")
        if neg:
            tid, tick, nr = neg
            ok, msg = try_order(client, tid, tick, nr, "neg_risk", use_batch=False)
            print(f"neg_risk single: {'OK' if ok else 'FAIL'} - {msg}")

if __name__ == "__main__":
    main()
