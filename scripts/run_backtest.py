#!/usr/bin/env python3
"""Run a backtest of the strategy over the BIST100 universe.

Usage:
    python scripts/run_backtest.py [--years 3] [--tickers THYAO,GARAN]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import backtest, config, tickers as tickers_mod  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=config.BACKTEST_LOOKBACK_YEARS)
    parser.add_argument("--tickers", type=str, default="", help="Comma-separated symbols, e.g. THYAO,GARAN. Default: full BIST100 list.")
    parser.add_argument("--cash", type=float, default=config.INITIAL_CASH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    symbols = None
    if args.tickers.strip():
        symbols = [tickers_mod.to_yfinance_ticker(s.strip()) for s in args.tickers.split(",")]

    portfolio, metrics, equity_df = backtest.run_backtest(
        symbols=symbols, period=f"{args.years}y", initial_cash=args.cash
    )
    backtest.print_report(metrics)

    if not equity_df.empty:
        out_csv = config.REPORT_DIR / "backtest_equity_curve.csv"
        equity_df.to_csv(out_csv, index=False)
        print(f"\nEquity curve saved to {out_csv}")

        try:
            import matplotlib.pyplot as plt

            eq = equity_df.copy()
            eq["date"] = eq["date"]
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(range(len(eq)), eq["equity"])
            ax.set_title("BIST100 Strategy Backtest - Equity Curve")
            ax.set_xlabel("Trading day")
            ax.set_ylabel("Equity (TL)")
            fig.tight_layout()
            out_png = config.REPORT_DIR / "backtest_equity_curve.png"
            fig.savefig(out_png, dpi=120)
            print(f"Equity curve chart saved to {out_png}")
        except Exception as exc:
            print(f"(chart skipped: {exc})")


if __name__ == "__main__":
    main()
