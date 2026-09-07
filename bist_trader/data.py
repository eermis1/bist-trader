"""Price data access via yfinance, with a simple on-disk cache.

Yahoo Finance data for .IS tickers is typically end-of-day / delayed by
~15-20 minutes -- fine for backtesting and paper-trading simulation,
not suitable as a live execution feed for real order routing.
"""

import datetime as dt
import json
import logging

import pandas as pd
import yfinance as yf

from . import config

log = logging.getLogger(__name__)


def _cache_path(ticker: str, interval: str, period: str) -> "config.Path":
    # `period` MUST be part of the key: a short-period fetch (e.g. screener's
    # "5d") and a long-period fetch (e.g. "6mo") for the same ticker+interval
    # used to share one cache file, so whichever ran most recently silently
    # served its (possibly too-short) row count to the other caller -- e.g.
    # a "5d" scan running right before a "6mo" indicator fetch would leave
    # technical_buy_point/volume_detail computing off 5 rows instead of 6
    # months, with no error, just quietly-wrong signals.
    safe = ticker.replace(".", "_")
    return config.CACHE_DIR / f"{safe}_{interval}_{period}.csv"


def _nodata_path(ticker: str, interval: str, period: str) -> "config.Path":
    safe = ticker.replace(".", "_")
    return config.CACHE_DIR / f"{safe}_{interval}_{period}.nodata"


def fetch_history(
    ticker: str,
    period: str = "3y",
    interval: str = "1d",
    use_cache: bool = True,
    max_age_hours: int = 12,
) -> pd.DataFrame:
    """Fetch OHLCV history for a single yfinance ticker (e.g. 'THYAO.IS').

    Returns a DataFrame indexed by date with columns Open/High/Low/Close/Volume.
    Empty DataFrame on failure (network issue, delisted symbol, etc). Failures
    are negative-cached too (as a .nodata marker) so a universe with lots of
    illiquid/delisted/fund tickers -- e.g. the full "all BIST" list -- doesn't
    re-hit the network for the same dead tickers on every run.
    """
    cache_file = _cache_path(ticker, interval, period)
    nodata_file = _nodata_path(ticker, interval, period)

    if use_cache and cache_file.exists():
        age_hours = (dt.datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                if not df.empty:
                    return df
            except Exception:
                pass

    if use_cache and max_age_hours > 0 and nodata_file.exists():
        age_hours = (dt.datetime.now().timestamp() - nodata_file.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            return pd.DataFrame()

    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    except Exception as exc:
        log.warning("fetch failed for %s: %s", ticker, exc)
        if use_cache:
            nodata_file.touch()
        return pd.DataFrame()

    if df.empty:
        log.warning("no data returned for %s", ticker)
        if use_cache:
            nodata_file.touch()
        return df

    if use_cache and nodata_file.exists():
        nodata_file.unlink(missing_ok=True)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index.name = "Date"

    if use_cache:
        try:
            df.to_csv(cache_file)
        except Exception as exc:
            log.warning("cache write failed for %s: %s", ticker, exc)

    return df


def fetch_universe(
    tickers: list[str],
    period: str = "3y",
    interval: str = "1d",
    use_cache: bool = True,
) -> dict[str, pd.DataFrame]:
    """Fetch history for many tickers, skipping ones with no usable data."""
    out: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(tickers, 1):
        df = fetch_history(t, period=period, interval=interval, use_cache=use_cache)
        if not df.empty and len(df) > max(config.SLOW_MA, config.RSI_PERIOD) + 5:
            out[t] = df
        log.info("[%d/%d] %s -> %d bars", i, len(tickers), t, len(df))
    return out


def latest_price(ticker: str) -> float | None:
    """Best-effort latest close for a ticker (used by the paper trader)."""
    df = fetch_history(ticker, period="5d", interval="1d", use_cache=True, max_age_hours=0)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def _info_cache_path(ticker: str) -> "config.Path":
    safe = ticker.replace(".", "_")
    return config.CACHE_DIR / f"{safe}_info.json"


def get_company_info(ticker: str, max_age_days: int = 30) -> dict:
    """Company name/sector/industry/description -- changes rarely, so cached
    for `max_age_days` (much longer than the price cache) to avoid an extra
    yfinance call every scan for tickers we've already looked up."""
    cache_file = _info_cache_path(ticker)
    if cache_file.exists():
        age_days = (dt.datetime.now().timestamp() - cache_file.stat().st_mtime) / 86400
        if age_days < max_age_days:
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    try:
        raw = yf.Ticker(ticker).get_info()
    except Exception as exc:
        log.warning("company info fetch failed for %s: %s", ticker, exc)
        return {}

    info = {
        "name": raw.get("longName") or raw.get("shortName"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "summary": raw.get("longBusinessSummary"),
    }
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
    except Exception as exc:
        log.warning("company info cache write failed for %s: %s", ticker, exc)
    return info
