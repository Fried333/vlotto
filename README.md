# vLotto TUI - Ticket Buyer

A command-line interface (TUI) for purchasing vLotto lottery tickets on the Verus blockchain.

## What is vLotto?

vLotto is a decentralized lottery system built on the Verus blockchain. Tickets are represented as blockchain identities, and drawings are determined by on-chain randomness at specific block heights.

## Features

- **View Draw Information**: Current jackpot, required matches to win, draw block, time until draw
- **Multi-Platform Support**: Automatically detects Verus config files on Linux, macOS, and Windows
- **Address Selection**: Lists wallet addresses with balances for easy selection
- **Automatic Currency Conversion**: Swaps VRSC → vLotto if you don't have enough vLotto tokens
- **Sequential Purchase**: Handles UTXO constraints by waiting for confirmations between purchases
- **Ticket Tracking**: Shows your owned tickets for the current draw

## Requirements

- Python 3.7+
- `requests` library
- Running Verus daemon (`verusd`) with RPC enabled

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/vlotto-tui.git
cd vlotto-tui

# Install dependencies
pip install requests
```

## Usage

```bash
# Basic usage - interactive mode
python vlotto_tui.py

# Specify address directly
python vlotto_tui.py --address RYourVerusAddressHere

# Dry run (don't broadcast transactions)
python vlotto_tui.py --dry-run

# Custom buffer for currency conversion (default 1%)
python vlotto_tui.py --buffer 0.02
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `--address` | Verus address to use for purchases |
| `--buffer` | Buffer percentage for VRSC→vLotto swap (default: 0.01 = 1%) |
| `--dry-run` | Simulate purchases without broadcasting |
| `--max-rounds` | Maximum offer refresh rounds (default: 10) |

## How It Works

1. **Connect**: Reads RPC credentials from your Verus config file
2. **Display Draw Info**: Shows current lottery details (jackpot, draw block, tickets available)
3. **Select Address**: Choose which wallet address to use
4. **Purchase Flow**:
   - Enter number of tickets to buy
   - If needed, automatically swaps VRSC → vLotto
   - Purchases tickets one at a time (waits for confirmations due to UTXO constraints)
5. **Results**: Shows purchased tickets and updated balances

## Config File Locations

The app automatically searches for Verus RPC credentials in:

- **Linux**: `~/.komodo/VRSC/VRSC.conf`
- **macOS**: `~/Library/Application Support/Komodo/VRSC/VRSC.conf`
- **Windows**: `%APPDATA%\Komodo\VRSC\VRSC.conf`

If not found, you'll be prompted to enter credentials manually.

## Example Output

```
============================================================
          vLotto Ticket Buyer (TUI)
============================================================

Connected to verusd | Current block: 3903777

------------------------------------------------------------
                   DRAW INFORMATION
------------------------------------------------------------
  Draw Block:        3906000
  Blocks Until Draw: 2223 (~37.0 hours)
  Jackpot:           31.75 vlotto
  Matches to Win:    1
  Total Tickets:     32
  Available Offers:  13 of 32
  Ticket Price:      1.0 vlotto each

  Your Tickets:      8 for this draw (all wallet addresses)
    3906000_10of32, 3906000_11of32, 3906000_14of32, ...
```

## Security

- RPC credentials are read from local config files only (never hardcoded)
- Passwords entered manually are hidden (uses `getpass`)
- Private keys remain in the Verus wallet daemon (never accessed by this script)
- All communication is localhost-only (`127.0.0.1`)

## License

MIT License - See LICENSE file for details.

## Disclaimer

This software is provided as-is. Use at your own risk. Always verify transactions before confirming. The authors are not responsible for any losses incurred through the use of this software.
