"""Momentum/KAP paper trading loop.

Separate strategy from paper_trader.py's trend-following one: chases
today's biggest gainers / near-the-daily-limit stocks, but only commits
virtual cash to a candidate that clears a checklist (see momentum.py):
technical entry point + high volume mandatory, plus at least
config.MOMENTUM_MIN_SUPPORT_CHECKS of {KAP support, balance-sheet support}.

Own virtual portfolio (config.MOMENTUM_INITIAL_CASH, default 10,000 TL;
config.MOMENTUM_MAX_POSITIONS, default 3), own state file, own trade log.
Still 100% paper trading -- no real order is ever sent.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

from . import config, data, kap, momentum, screener, tickers as tickers_mod
from .portfolio import Portfolio

log = logging.getLogger(__name__)

STATE_FILE = config.STATE_DIR / "momentum_portfolio.json"
TRADE_LOG_FILE = config.LOG_DIR / "momentum_trades.csv"

# Candidates need enough history for SLOW_MA + a volume lookback window.
CANDIDATE_FETCH_PERIOD = "6mo"

_PORTFOLIO_KWARGS = dict(
    max_positions=config.MOMENTUM_MAX_POSITIONS,
    position_size_pct=config.MOMENTUM_POSITION_SIZE_PCT,
    commission_pct=config.MOMENTUM_COMMISSION_PCT,
    min_cash_buffer_pct=config.MOMENTUM_MIN_CASH_BUFFER_PCT,
    stop_loss_pct=config.MOMENTUM_STOP_LOSS_PCT,
    take_profit_pct=config.MOMENTUM_TAKE_PROFIT_PCT,
)


def _setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_DIR / "momentum_trading.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load_or_create_portfolio() -> Portfolio:
    if STATE_FILE.exists():
        log.info("Loading existing momentum portfolio from %s", STATE_FILE)
        return Portfolio.load(STATE_FILE, **_PORTFOLIO_KWARGS)
    log.info("No saved momentum portfolio found, starting fresh with %.2f TL / max %d positions",
              config.MOMENTUM_INITIAL_CASH, config.MOMENTUM_MAX_POSITIONS)
    return Portfolio(cash=config.MOMENTUM_INITIAL_CASH, **_PORTFOLIO_KWARGS)


def _log_trade_csv(trade, trade_log_file, ev: "momentum.CandidateEvaluation | None" = None) -> None:
    is_new = not trade_log_file.exists()
    with open(trade_log_file, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["date", "ticker", "side", "qty", "price", "reason", "pnl",
                        "technical", "volume_high", "kap_support", "kap_reasons", "financials_support",
                        "adx_strong", "donchian_breakout", "score"])
        if ev:
            w.writerow([trade.date, trade.ticker, trade.side, trade.qty, trade.price, trade.reason, trade.pnl,
                        ev.technical_buy_point, ev.volume_high, ev.kap_support, "; ".join(ev.kap_reasons),
                        ev.financials_support, ev.adx_strong, ev.donchian_breakout, f"{ev.score:.2f}"])
        else:
            w.writerow([trade.date, trade.ticker, trade.side, trade.qty, trade.price, trade.reason, trade.pnl,
                        "", "", "", "", "", "", "", ""])


def is_market_open(now: dt.datetime | None = None) -> bool:
    tz = ZoneInfo(config.MARKET_TZ)
    now = (now or dt.datetime.now(tz)).astimezone(tz)
    if now.weekday() >= 5:
        return False
    open_h, open_m = map(int, config.MARKET_OPEN.split(":"))
    close_h, close_m = map(int, config.MARKET_CLOSE.split(":"))
    open_t = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_t = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return open_t <= now <= close_t


def _exit_reason(ticker: str, portfolio: Portfolio, df) -> str | None:
    price = float(df["Close"].iloc[-1])
    reason = portfolio.check_stop_take(ticker, price)
    if reason:
        return reason

    from . import strategy
    ind = strategy.compute_indicators(df)
    last = ind.iloc[-1]
    if not (last[["fast_ma", "rsi"]].isna().any()):
        if last["rsi"] < config.MOMENTUM_EXIT_RSI_BELOW:
            return "momentum_fading_rsi"
        if last["Close"] < last["fast_ma"]:
            return "momentum_fading_below_ma"
    return None


def run_cycle(
    portfolio: Portfolio,
    state_file,
    trade_log_file,
    tag: str = "MOMENTUM",
    universe: list[str] | None = None,
) -> Portfolio:
    """The actual checklist-driven trading engine: scan, evaluate, exit,
    enter, mark-to-market, save. Reusable across any number of independently
    capitalized portfolios (the momentum strategy's own, Senaryo 3, ...) --
    `tag` just labels log lines and the trade reason string so it's obvious
    which portfolio did what."""
    yf_tickers = universe or tickers_mod.load_yfinance_universe()
    raw_symbols = {t.replace(config.YF_SUFFIX, "") for t in yf_tickers}

    log.info("[%s] Scanning %d tickers for daily movers...", tag, len(yf_tickers))
    movers = screener.daily_movers(yf_tickers)
    if movers.empty:
        log.warning("[%s] No mover data this cycle; skipping.", tag)
        return portfolio
    date_str = movers["date"].iloc[0]

    kap_df = kap.scan_recent(days=config.MOMENTUM_KAP_LOOKBACK_DAYS, known_tickers=raw_symbols)
    kap_by_symbol: dict[str, list[dict]] = {}
    for _, row in kap_df.iterrows():
        kap_by_symbol.setdefault(row["ticker"], []).append(row.to_dict())

    # 1) exits: stop-loss / take-profit / fading momentum
    for ticker in list(portfolio.positions.keys()):
        df = data.fetch_history(ticker, period=CANDIDATE_FETCH_PERIOD, interval="1d", max_age_hours=1)
        if df.empty:
            continue
        reason = _exit_reason(ticker, portfolio, df)
        if reason:
            price = float(df["Close"].iloc[-1])
            portfolio.close_position(ticker, price, date_str, reason)
            _log_trade_csv(portfolio.trades[-1], trade_log_file)
            log.info("[%s] SELL %s qty=%s price=%.2f reason=%s",
                      tag, ticker, portfolio.trades[-1].qty, price, reason)

    # 2) entries: rank candidates by checklist score, fill open slots
    if portfolio.open_slots() > 0:
        candidate_rows = movers[(movers["near_limit"]) | (movers["in_top_gainers"])]
        candidate_rows = candidate_rows[~candidate_rows["ticker"].isin(portfolio.positions.keys())]

        evaluations = []
        for _, row in candidate_rows.iterrows():
            yf_t = row["ticker"]
            symbol = yf_t.replace(config.YF_SUFFIX, "")
            df = data.fetch_history(yf_t, period=CANDIDATE_FETCH_PERIOD, interval="1d", max_age_hours=1)
            if df.empty:
                continue
            ev = momentum.evaluate_candidate(yf_t, df, kap_flags=kap_by_symbol.get(symbol))
            log.info(
                "[%s] Candidate %s: pct_change=%.2f%% technical=%s volume=%s kap=%s financials=%s score=%.2f -> %s",
                tag, yf_t, row["pct_change"], ev.technical_buy_point, ev.volume_high,
                ev.kap_support, ev.financials_support, ev.score, "PASS" if ev.passes else "skip",
            )
            if ev.passes:
                evaluations.append((ev, df))

        evaluations.sort(key=lambda pair: pair[0].score, reverse=True)

        equity_now = portfolio.cash
        for t, pos in portfolio.positions.items():
            held_df = data.fetch_history(t, period="5d", max_age_hours=6)
            price = float(held_df["Close"].iloc[-1]) if not held_df.empty else pos.entry_price
            equity_now += price * pos.qty

        for ev, df in evaluations:
            if portfolio.open_slots() <= 0:
                break
            price = float(df["Close"].iloc[-1])
            reason = f"{tag.lower()}_checklist(score={ev.score:.1f}, kap={ev.kap_support}, fin={ev.financials_support})"
            if portfolio.open_position(ev.ticker, price, date_str, equity_now, reason=reason):
                _log_trade_csv(portfolio.trades[-1], trade_log_file, ev)
                log.info("[%s] BUY  %s qty=%s price=%.2f score=%.2f kap=%s financials=%s",
                          tag, ev.ticker, portfolio.trades[-1].qty, price, ev.score, ev.kap_reasons, ev.financials_support)

    # 3) mark to market
    closes = {}
    for t in portfolio.positions:
        df = data.fetch_history(t, period="5d", max_age_hours=6)
        if not df.empty:
            closes[t] = float(df["Close"].iloc[-1])
    equity = portfolio.mark_to_market(closes, date_str)
    log.info("[%s] Cycle done. Equity=%.2f TL | Cash=%.2f | Open positions=%d/%d",
              tag, equity, portfolio.cash, len(portfolio.positions), portfolio.max_positions)
    portfolio.save(state_file)
    return portfolio


def run_once(portfolio: Portfolio, universe: list[str] | None = None) -> Portfolio:
    portfolio = run_cycle(portfolio, STATE_FILE, TRADE_LOG_FILE, tag="MOMENTUM", universe=universe)

    try:
        from . import dashboard
        dashboard.write_snapshot()
    except Exception:
        log.exception("Dashboard snapshot refresh failed (non-fatal).")

    return portfolio


def run_loop(poll_seconds: int = 3600) -> None:
    """Momentum scanning is heavier (full-universe daily-mover scan, plus the
    BIST Ekranı/Fonlar/Haberler dashboard data) than the trend strategy's
    loop -- default to an hourly poll to avoid hammering Yahoo Finance/KAP
    with hundreds of requests too often. Matches the Windows Scheduled Task's
    own hourly repetition (this loop mode is only used if you run the script
    directly instead of via Task Scheduler)."""
    _setup_logging()
    portfolio = _load_or_create_portfolio()
    log.info("Starting momentum/KAP paper trading loop (Ctrl+C to stop).")
    try:
        while True:
            if is_market_open():
                try:
                    portfolio = run_once(portfolio)
                except Exception:
                    log.exception("Error during momentum cycle; will retry next poll.")
                time.sleep(poll_seconds)
            else:
                log.info("Market closed (%s). Sleeping 15 min.", config.MARKET_TZ)
                time.sleep(900)
    except KeyboardInterrupt:
        log.info("Stopped by user. Final state saved to %s", STATE_FILE)
        portfolio.save(STATE_FILE)
