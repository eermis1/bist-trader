#!/usr/bin/env python3
"""Grid-search the strategy's parameters over the BIST100 universe.

Fetches price data once (cached), then re-runs the simulation for every
parameter combination by mutating bist_trader.config in place. Ranks
results by Calmar ratio (CAGR / |max drawdown|) by default -- a decent
single number for "good return without brutal drawdowns", but the full
grid is saved to reports/optimization_results.csv so you can re-sort by
whatever you actually care about (Sharpe, win rate, etc).

Usage:
    python scripts/optimize.py [--years 3] [--top 15] [--rank calmar]
"""

import argparse
import itertools
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import backtest, config, data, tickers as tickers_mod  # noqa: E402

# Keep this grid modest -- each combo re-walks the full daily calendar for
# every ticker. Widen it once you've confirmed run time is acceptable.
GRID = {
    "FAST_MA": [10, 20, 30],
    "SLOW_MA": [50, 100],
    "RSI_BUY_MIN": [45, 50, 55],
    "RSI_SELL_MAX": [35, 45],
    "STOP_LOSS_PCT": [0.05, 0.08, 0.12],
    "TAKE_PROFIT_PCT": [0.15, 0.25],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=config.BACKTEST_LOOKBACK_YEARS)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--rank", type=str, default="calmar", choices=["calmar", "sharpe", "cagr_pct", "total_return_pct"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    yf_tickers = tickers_mod.load_yfinance_universe()
    print(f"Fetching data for {len(yf_tickers)} tickers ({args.years}y, cached where possible)...")
    raw = data.fetch_universe(yf_tickers, period=f"{args.years}y", interval=config.BACKTEST_INTERVAL)
    if not raw:
        raise SystemExit("No data fetched -- aborting.")
    print(f"Got usable data for {len(raw)} tickers.\n")

    keys = list(GRID.keys())
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    # fast MA must be strictly below slow MA to mean anything
    combos = [c for c in combos if c[keys.index("FAST_MA")] < c[keys.index("SLOW_MA")]]
    print(f"Running {len(combos)} parameter combinations...\n")

    results = []
    t0 = time.time()
    for i, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        for k, v in params.items():
            setattr(config, k, v)

        try:
            _portfolio, metrics, _eq = backtest.simulate(raw, initial_cash=config.INITIAL_CASH)
        except Exception as exc:
            print(f"[{i}/{len(combos)}] {params} -> FAILED: {exc}")
            continue

        if metrics:
            results.append({**params, **metrics})

        if i % 10 == 0 or i == len(combos):
            elapsed = time.time() - t0
            print(f"[{i}/{len(combos)}] done, {elapsed:.0f}s elapsed")

    if not results:
        raise SystemExit("No successful runs.")

    import pandas as pd

    df = pd.DataFrame(results)
    out_csv = config.REPORT_DIR / "optimization_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nFull results ({len(df)} rows) saved to {out_csv}")

    df_ranked = df.replace([float("inf"), float("-inf")], float("nan")).dropna(subset=[args.rank])
    df_ranked = df_ranked.sort_values(args.rank, ascending=False).head(args.top)

    cols = ["FAST_MA", "SLOW_MA", "RSI_BUY_MIN", "RSI_SELL_MAX", "STOP_LOSS_PCT", "TAKE_PROFIT_PCT",
            "cagr_pct", "max_drawdown_pct", "sharpe", "calmar", "num_trades", "win_rate_pct"]
    print(f"\n=== Top {len(df_ranked)} by {args.rank} ===")
    with pd.option_context("display.width", 160, "display.max_columns", 20, "display.float_format", "{:.2f}".format):
        print(df_ranked[cols].to_string(index=False))


if __name__ == "__main__":
    main()
