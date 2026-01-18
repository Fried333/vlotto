# vLotto TUI

A terminal app for buying vLotto lottery tickets on the Verus blockchain.

## How to Run

1. Make sure `verusd` is running with RPC enabled
2. Install Python dependency (one time):

```bash
pip install requests
```

3. Run:

```bash
python3 vlotto_tui.py
```

RPC credentials are read from your local Verus config (`VRSC.conf`). If they are not found, the script prompts for them.

## What It Does

The script:

1. Reads the current draw status and ticket offers
2. Lets you pick a funding address
3. Optionally converts VRSC -> vLotto
4. Buys tickets by taking marketplace offers

## How It Works (RPC Flow)

Below is the actual sequence of Verus RPC methods the script uses.

### 1) Connect + chain height

- `getinfo`

Used to display the current block height and estimate time to the draw.

### 2) Discover available ticket offers

- `getoffers "vlotto" true`

The script extracts ticket names from offers (e.g. `3906000_23of32`) to infer:

- draw block
- total tickets
- how many tickets are still listed

### 3) Read lottery parameters (jackpot, matches, phase)

- `getidentity "ledger.vlotto@"`

The script parses `contentmultimap` and reads values like:

- current jackpot
- required matches to win
- draw block
- total tickets
- current phase

### 4) Show your existing tickets

- `listidentities`

Tickets are identities whose `parent` matches the vLotto currency id.

### 5) Address selection + balances

- `listaddressgroupings`
- `getcurrencybalance <address>`

Used to list addresses with VRSC and show per-address balances for VRSC and vLotto.

### 6) Optional swap (VRSC -> vLotto)

If you don’t have enough vLotto to cover `qty * 1.0`, the script:

1. Quotes the required VRSC for an exact vLotto output:
   - `getcurrencyconverters` (exact-out style query)
2. Submits the conversion:
   - `sendcurrency <from_address> [{... convertto: "vlotto" ...}]`
3. Waits for completion / confirmations:
   - `z_getoperationstatus` (when `sendcurrency` returns an `opid-...`)
   - `gettransaction` (wait for confirmations)
4. Polls until the vLotto balance is updated:
   - `getcurrencybalance <address>` (repeated)

### 7) Buy tickets (take offers)

For each ticket, the script:

1. Refreshes the marketplace:
   - `getoffers "vlotto" true`
2. Takes one offer:
   - `takeoffer <from_address> {"txid": <offer_txid>, "changeaddress": <address>, "deliver": {"currency": <vlotto_id>, "amount": 1.0}, "accept": {"identitydefinition": ...}}
3. Waits for 1 confirmation before the next ticket:
   - `gettransaction`

This confirmation wait is intentional: each `takeoffer` is a separate transaction, and waiting avoids transient "rejected" errors from spending change that hasn’t been confirmed yet.

## Notes

- Ticket price is currently assumed to be `1.0 vlotto` per ticket.
- All RPC traffic is localhost-only (`127.0.0.1`).
- Private keys never leave your local wallet; this script only uses RPC calls.

## License

MIT
