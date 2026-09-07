#!/usr/bin/env python3
"""Single hourly entry point: refreshes everything the dashboard needs.

Replaces run_momentum_trading.py as the Windows Scheduled Task's target
(2026-09-06) -- the original momentum/trend paper-trading strategies
(10.000 TL / 100.000 TL) were retired in favor of the Senaryo 1/2/3
framework. dashboard.write_snapshot() internally:
  - runs Senaryo 3's active trading cycle (scan, checklist, buy/sell)
  - refreshes Senaryo 1/2's buy-and-hold prices
  - refreshes BIST Ekranı, Fonlar, Haberler, Öneriler
  - writes reports/dashboard.html and dashboard_data.json

Usage:
    python scripts/run_dashboard_cycle.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import config, dashboard  # noqa: E402


def main() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_DIR / "dashboard_cycle.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    dashboard.write_snapshot()


if __name__ == "__main__":
    main()
