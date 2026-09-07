"""Vectorized-ish daily backtest over the BIST100 universe.

Walks the calendar day by day: exits (stop-loss / take-profit / signal)
are processed before entries, then the portfolio is marked to market.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config, data, strategy, tickers as tickers_mod
from .portfolio import Portfolio

log = logging.getLogger(__name__)


def run_backtest(
    symbols: list[str] | None = None,
    period: str = f"{config.BACKTEST_LOOKBACK_YEARS}y",
    interval: str = config.BACKTEST_INTERVAL,
    initial_cash: float = config.INITIAL_CASH,
) -> tuple[Portfolio, dict, pd.DataFrame]:
    """Fetch data for `symbols` (or the full BIST100 universe) and simulate."""
    yf_tickers = symbols or tickers_mod.load_yfinance_universe()
    raw = data.fetch_universe(yf_tickers, period=period, interval=interval)
    if not raw:
        raise RuntimeError("No usable price data fetched for any ticker.")
    return simulate(raw, initial_cash=initial_cash)


def simulate(
    raw: dict[str, pd.DataFrame],
    initial_cash: float = config.INITIAL_CASH,
) -> tuple[Portfolio, dict, pd.DataFrame]:
    """Run the strategy + portfolio simulation over already-fetched raw OHLCV data.

    Re-reads strategy/risk parameters from `config` on every call, so callers
    (e.g. a parameter sweep) can mutate `config.FAST_MA` etc. between calls
    without re-fetching data.
    """
    indicators = {t: strategy.compute_indicators(df) for t, df in raw.items()}

    all_dates = sorted(set().union(*(df.index for df in indicators.values())))
    portfolio = Portfolio(cash=initial_cash)

    for date in all_dates:
        date_str = str(date.date()) if hasattr(date, "date") else str(date)

        closes: dict[str, float] = {}
        for t, df in indicators.items():
            if date in df.index and not np.isnan(df.loc[date, "Close"]):
                closes[t] = float(df.loc[date, "Close"])

        # 1) exits: stop-loss / take-profit / strategy exit signal
        for t in list(portfolio.positions.keys()):
            price = closes.get(t)
            if price is None:
                continue
            reason = portfolio.check_stop_take(t, price)
            if reason is None and date in indicators[t].index and bool(indicators[t].loc[date, "exit_signal"]):
                reason = "exit_signal"
            if reason:
                portfolio.close_position(t, price, date_str, reason)

        # 2) entries: only if we have free slots
        if portfolio.open_slots() > 0:
            equity_now = portfolio.cash + sum(
                closes.get(t, p.entry_price) * p.qty for t, p in portfolio.positions.items()
            )
            candidates = [
                t for t, df in indicators.items()
                if t not in portfolio.positions
                and date in df.index
                and bool(df.loc[date, "entry_signal"])
                and t in closes
            ]
            for t in candidates:
                if portfolio.open_slots() <= 0:
                    break
                portfolio.open_position(t, closes[t], date_str, equity_now)

        # 3) mark to market
        if closes:
            portfolio.mark_to_market(closes, date_str)

    metrics = compute_metrics(portfolio)
    equity_df = pd.DataFrame(portfolio.equity_curve)
    return portfolio, metrics, equity_df


def compute_metrics(portfolio: Portfolio) -> dict:
    if not portfolio.equity_curve:
        return {}
    eq = pd.DataFrame(portfolio.equity_curve)
    eq["date"] = pd.to_datetime(eq["date"])
    eq = eq.set_index("date").sort_index()
    returns = eq["equity"].pct_change().dropna()

    start_eq = portfolio.initial_cash
    end_eq = eq["equity"].iloc[-1]
    total_return = end_eq / start_eq - 1

    n_days = (eq.index[-1] - eq.index[0]).days or 1
    years = n_days / 365.25
    cagr = (end_eq / start_eq) ** (1 / years) - 1 if years > 0 and end_eq > 0 else float("nan")

    sharpe = float("nan")
    if returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

    running_max = eq["equity"].cummax()
    drawdown = eq["equity"] / running_max - 1
    max_drawdown = drawdown.min()

    closed = [t for t in portfolio.trades if t.side == "SELL" and t.pnl is not None]
    wins = [t for t in closed if t.pnl > 0]
    win_rate = len(wins) / len(closed) if closed else float("nan")

    calmar = (cagr / abs(max_drawdown)) if max_drawdown < 0 else float("nan")

    return {
        "start_equity": start_eq,
        "end_equity": end_eq,
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown * 100,
        "calmar": calmar,
        "num_trades": len(closed),
        "win_rate_pct": win_rate * 100,
    }


def print_report(metrics: dict) -> None:
    if not metrics:
        print("No trades / no equity curve produced.")
        return
    print("=== Backtest Report ===")
    print(f"Start equity     : {metrics['start_equity']:,.2f} TL")
    print(f"End equity       : {metrics['end_equity']:,.2f} TL")
    print(f"Total return     : {metrics['total_return_pct']:.2f}%")
    print(f"CAGR             : {metrics['cagr_pct']:.2f}%")
    print(f"Sharpe (approx)  : {metrics['sharpe']:.2f}")
    print(f"Max drawdown     : {metrics['max_drawdown_pct']:.2f}%")
    print(f"Calmar (CAGR/DD) : {metrics['calmar']:.2f}")
    print(f"Closed trades    : {metrics['num_trades']}")
    print(f"Win rate         : {metrics['win_rate_pct']:.2f}%")
