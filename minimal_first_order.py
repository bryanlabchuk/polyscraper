#!/usr/bin/env python3
"""
Minimal first-order test - exactly matching Polymarket docs.
Tests different signature_type + funder combinations to find one that works.
Run: python minimal_first_order.py
"""
import os
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY

from config import BotConfig
from markets import fetch_btc_5m_markets
from client import fee_rate_available


def get_active_token(client):
    """Get one active BTC 5m token with fee rate (orderbook exists)."""
    cfg = BotConfig()
    markets = fetch_btc_5m_markets(cfg)
    for m in markets:
        if fee_rate_available(client, m.up_token_id):
            return m.up_token_id, m.tick_size, True  # BTC 5m are neg_risk
    return None, "0.01", True


def try_config(host, chain_id, key, sig_type, funder, token_id, tick_size, neg_risk):
    """Try one config and return (success, message)."""
    try:
        temp = ClobClient(host, key=key, chain_id=chain_id)
        api_creds = temp.create_or_derive_api_creds()
        if not api_creds:
            return False, "Failed to derive API creds"

        client = ClobClient(
            host,
            key=key,
            chain_id=chain_id,
            creds=api_creds,
            signature_type=sig_type,
            funder=funder if funder else None,
        )
        wallet = client.get_address()
        print(f"  Wallet: {wallet}, Funder: {funder or '(default)'}")

        opts = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)
        resp = client.create_and_post_order(
            OrderArgs(token_id=token_id, price=0.48, size=2.0, side=BUY),
            opts,
        )
        if isinstance(resp, dict) and resp.get("orderID"):
            return True, f"SUCCESS! Order ID: {resp.get('orderID')}"
        if isinstance(resp, list) and resp:
            r0 = resp[0] if isinstance(resp[0], dict) else resp[0]
            err = r0.get("errorMsg", r0) if isinstance(r0, dict) else str(r0)
            return False, err
        return False, str(resp)
    except Exception as e:
        return False, str(e)


def main():
    key = os.getenv("PRIVATE_KEY", "").strip()
    funder_env = os.getenv("FUNDER", "").strip()
    if not key:
        print("Set PRIVATE_KEY in PMSC.env")
        return

    host = "https://clob.polymarket.com"
    chain_id = 137

    print("Fetching active market...")
    temp = ClobClient(host, key=key, chain_id=chain_id)
    token_id, tick_size, neg_risk = get_active_token(temp)
    if not token_id:
        print("No active BTC 5m market with orderbook found (try again)")
        return
    print(f"Token: {token_id[:30]}..., tick={tick_size}, neg_risk={neg_risk}\n")

    # Get wallet address for EOA funder
    temp = ClobClient(host, key=key, chain_id=chain_id)
    wallet_addr = temp.get_address()
    print(f"Your wallet: {wallet_addr}")
    print(f"FUNDER in PMSC.env: {funder_env or '(empty)'}\n")

    configs = [
        ("EOA, funder=wallet (docs)", 0, wallet_addr),
        ("EOA, funder=empty", 0, None),
        ("POLY_PROXY (1), funder=profile", 1, funder_env or "(need FUNDER in PMSC.env)"),
        ("GNOSIS_SAFE (2), funder=profile", 2, funder_env or "(need FUNDER in PMSC.env)"),
    ]

    for name, sig_type, funder in configs:
        f = funder
        if sig_type in (1, 2):
            if not funder_env:
                print(f"Skipping {name}: set FUNDER=profile_address in PMSC.env first")
                continue
            f = funder_env
        if sig_type == 0 and not f:
            f = None
        print(f"Trying: {name} (sig={sig_type})")
        ok, msg = try_config(host, chain_id, key, sig_type, f, token_id, tick_size, neg_risk)
        status = "✓" if ok else "✗"
        print(f"  {status} {msg}\n")
        if ok:
            print(">>> This config works! Update PMSC.env accordingly. <<<")
            return

    print("No config worked. Try:")
    print("  1. FUNDER = profile address from polymarket.com/profile/0x...")
    print("  2. SIGNATURE_TYPE=2 (Gnosis Safe) with FUNDER=profile")
    print("  3. Polymarket Discord: discord.gg/polymarket")


if __name__ == "__main__":
    main()
