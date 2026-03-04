#!/usr/bin/env python3
"""
Set token approvals for Polymarket trading. Run once before placing orders.
Uses your PRIVATE_KEY - signs from your MetaMask address. Requires POL for gas.

If you get "Cannot connect to Polygon RPC":
  - Add POLYGON_RPC to PMSC.env with a free Alchemy URL:
    https://polygon-mainnet.g.alchemy.com/v2/YOUR_API_KEY
  - Or try from a different network (e.g. mobile hotspot) in case your network blocks RPC.
"""
import os
import sys
import time
import requests
from dotenv import load_dotenv
load_dotenv("PMSC.env")

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

# Try env first, then multiple public endpoints (some networks block certain hosts)
RPC_URLS = [
    os.getenv("POLYGON_RPC"),
    "https://polygon-rpc.com",
    "https://polygon.llamarpc.com",
    "https://rpc.ankr.com/polygon",
    "https://1rpc.io/matic",
    "https://polygon-mainnet.public.blastapi.io",
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
]
RPC = next((u for u in RPC_URLS if u and u.strip()), "https://polygon-rpc.com")
CHAIN_ID = 137

USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

ERC20_APPROVE = [{"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"}]
ERC1155_APPROVE = [{"inputs": [{"internalType": "address", "name": "operator", "type": "address"}, {"internalType": "bool", "name": "approved", "type": "bool"}], "name": "setApprovalForAll", "outputs": [], "type": "function"}]

def _test_rpc(url, timeout=15):
    """Try a single RPC with a simple JSON-RPC call; return (True, None) or (False, error_msg)."""
    try:
        r = requests.post(
            url,
            json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        data = r.json()
        if "result" not in data and "error" in data:
            return False, data["error"].get("message", str(data["error"]))
        return True, None
    except requests.exceptions.Timeout:
        return False, "timeout"
    except requests.exceptions.SSLError as e:
        return False, f"SSL: {e}"
    except requests.exceptions.ConnectionError as e:
        return False, f"connection: {str(e)[:80]}"
    except Exception as e:
        return False, str(e)[:80]


def main():
    key = os.getenv("PRIVATE_KEY", "").strip()
    if not key:
        print("Set PRIVATE_KEY in PMSC.env")
        return

    # Find a working RPC: test each and use the first that responds
    candidates = [u for u in RPC_URLS if u and u.strip()]
    working_rpc = None
    print("Testing Polygon RPC endpoints...")
    for url in candidates:
        ok, err = _test_rpc(url)
        if ok:
            print(f"  OK: {url[:60]}...")
            working_rpc = url
            break
        print(f"  FAIL: {url[:50]}... -> {err}")
    if not working_rpc:
        print("\nCannot connect to any Polygon RPC. Try:")
        print("  1. Add POLYGON_RPC to PMSC.env with a free Alchemy URL:")
        print("     https://polygon-mainnet.g.alchemy.com/v2/YOUR_API_KEY")
        print("  2. Check firewall/VPN or try another network (e.g. mobile hotspot).")
        sys.exit(1)

    from web3.providers import HTTPProvider
    session = requests.Session()
    provider = HTTPProvider(working_rpc, request_kwargs={"timeout": 60}, session=session)
    w3 = Web3(provider)
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)  # Polygon is POA; required for block parsing
    if not w3.is_connected():
        print("Web3 could not connect (unexpected after RPC test).")
        sys.exit(1)

    acct = Account.from_key(key)
    addr = acct.address
    pol = w3.eth.get_balance(addr)
    print(f"Address: {addr}")
    print(f"POL balance: {w3.from_wei(pol, 'ether')} POL (need ~0.01 for gas)")
    if pol < w3.to_wei(0.005, "ether"):
        print("Low POL - add some to pay for gas")
        return

    nonce = w3.eth.get_transaction_count(addr)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_APPROVE)
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=ERC1155_APPROVE)
    max_uint = 2**256 - 1

    for name, spender in [
        ("CTF Exchange", CTF_EXCHANGE),
        ("Neg Risk Exchange", NEG_RISK_EXCHANGE),
        ("Neg Risk Adapter", NEG_RISK_ADAPTER),
    ]:
        print(f"\nApproving {name}...")
        try:
            tx = usdc.functions.approve(Web3.to_checksum_address(spender), max_uint).build_transaction({
                "chainId": CHAIN_ID, "from": addr, "nonce": nonce, "gas": 100000,
            })
            signed = w3.eth.account.sign_transaction(tx, key)
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
            print(f"  USDC approve: {r['status']}")
            nonce += 1

            tx2 = ctf.functions.setApprovalForAll(Web3.to_checksum_address(spender), True).build_transaction({
                "chainId": CHAIN_ID, "from": addr, "nonce": nonce, "gas": 100000,
            })
            signed2 = w3.eth.account.sign_transaction(tx2, key)
            h2 = w3.eth.send_raw_transaction(signed2.raw_transaction)
            r2 = w3.eth.wait_for_transaction_receipt(h2, timeout=120)
            print(f"  CTF setApprovalForAll: {r2['status']}")
            nonce += 1
        except Exception as e:
            print(f"  Error: {e}")
        time.sleep(2)  # Avoid RPC rate limit (429) when using public endpoints

    print("\nDone. Run again if any approval failed (e.g. 429). Then try the bot.")

if __name__ == "__main__":
    main()
