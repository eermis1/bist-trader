"""Daily momentum screener: today's biggest gainers / near the daily limit.

Data is yfinance end-of-day (delayed ~15-20 min at best, effectively
next-bar once the session closes) -- this flags stocks that closed near
their daily limit or among the day's top gainers, not a real-time
"about to hit the ceiling" alert. Wire in a live/streaming feed if you
need true intraday detection.
"""

from __future__ import annotations

import logging

import pandas as pd

from . import config, data

log = logging.getLogger(__name__)


def daily_movers(tickers: list[str], period: str = "5d") -> pd.DataFrame:
    """Latest daily % change for each ticker, ranked descending.

    Columns: ticker, date, close, prev_close, pct_change, volume,
             near_limit, in_top_gainers
    """
    rows = []
    for t in tickers:
        df = data.fetch_history(t, period=period, interval="1d", use_cache=True, max_age_hours=6)
        if len(df) < 2:
            continue
        last, prev = df.iloc[-1], df.iloc[-2]
        pct = (last["Close"] / prev["Close"] - 1) * 100
        rows.append({
            "ticker": t,
            "date": str(df.index[-1].date()),
            "close": float(last["Close"]),
            "prev_close": float(prev["Close"]),
            "pct_change": float(pct),
            "volume": float(last["Volume"]),
        })

    if not rows:
        return pd.DataFrame(columns=["ticker", "date", "close", "prev_close", "pct_change", "volume", "near_limit", "in_top_gainers"])

    out = pd.DataFrame(rows).sort_values("pct_change", ascending=False).reset_index(drop=True)
    out["near_limit"] = out["pct_change"] >= config.NEAR_LIMIT_THRESHOLD_PCT
    out["in_top_gainers"] = out.index < config.TOP_GAINERS_COUNT
    return out


def top_gainers(tickers: list[str], n: int = config.TOP_GAINERS_COUNT, period: str = "5d") -> pd.DataFrame:
    movers = daily_movers(tickers, period=period)
    return movers.head(n)
