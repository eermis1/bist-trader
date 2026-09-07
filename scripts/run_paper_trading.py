#!/usr/bin/env python3
"""Start the continuous BIST100 paper-trading loop (no real orders, ever).

Usage:
    python scripts/run_paper_trading.py            # loop while market is open
    python scripts/run_paper_trading.py --once      # single evaluation cycle, then exit
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import paper_trader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single cycle instead of looping.")
    args = parser.parse_args()

    if args.once:
        paper_trader._setup_logging()
        portfolio = paper_trader._load_or_create_portfolio()
        paper_trader.run_once(portfolio)
    else:
        paper_trader.run_loop()


if __name__ == "__main__":
    main()
