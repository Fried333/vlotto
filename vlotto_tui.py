#!/usr/bin/env python3

 
import json
import os
import getpass
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.exceptions import ConnectionError, Timeout, RequestException


DEFAULT_RPC_URL = "http://127.0.0.1:27486/"

# Config file paths for Linux, macOS, and Windows
DEFAULT_CONF_PATHS = [
    # Linux
    os.path.expanduser("~/.komodo/VRSC/VRSC.conf"),
    # macOS
    os.path.expanduser("~/Library/Application Support/Komodo/VRSC/VRSC.conf"),
    # Windows (via APPDATA)
    os.path.join(os.environ.get("APPDATA", ""), "Komodo", "VRSC", "VRSC.conf"),
]


def load_rpc_credentials_from_conf() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    rpcuser = None
    rpcpassword = None
    rpcport = None

    for path in DEFAULT_CONF_PATHS:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("rpcuser="):
                        rpcuser = line.split("=", 1)[1].strip()
                    elif line.startswith("rpcpassword="):
                        rpcpassword = line.split("=", 1)[1].strip()
                    elif line.startswith("rpcport="):
                        rpcport = line.split("=", 1)[1].strip()
        except OSError:
            continue

        if rpcuser and rpcpassword:
            break

    url = DEFAULT_RPC_URL
    if rpcport and rpcport.isdigit():
        url = f"http://127.0.0.1:{rpcport}/"

    return rpcuser, rpcpassword, url


@dataclass
class RpcClient:
    url: str
    user: str
    password: str

    def call(self, method: str, params: List[Any]) -> Any:
        payload = {
            "jsonrpc": "1.0",
            "id": "vlotto_tui",
            "method": method,
            "params": params,
        }
        try:
            resp = requests.post(
                self.url,
                headers={"Content-Type": "application/json"},
                json=payload,
                auth=(self.user, self.password),
                timeout=60,
            )
            data = resp.json()
        except (ConnectionError, Timeout, RequestException) as e:
            raise RuntimeError(f"RPC connection error: {e}")
        except ValueError:
            raise RuntimeError(f"RPC returned non-JSON response (HTTP {getattr(resp, 'status_code', 'n/a')})")

        if data.get("error"):
            err = data["error"]
            if isinstance(err, dict) and "message" in err:
                raise RuntimeError(err["message"])
            raise RuntimeError(str(err))

        return data.get("result")

    def batch_call(self, calls: List[Tuple[str, List[Any]]]) -> List[Any]:
        """Send multiple RPC calls in a single HTTP request (JSON-RPC batch)."""
        payloads = [
            {"jsonrpc": "1.0", "id": f"batch_{i}", "method": method, "params": params}
            for i, (method, params) in enumerate(calls)
        ]
        try:
            resp = requests.post(
                self.url,
                headers={"Content-Type": "application/json"},
                json=payloads,
                auth=(self.user, self.password),
                timeout=120,
            )
            data = resp.json()
        except (ConnectionError, Timeout, RequestException) as e:
            raise RuntimeError(f"RPC connection error: {e}")
        except ValueError:
            raise RuntimeError(f"RPC returned non-JSON response")

        # Parse batch response - returns list of results in order
        results = []
        if isinstance(data, list):
            for item in data:
                if item.get("error"):
                    err = item["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    results.append({"error": msg})
                else:
                    results.append({"result": item.get("result")})
        return results


def sleep_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)


def extract_offers_list(getoffers_result: Any) -> List[Dict[str, Any]]:
    if isinstance(getoffers_result, list):
        return getoffers_result
    if isinstance(getoffers_result, dict):
        list_values = [v for v in getoffers_result.values() if isinstance(v, list)]
        if len(list_values) == 1:
            return list_values[0]
    return []


def parse_ticket_name(name: str) -> Dict[str, Any]:
    """Parse ticket name like '3906000_32of32' into components."""
    result = {"raw": name, "draw_block": None, "ticket_num": None, "total_tickets": None}
    if "_" not in name:
        return result
    parts = name.split("_", 1)
    try:
        result["draw_block"] = int(parts[0])
    except ValueError:
        pass
    if len(parts) > 1 and "of" in parts[1]:
        ticket_part = parts[1]
        of_parts = ticket_part.split("of")
        if len(of_parts) == 2:
            try:
                result["ticket_num"] = int(of_parts[0])
                result["total_tickets"] = int(of_parts[1])
            except ValueError:
                pass
    return result


def summarize_offers(offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_draw: Dict[str, List[str]] = {}
    names = []
    draw_info: Dict[str, Dict[str, Any]] = {}
    
    for o in offers:
        name = (((o or {}).get("offer") or {}).get("offer") or {}).get("name")
        if not name:
            continue
        names.append(name)
        parsed = parse_ticket_name(name)
        draw_block = parsed.get("draw_block")
        if draw_block:
            draw_key = str(draw_block)
            by_draw.setdefault(draw_key, []).append(name)
            if draw_key not in draw_info:
                draw_info[draw_key] = {
                    "draw_block": draw_block,
                    "total_tickets": parsed.get("total_tickets"),
                }

    draws_sorted = sorted(by_draw.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return {
        "total": len(offers),
        "ticket_names": names,
        "draws": draws_sorted,
        "draw_info": draw_info,
    }


def get_currency_balance(rpc: RpcClient, address: str, currency: str) -> float:
    """Get balance of a specific currency for an address."""
    try:
        # getcurrencybalance returns dict of {currency: balance}
        bal_dict = rpc.call("getcurrencybalance", [address])
        if isinstance(bal_dict, dict):
            # Try exact match first, then case-insensitive
            if currency in bal_dict:
                return float(bal_dict[currency])
            for k, v in bal_dict.items():
                if k.lower() == currency.lower():
                    return float(v)
        return 0.0
    except Exception:
        return 0.0


def get_addresses_with_vrsc(rpc: RpcClient, min_balance: float = 0.0) -> List[Tuple[str, float]]:
    """Get list of addresses with VRSC balance >= min_balance."""
    result = []
    try:
        groupings = rpc.call("listaddressgroupings", [])
        if isinstance(groupings, list):
            for group in groupings:
                if isinstance(group, list):
                    for entry in group:
                        if isinstance(entry, list) and len(entry) >= 2:
                            addr = entry[0]
                            bal = float(entry[1]) if entry[1] else 0.0
                            if bal >= min_balance:
                                result.append((addr, bal))
    except Exception:
        pass
    result.sort(key=lambda x: -x[1])
    return result


def get_best_exact_out_converter(rpc: RpcClient, from_currency: str, to_currency: str, to_amount: float) -> Tuple[float, str]:
    query = {
        "fromcurrency": [{"currency": from_currency}],
        "convertto": to_currency,
        "amount": round(float(to_amount), 8),
    }

    res = rpc.call("getcurrencyconverters", [json.dumps(query)])
    if not isinstance(res, list) or not res:
        raise RuntimeError(f"No converters found for {from_currency} -> {to_currency}")

    best_required = None
    best_via = None

    for c in res:
        via = (c or {}).get("fullyqualifiedname")
        sourceamounts = (c or {}).get("sourceamounts")
        if not via or not isinstance(sourceamounts, dict) or not sourceamounts:
            continue
        vals = [float(v) for v in sourceamounts.values() if isinstance(v, (int, float, str))]
        vals = [v for v in vals if v == v and v > 0]
        if not vals:
            continue
        required = vals[0]
        if best_required is None or required < best_required:
            best_required = required
            best_via = via

    if best_required is None or best_via is None:
        raise RuntimeError(f"No usable converter route found for {from_currency} -> {to_currency}")

    return round(float(best_required), 8), best_via


def sendcurrency_convert(rpc: RpcClient, from_address: str, from_currency: str, to_currency: str, amount_in: float, via: Optional[str]) -> str:
    obj: Dict[str, Any] = {
        "address": from_address,
        "amount": round(float(amount_in), 8),
        "currency": from_currency,
        "convertto": to_currency,
    }
    # For VRSC -> vlotto (reserve to basket), NO via needed - direct conversion
    # Only use via for multi-hop conversions
    if via and via.lower() != to_currency.lower():
        obj["via"] = via

    result = rpc.call("sendcurrency", [from_address, [obj]])
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and "txid" in result:
        return str(result["txid"])
    return str(result)


def wait_for_opid_success(rpc: RpcClient, opid: str) -> str:
    """Wait indefinitely for opid to complete. Returns txid on success."""
    print(f"    Waiting for operation {opid[:20]}...")
    while True:
        status = rpc.call("z_getoperationstatus", [[opid]])
        if isinstance(status, list) and status:
            s0 = status[0]
            st = s0.get("status")
            if st == "success":
                txid = (s0.get("result") or {}).get("txid")
                print(f"    Operation succeeded, txid: {txid}")
                return txid or ""
            if st == "failed":
                err = (s0.get("error") or {}).get("message")
                raise RuntimeError(err or "Operation failed")
            # Still executing/queued
            print(f"    Status: {st}...", end="\r")
        sleep_ms(3000)


def get_tx_confirmations(rpc: RpcClient, txid: str) -> int:
    """Get confirmations for a txid. Returns -1 if orphaned, 0 if pending."""
    try:
        tx = rpc.call("gettransaction", [txid])
        if isinstance(tx, dict):
            return tx.get("confirmations", 0)
    except Exception:
        pass
    return 0


def wait_for_tx_confirmed(rpc: RpcClient, txid: str, min_confirmations: int = 1) -> int:
    """Wait for tx to get confirmations. Returns confirmations count."""
    print(f"    Waiting for tx {txid[:16]}... to confirm")
    while True:
        confs = get_tx_confirmations(rpc, txid)
        if confs >= min_confirmations:
            print(f"    Confirmed with {confs} confirmations")
            return confs
        if confs == -1:
            raise RuntimeError(f"Transaction {txid} was orphaned (confirmations=-1)")
        print(f"    Confirmations: {confs} (waiting for {min_confirmations})...", end="\r")
        sleep_ms(5000)


def wait_for_balance(rpc: RpcClient, address: str, currency: str, min_balance: float) -> float:
    """Wait indefinitely for balance to reach min_balance."""
    print(f"    Waiting for {currency} balance >= {min_balance:.4f}...")
    while True:
        bal = get_currency_balance(rpc, address, currency)
        if bal >= min_balance:
            print(f"    Balance: {bal:.8f} {currency}")
            return bal
        print(f"    Balance: {bal:.8f} (need {min_balance:.4f})...", end="\r")
        sleep_ms(5000)


VLOTTO_CURRENCY_ID = "iMLmoaN3SS8KdJwb7fG4WZxJMFrjJxHBfj"


def get_ledger_info(rpc: 'RpcClient') -> Dict[str, Any]:
    """Fetch ledger.vlotto@ and parse lottery parameters from contentmultimap."""
    info = {
        "jackpot": None,
        "required_matches": None,
        "drawing_block": None,
        "total_tickets": None,
        "tickets_on_marketplace": None,
        "current_phase": None,
    }
    try:
        ledger = rpc.call("getidentity", ["ledger.vlotto@"])
        if not isinstance(ledger, dict):
            return info
        
        identity = ledger.get("identity", {})
        contentmultimap = identity.get("contentmultimap", {})
        
        # Parse the nested JSON from contentmultimap
        for key, entries in contentmultimap.items():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        for inner_key, inner_val in entry.items():
                            if isinstance(inner_val, dict):
                                obj_data = inner_val.get("objectdata", {})
                                message = obj_data.get("message", "")
                                if message and message.startswith("{"):
                                    try:
                                        data = json.loads(message)
                                        params = data.get("lotteryParameters", {})
                                        financial = data.get("financialSummary", {})
                                        tickets = data.get("ticketSummary", {})
                                        
                                        info["jackpot"] = financial.get("jackpotCurrent")
                                        info["required_matches"] = params.get("requiredMatches")
                                        info["drawing_block"] = params.get("drawingBlock")
                                        info["total_tickets"] = tickets.get("planned")
                                        info["tickets_on_marketplace"] = tickets.get("onMarketplace")
                                        info["current_phase"] = data.get("currentPhase")
                                        return info
                                    except json.JSONDecodeError:
                                        pass
    except Exception:
        pass
    return info


def take_ticket_offer(
    rpc: RpcClient,
    from_address: str,
    change_address: str,
    offer_entry: Dict[str, Any],
    returntx: bool,
) -> Any:
    # Extract offer details
    offer_txid = ((offer_entry.get("offer") or {}).get("txid"))
    ticket_name = (((offer_entry.get("offer") or {}).get("offer") or {}).get("name"))
    identity_id = offer_entry.get("identityid")
    
    if not offer_txid or not ticket_name:
        raise RuntimeError("Offer missing txid or ticket name")
    if not identity_id:
        raise RuntimeError("Offer missing identityid")

    # Format: "ticketname@" (not ".vlotto@")
    identity_name = f"{ticket_name}@"

    # Build accept with identityid from the offer
    accept_def = {
        "name": identity_name,
        "parent": "vlotto",
        "primaryaddresses": [from_address],
        "minimumsignatures": 1,
        "identityid": identity_id,
    }

    # First param is the source address for funds
    params = [
        from_address,
        {
            "txid": offer_txid,
            "changeaddress": change_address,
            "deliver": {"currency": VLOTTO_CURRENCY_ID, "amount": 1.0},
            "accept": accept_def,
        },
    ]
    if returntx:
        params.append(True)

    result = rpc.call("takeoffer", params)
    return {
        "offer_txid": offer_txid,
        "ticket": ticket_name,
        "result": result,
    }


def prompt(text: str, default: Optional[str] = None) -> str:
    if default is None:
        return input(text)
    v = input(f"{text} [{default}]: ").strip()
    return v if v else default


def get_my_tickets(rpc: RpcClient, address: Optional[str] = None) -> List[str]:
    """Get list of vlotto ticket identities owned by wallet (optionally filter by address)."""
    tickets = []
    try:
        # listidentities returns identities controlled by wallet
        ids = rpc.call("listidentities", [])
        if isinstance(ids, list):
            for id_entry in ids:
                if isinstance(id_entry, dict):
                    id_info = id_entry.get("identity", {})
                    name = id_info.get("name", "")
                    parent = id_info.get("parent", "")
                    # Check if it's a vlotto ticket (parent is vlotto currency ID)
                    if parent == VLOTTO_CURRENCY_ID:
                        # If address specified, check ownership
                        if address:
                            primary = id_info.get("primaryaddresses", [])
                            if address in primary:
                                tickets.append(name)
                        else:
                            tickets.append(name)
    except Exception:
        pass
    return sorted(tickets)


def main() -> None:
    buffer_percent = 0.01
    dry_run = False

    # Load from config file (checks Linux, macOS, Windows paths)
    rpcuser, rpcpass, url = load_rpc_credentials_from_conf()
    rpcuser = rpcuser or ""
    rpcpass = rpcpass or ""
    url = url or DEFAULT_RPC_URL

    if not rpcuser or not rpcpass:
        print("RPC credentials not found in config files.")
        print("Searched paths:")
        for p in DEFAULT_CONF_PATHS:
            print(f"  - {p}")
        print()
        # Prompt for manual entry
        rpcuser = prompt("Enter RPC username")
        rpcpass = getpass.getpass("Enter RPC password: ")
        if not rpcuser or not rpcpass:
            raise SystemExit("RPC credentials required.")

    rpc = RpcClient(url=url, user=rpcuser, password=rpcpass)

    print("=" * 60)
    print("          vLotto Ticket Buyer (TUI)")
    print("=" * 60)

    info = rpc.call("getinfo", [])
    current_height = info.get("blocks") if isinstance(info, dict) else 0
    print(f"\nConnected to verusd | Current block: {current_height}")

    # Fetch offers and parse draw info
    offers_raw = rpc.call("getoffers", ["vlotto", True])
    offers = extract_offers_list(offers_raw)
    summary = summarize_offers(offers)

    # Fetch ledger info for jackpot and win criteria
    ledger_info = get_ledger_info(rpc)
    
    # Display draw information
    print("\n" + "-" * 60)
    print("                   DRAW INFORMATION")
    print("-" * 60)
    
    if summary["draws"]:
        draw_key, ticket_names = summary["draws"][0]
        draw_meta = summary["draw_info"].get(draw_key, {})
        draw_block = ledger_info.get("drawing_block") or draw_meta.get("draw_block", int(draw_key) if draw_key.isdigit() else None)
        total_tickets = ledger_info.get("total_tickets") or draw_meta.get("total_tickets")
        available_tickets = len(ticket_names)
        jackpot = ledger_info.get("jackpot")
        required_matches = ledger_info.get("required_matches")
        current_phase = ledger_info.get("current_phase")
        
        if draw_block and current_height:
            blocks_until = draw_block - current_height
            est_minutes = blocks_until  # ~1 block per minute
            est_hours = est_minutes / 60
            if est_hours >= 1:
                time_str = f"~{est_hours:.1f} hours"
            else:
                time_str = f"~{est_minutes} minutes"
        else:
            blocks_until = None
            time_str = "unknown"
        
        print(f"  Draw Block:        {draw_block or 'unknown'}")
        if blocks_until is not None:
            print(f"  Blocks Until Draw: {blocks_until} ({time_str})")
        if jackpot is not None:
            print(f"  Jackpot:           {jackpot} vlotto")
        if required_matches is not None:
            print(f"  Matches to Win:    {required_matches}")
        if total_tickets:
            print(f"  Total Tickets:     {total_tickets}")
        print(f"  Available Offers:  {available_tickets} of {total_tickets or '?'}")
        print(f"  Ticket Price:      1.0 vlotto each")
        if current_phase:
            phase_display = current_phase.replace("_", " ").replace("phase", "Phase ")
            print(f"  Current Phase:     {phase_display}")
        
        # Show user's current tickets for this draw (all addresses in wallet)
        my_tickets = get_my_tickets(rpc)
        draw_prefix = str(draw_block) + "_" if draw_block else ""
        my_draw_tickets = [t for t in my_tickets if t.startswith(draw_prefix)]
        print(f"\n  Your Tickets:      {len(my_draw_tickets)} for this draw (all wallet addresses)")
        if my_draw_tickets:
            print(f"    {', '.join(sorted(my_draw_tickets))}")
    else:
        print("  No offers found in marketplace.")
        raise SystemExit("No tickets available to purchase.")

    # Get addresses with VRSC balance
    print("\n" + "-" * 60)
    print("                   SELECT ADDRESS")
    print("-" * 60)
    
    addresses = get_addresses_with_vrsc(rpc, min_balance=0.001)
    
    address = os.environ.get("VERUS_ADDRESS")
    
    if not address:
        if not addresses:
            print("No addresses with VRSC balance found.")
            address = prompt("Enter address manually")
        else:
            print("\nAddresses with VRSC balance:")
            for i, (addr, bal) in enumerate(addresses):
                vlotto_bal = get_currency_balance(rpc, addr, "vlotto")
                print(f"  [{i+1}] {addr}")
                print(f"      VRSC: {bal:.8f}  |  vlotto: {vlotto_bal:.8f}")
            print()
            choice = prompt(f"Select address (1-{len(addresses)}) or enter manually", default="1")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(addresses):
                    address = addresses[idx][0]
                else:
                    address = choice
            except ValueError:
                address = choice

    # Get balances for selected address
    vlotto_balance = get_currency_balance(rpc, address, "vlotto")
    vrsc_balance = get_currency_balance(rpc, address, "VRSC")
    
    print(f"\nSelected address: {address}")
    print(f"  VRSC balance:   {vrsc_balance:.8f}")
    print(f"  vLotto balance: {vlotto_balance:.8f}")

    change_address = address  # Use same address for change

    # Ask how many tickets
    print("\n" + "-" * 60)
    print("                   BUY TICKETS")
    print("-" * 60)
    
    max_affordable = int(vlotto_balance) if vlotto_balance >= 1.0 else 0
    available = len(ticket_names) if summary["draws"] else 0
    
    print(f"\n  You can afford:    {max_affordable} tickets (with current vlotto)")
    print(f"  Available offers:  {available} tickets")
    print(f"  (If you need more vlotto, we will swap VRSC -> vlotto automatically)")
    
    qty_raw = prompt("\nHow many tickets to buy", default="1")
    try:
        qty = int(qty_raw)
        if qty <= 0:
            raise ValueError
    except ValueError:
        raise SystemExit("quantity must be a positive integer")

    ticket_price = 1.0
    needed = qty * ticket_price
    vlotto_balance = get_currency_balance(rpc, address, "vlotto")
    deficit = max(0.0, needed - vlotto_balance)

    buf = buffer_percent
    if buf < 0:
        buf = 0.0

    deficit_with_buffer = deficit * (1.0 + buf) if deficit > 0 else 0.0

    # Calculate swap requirement if needed
    swap_opid = None
    required_vrsc = 0.0
    via = None
    
    if deficit_with_buffer > 0:
        required_vrsc, via = get_best_exact_out_converter(rpc, "VRSC", "vlotto", deficit_with_buffer)

    # Show complete purchase summary
    print("\n" + "-" * 60)
    print("                   ORDER SUMMARY")
    print("-" * 60)
    print(f"\n  Tickets to buy:    {qty}")
    print(f"  Cost per ticket:   1.0 vlotto")
    print(f"  Total vlotto:      {needed:.8f} vlotto")
    print(f"\n  Your vlotto:       {vlotto_balance:.8f}")
    
    if deficit > 0:
        print(f"  Deficit:           {deficit:.8f} vlotto")
        print(f"  + {buf*100:.1f}% buffer:      {deficit_with_buffer:.8f} vlotto")
        print(f"\n  VRSC needed:       {required_vrsc:.8f} VRSC")
        print(f"  Your VRSC:         {vrsc_balance:.8f}")
        print(f"  Swap via:          {via}")
        
        if vrsc_balance < required_vrsc:
            print(f"\n  ⚠ WARNING: Insufficient VRSC balance!")
            print(f"     Need {required_vrsc:.8f}, have {vrsc_balance:.8f}")
    else:
        print(f"\n  ✓ Sufficient vlotto balance - no swap needed")

    print("\n" + "-" * 60)
    confirm = prompt("Confirm purchase? (y/n)", default="y").lower()
    if confirm != "y":
        raise SystemExit("Cancelled by user.")

    # Execute swap if needed
    if deficit_with_buffer > 0:
        print(f"\nSwapping {required_vrsc:.8f} VRSC -> vlotto...")
        print(f"  From address: {address}")
        swap_opid = sendcurrency_convert(rpc, address, "VRSC", "vlotto", required_vrsc, via)
        print(f"  Swap submitted: {swap_opid}")

        if swap_opid.startswith("opid-"):
            swap_txid = wait_for_opid_success(rpc, swap_opid)
            # Wait for at least 1 confirmation
            wait_for_tx_confirmed(rpc, swap_txid, min_confirmations=1)

        print("\n  Checking vlotto balance...")
        vlotto_balance = wait_for_balance(rpc, address, "vlotto", needed)
        print(f"  vlotto balance now: {vlotto_balance:.8f}")

    # Buy tickets sequentially - each takeoffer is a separate tx needing its own UTXO
    print(f"\nBuying {qty} tickets...")
    print(f"  Using address: {address}")

    purchased = []
    errors = []
    attempted = set()
    bought = 0
    last_txid = None

    while bought < qty:
        # Refresh offers to get current state
        offers_raw = rpc.call("getoffers", ["vlotto", True])
        offers = extract_offers_list(offers_raw)
        offers.sort(key=lambda o: ((((o or {}).get("offer") or {}).get("offer") or {}).get("name") or ""))

        # Find next available offer
        found_offer = None
        for offer in offers:
            txid = ((offer.get("offer") or {}).get("txid"))
            if txid and txid not in attempted:
                found_offer = offer
                break

        if not found_offer:
            print("  No more offers available")
            break

        offer_txid = ((found_offer.get("offer") or {}).get("txid"))
        attempted.add(offer_txid)

        try:
            r = take_ticket_offer(rpc, address, change_address, found_offer, returntx=dry_run)
            result = r.get("result")
            
            # Extract txid
            tx_id = None
            if isinstance(result, str) and len(result) >= 64:
                tx_id = result.strip()[:64]
            elif isinstance(result, dict) and "txid" in result:
                tx_id = result["txid"]
            
            purchased.append(r)
            bought += 1
            print(f"  ✓ {bought}/{qty}: {r['ticket']}")
            
            # Wait for this tx to confirm before next purchase (UTXO availability)
            if tx_id and bought < qty and not dry_run:
                wait_for_tx_confirmed(rpc, tx_id, min_confirmations=1)
            elif tx_id:
                last_txid = tx_id
            
        except Exception as e:
            err_msg = str(e)
            if "rejected" in err_msg.lower():
                # UTXO not ready, wait for previous tx to confirm
                if last_txid:
                    print(f"  ⏳ Waiting for previous tx to confirm...")
                    wait_for_tx_confirmed(rpc, last_txid, min_confirmations=1)
                else:
                    print(f"  ⏳ Waiting for UTXO...")
                    sleep_ms(5000)
                # Retry this offer
                attempted.discard(offer_txid)
            else:
                errors.append({"offer_txid": offer_txid, "error": err_msg})
                print(f"  ✗ Failed: {err_msg[:50]}")

    # Wait for last transaction to confirm if not already done
    if last_txid and not dry_run:
        print(f"\n  Waiting for final confirmation...")
        wait_for_tx_confirmed(rpc, last_txid, min_confirmations=1)

    print("\n" + "=" * 60)
    print("                      RESULT")
    print("=" * 60)
    
    if bought == qty:
        print(f"\n  ✓ SUCCESS: Bought {bought}/{qty} tickets")
    elif bought > 0:
        print(f"\n  ⚠ PARTIAL: Bought {bought}/{qty} tickets")
    else:
        print(f"\n  ✗ FAILED: Could not buy any tickets")
    
    if swap_opid:
        print(f"\n  Swap txid: {swap_opid}")

    if purchased:
        print("\n  Purchased tickets:")
        for p in purchased:
            print(f"    - {p['ticket']}")

    if errors and bought < qty:
        print("\n  Errors (race conditions are normal):")
        for e in errors[:5]:
            print(f"    - {e['error'][:60]}")
        if len(errors) > 5:
            print(f"    ... (+{len(errors) - 5} more)")
    
    # Show current ticket holdings
    print("\n" + "-" * 60)
    print("                   YOUR TICKETS")
    print("-" * 60)
    my_tickets = get_my_tickets(rpc, address)
    vlotto_balance = get_currency_balance(rpc, address, "vlotto")
    vrsc_balance = get_currency_balance(rpc, address, "VRSC")
    
    print(f"\n  Address: {address}")
    print(f"  VRSC balance:   {vrsc_balance:.8f}")
    print(f"  vLotto balance: {vlotto_balance:.8f}")
    print(f"  Tickets owned:  {len(my_tickets)}")
    
    if my_tickets:
        print(f"    {', '.join(sorted(my_tickets))}")
    
    print()
    
    # Ask if user wants to buy more
    again = prompt("Buy more tickets? (y/n)", default="n").lower()
    if again == "y":
        # Restart the buy flow (recursive call or loop)
        print("\n")
        main()


if __name__ == "__main__":
    main()
