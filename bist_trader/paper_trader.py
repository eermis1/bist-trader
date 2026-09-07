"""Paper trading loop: simulates the strategy against near-live prices.

This NEVER sends a real order anywhere -- it only fetches quotes (delayed,
via yfinance) and updates a virtual Portfolio persisted to
data/state/portfolio.json. Safe to run continuously.

To later wire this to a real broker (e.g. AlgoLab for Deniz Yatirim),
add an execution.py that implements place_order(ticker, side, qty) against
the broker's API, call it from _apply_exit / _apply_entry below *in
addition to* the paper fill, and gate it behind an explicit config flag
and your own manual confirmation step -- do not flip that on blindly.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

from . import config, data, strategy, tickers as tickers_mod
from .portfolio import Portfolio

log = logging.getLogger(__name__)

STATE_FILE = config.STATE_DIR / "portfolio.json"
TRADE_LOG_FILE = config.LOG_DIR / "trades.csv"


def _setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_DIR / "paper_trading.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load_or_create_portfolio() -> Portfolio:
    if STATE_FILE.exists():
        log.info("Loading existing paper portfolio from %s", STATE_FILE)
        return Portfolio.load(STATE_FILE)
    log.info("No saved portfolio found, starting fresh with %.2f TL", config.INITIAL_CASH)
    return Portfolio(cash=config.INITIAL_CASH)


def _log_trade_csv(trade) -> None:
    is_new = not TRADE_LOG_FILE.exists()
    with open(TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["date", "ticker", "side", "qty", "price", "reason", "pnl"])
        w.writerow([trade.date, trade.ticker, trade.side, trade.qty, trade.price, trade.reason, trade.pnl])


def is_market_open(now: dt.datetime | None = None) -> bool:
    tz = ZoneInfo(config.MARKET_TZ)
    now = (now or dt.datetime.now(tz)).astimezone(tz)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    open_h, open_m = map(int, config.MARKET_OPEN.split(":"))
    close_h, close_m = map(int, config.MARKET_CLOSE.split(":"))
    open_t = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_t = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return open_t <= now <= close_t


def run_once(portfolio: Portfolio, universe: list[str] | None = None) -> Portfolio:
    """Fetch latest data, evaluate signals once, update the paper portfolio."""
    yf_tickers = universe or tickers_mod.load_yfinance_universe()
    raw = data.fetch_universe(yf_tickers, period="1y", interval=config.PAPER_INTERVAL)
    if not raw:
        log.warning("No data fetched this cycle; skipping.")
        return portfolio

    indicators = {t: strategy.compute_indicators(df) for t, df in raw.items()}
    latest_date = max(df.index[-1] for df in indicators.values())
    date_str = str(latest_date.date()) if hasattr(latest_date, "date") else str(latest_date)

    closes = {t: float(df["Close"].iloc[-1]) for t, df in indicators.items()}

    # 1) exits
    for t in list(portfolio.positions.keys()):
        price = closes.get(t)
        if price is None:
            continue
        reason = portfolio.check_stop_take(t, price)
        df = indicators.get(t)
        if reason is None and df is not None and bool(df["exit_signal"].iloc[-1]):
            reason = "exit_signal"
        if reason:
            portfolio.close_position(t, price, date_str, reason)
            _log_trade_csv(portfolio.trades[-1])
            log.info("PAPER SELL %s qty=%s price=%.2f reason=%s", t, portfolio.trades[-1].qty, price, reason)

    # 2) entries
    if portfolio.open_slots() > 0:
        equity_now = portfolio.cash + sum(
            closes.get(t, p.entry_price) * p.qty for t, p in portfolio.positions.items()
        )
        candidates = [
            t for t, df in indicators.items()
            if t not in portfolio.positions and bool(df["entry_signal"].iloc[-1]) and t in closes
        ]
        for t in candidates:
            if portfolio.open_slots() <= 0:
                break
            if portfolio.open_position(t, closes[t], date_str, equity_now):
                _log_trade_csv(portfolio.trades[-1])
                log.info("PAPER BUY  %s qty=%s price=%.2f", t, portfolio.trades[-1].qty, closes[t])

    equity = portfolio.mark_to_market(closes, date_str)
    log.info(
        "Cycle done. Equity=%.2f TL | Cash=%.2f | Open positions=%d",
        equity, portfolio.cash, len(portfolio.positions),
    )
    portfolio.save(STATE_FILE)

    try:
        from . import dashboard
        dashboard.write_snapshot()
    except Exception:
        log.exception("Dashboard snapshot refresh failed (non-fatal).")

    return portfolio


def run_loop(poll_seconds: int = config.POLL_SECONDS) -> None:
    _setup_logging()
    portfolio = _load_or_create_portfolio()
    log.info("Starting BIST100 paper trading loop (Ctrl+C to stop).")
    try:
        while True:
            if is_market_open():
                try:
                    portfolio = run_once(portfolio)
                except Exception:
                    log.exception("Error during trading cycle; will retry next poll.")
                time.sleep(poll_seconds)
            else:
                log.info("Market closed (%s). Sleeping 15 min.", config.MARKET_TZ)
                time.sleep(900)
    except KeyboardInterrupt:
        log.info("Stopped by user. Final state saved to %s", STATE_FILE)
        portfolio.save(STATE_FILE)
