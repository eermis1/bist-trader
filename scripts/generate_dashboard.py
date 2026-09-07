#!/usr/bin/env python3
"""Refresh reports/dashboard_data.json from the current portfolio state(s).

Usually not needed standalone -- momentum_trader.run_once() and
paper_trader.run_once() already refresh it after every cycle. Useful to
force a refresh on demand (e.g. right before viewing the dashboard).

Usage:
    python scripts/generate_dashboard.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bist_trader import dashboard  # noqa: E402


def main() -> None:
    snapshot = dashboard.write_snapshot()
    print(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
