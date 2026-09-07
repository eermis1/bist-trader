"""BIST ticker universe loading.

Two snapshots are bundled:
  - data/bist100_tickers.csv    -- BIST100 index constituents (~100 names)
  - data/bist_all_tickers.csv   -- every KAP-registered BIST ticker (~759,
    generated from pykap's bundled company list; includes some non-equity
    or illiquid names that simply won't return usable price data and get
    skipped automatically by data.fetch_universe)

Both are point-in-time snapshots -- index composition and the company
registry change over time. Regenerate data/bist_all_tickers.csv with
pykap.get_bist_companies(online=True) occasionally to refresh it.

config.UNIVERSE selects which one load_yfinance_universe() returns by
default ("bist100" or "all").
"""

import csv

from . import config


def _load_symbols(path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["symbol"].strip().upper() for row in reader if row["symbol"].strip()]


def load_bist100_symbols() -> list[str]:
    """Return raw BIST100 symbols (no .IS suffix), e.g. ['THYAO', 'GARAN', ...]."""
    return _load_symbols(config.TICKERS_FILE)


def load_all_bist_symbols() -> list[str]:
    """Return raw symbols for every KAP-registered BIST ticker."""
    return _load_symbols(config.ALL_TICKERS_FILE)


def to_yfinance_ticker(symbol: str) -> str:
    return f"{symbol.upper()}{config.YF_SUFFIX}"


def load_yfinance_universe(universe: str | None = None) -> list[str]:
    """universe: "bist100", "all", or None to use config.UNIVERSE."""
    universe = universe or config.UNIVERSE
    symbols = load_all_bist_symbols() if universe == "all" else load_bist100_symbols()
    return [to_yfinance_ticker(s) for s in symbols]
