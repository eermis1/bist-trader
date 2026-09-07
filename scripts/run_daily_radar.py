#!/usr/bin/env python3
"""Daily high-risk radar: momentum (top gainers / near daily limit) + KAP flags.

Combines:
  1. Price screener: today's top-N gainers and anyone within
     config.NEAR_LIMIT_THRESHOLD_PCT of the daily move limit.
  2. KAP screener: recent high-priority disclosures (ownership-threshold
     crossings, "unusual price/volume movement" flags, tender offers, etc.)

This is a WATCHLIST tool, not an auto-trader -- it surfaces candidates for
you to review. Nothing here places orders, paper or real.

Usage:
    python scripts/run_daily_radar.py [--universe all|bist100] [--kap-days 3]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bist_trader import config, kap, screener, tickers as tickers_mod  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["all", "bist100"], default=config.UNIVERSE)
    parser.add_argument("--kap-days", type=int, default=config.KAP_LOOKBACK_DAYS)
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    raw_symbols = tickers_mod.load_all_bist_symbols() if args.universe == "all" else tickers_mod.load_bist100_symbols()
    yf_tickers = [tickers_mod.to_yfinance_ticker(s) for s in raw_symbols]
    known_tickers = set(raw_symbols)

    print(f"Scanning {len(yf_tickers)} tickers ({args.universe}) for daily movers...")
    movers = screener.daily_movers(yf_tickers)
    movers["symbol"] = movers["ticker"].str.replace(config.YF_SUFFIX, "", regex=False)
    print(f"Got price data for {len(movers)} tickers.\n")

    print(f"Fetching KAP disclosures from the last {args.kap_days} day(s)...")
    kap_df = kap.scan_recent(days=args.kap_days, known_tickers=known_tickers)
    print(f"Found {len(kap_df)} high-priority KAP disclosures.\n")

    kap_by_symbol: dict[str, list[dict]] = {}
    for _, row in kap_df.iterrows():
        kap_by_symbol.setdefault(row["ticker"], []).append(row.to_dict())

    def score(row) -> float:
        s = 0.0
        if row["near_limit"]:
            s += 3.0
        if row["in_top_gainers"]:
            s += 1.0
        flags = kap_by_symbol.get(row["symbol"], [])
        for f in flags:
            s += 2.0
            if f["subject"] == "Pay Alım Satım Bildirimi":
                s += 1.5
            if f["subject"] == "Olağan Dışı Fiyat ve Miktar Hareketleri":
                s += 1.0
        return s

    movers["kap_flags"] = movers["symbol"].map(lambda s: "; ".join(f["subject"] for f in kap_by_symbol.get(s, [])))
    movers["priority_score"] = movers.apply(score, axis=1)

    radar = movers[(movers["near_limit"]) | (movers["in_top_gainers"]) | (movers["kap_flags"] != "")]
    radar = radar.sort_values("priority_score", ascending=False).head(args.top)

    out_csv = config.REPORT_DIR / f"daily_radar_{movers['date'].iloc[0] if not movers.empty else 'na'}.csv"
    radar.to_csv(out_csv, index=False)

    cols = ["symbol", "pct_change", "close", "near_limit", "in_top_gainers", "kap_flags", "priority_score"]
    print(f"=== Radar (top {len(radar)}, saved to {out_csv}) ===")
    with pd.option_context("display.width", 160, "display.max_colwidth", 50, "display.float_format", "{:.2f}".format):
        print(radar[cols].to_string(index=False))

    if not kap_df.empty:
        print("\n=== All high-priority KAP disclosures (may not have moved price yet) ===")
        with pd.option_context("display.width", 160, "display.max_colwidth", 60):
            print(kap_df[["date", "ticker", "subject", "kap_title", "url"]].to_string(index=False))


if __name__ == "__main__":
    main()
