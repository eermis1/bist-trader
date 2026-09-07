"""Simple trend-following strategy: MA crossover confirmed by RSI momentum.

Entry: fast SMA crosses above slow SMA AND RSI > RSI_BUY_MIN
Exit:  fast SMA crosses below slow SMA OR RSI < RSI_SELL_MAX
       (stop-loss / take-profit are applied separately, against the
       actual entry price, by the portfolio/backtest engine)

This is intentionally simple and easy to reason about. Swap this module
out (or add more signals) once you want something more sophisticated --
the rest of the system only depends on compute_indicators()'s output
columns: 'fast_ma', 'slow_ma', 'rsi', 'entry_signal', 'exit_signal'.
"""

import pandas as pd

from . import config


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA/RSI/signal columns to an OHLCV DataFrame. Returns a copy."""
    out = df.copy()
    out["fast_ma"] = out["Close"].rolling(config.FAST_MA).mean()
    out["slow_ma"] = out["Close"].rolling(config.SLOW_MA).mean()
    out["rsi"] = _rsi(out["Close"], config.RSI_PERIOD)

    above = out["fast_ma"] > out["slow_ma"]
    crossed_up = above & ~above.shift(1, fill_value=False)
    crossed_down = ~above & above.shift(1, fill_value=False)

    out["entry_signal"] = crossed_up & (out["rsi"] > config.RSI_BUY_MIN)
    out["exit_signal"] = crossed_down | (out["rsi"] < config.RSI_SELL_MAX)

    return out
