#!/usr/bin/env python3
"""Start the momentum/KAP paper-trading loop (10,000 TL virtual, max 3 positions).

Usage:
    python scripts/run_momentum_trading.py            # loop while market is open
    python scripts/run_momentum_trading.py --once      # single evaluation cycle, then exit
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import momentum_trader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single cycle instead of looping.")
    parser.add_argument("--poll-seconds", type=int, default=3600)
    args = parser.parse_args()

    if args.once:
        momentum_trader._setup_logging()
        portfolio = momentum_trader._load_or_create_portfolio()
        momentum_trader.run_once(portfolio)
    else:
        momentum_trader.run_loop(poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
