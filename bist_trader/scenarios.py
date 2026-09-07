"""One-shot buy-and-hold scenario portfolios ("Senaryo 1" / "Senaryo 2").

Built exactly once, from that day's best combined signals (stocks ranked by
bist_screen's recommendation_score, funds ranked by 1-month TEFAS return),
then held untouched for config.SCENARIO_HOLD_DAYS -- no rebalancing, no
stop-loss, no new entries, nothing. The point is to see how "our best
current picks" actually perform over a week, not to keep trading them.

Completely independent of the momentum/trend strategies -- separate state
files, never touched by their scheduled logic.
"""

from __future__ import annotations

import datetime as dt
import logging

from tefas import Crawler

from . import bist_screen, config, data, lessons
from . import funds as funds_mod
from .portfolio import Portfolio

log = logging.getLogger(__name__)


def _state_file(key: str):
    return config.STATE_DIR / f"{key}_portfolio.json"


def _fund_price(code: str) -> float | None:
    try:
        crawler = Crawler()
        df = crawler.fetch(
            start=(dt.date.today() - dt.timedelta(days=7)).isoformat(),
            end=dt.date.today().isoformat(),
            name=code,
        )
    except Exception as exc:
        log.warning("fund price fetch failed for %s: %s", code, exc)
        return None
    if df.empty:
        return None
    return float(df.sort_values("date").iloc[-1]["price"])


def _current_price(ticker: str, asset_type: str) -> float | None:
    if asset_type == "fund":
        return _fund_price(ticker)
    return data.latest_price(ticker)


def _price_series(ticker: str, asset_type: str, bars: int = config.BIST_SCREEN_SPARK_BARS) -> list[float]:
    """Recent close-price series for a position's mini trend chart."""
    if asset_type == "fund":
        try:
            crawler = Crawler()
            df = crawler.fetch(
                start=(dt.date.today() - dt.timedelta(days=bars * 2)).isoformat(),
                end=dt.date.today().isoformat(),
                name=ticker,
            )
        except Exception as exc:
            log.warning("fund price series fetch failed for %s: %s", ticker, exc)
            return []
        if df.empty:
            return []
        return [round(float(v), 4) for v in df.sort_values("date")["price"].tail(bars).tolist()]

    df = data.fetch_history(ticker, period="3mo", max_age_hours=6)
    if df.empty:
        return []
    return [round(float(v), 2) for v in df["Close"].tail(bars).tolist()]


def _pick_stocks(n: int) -> list[dict]:
    """Best `n` stocks from today's BIST Ekranı, preferring anything with an
    identified driver (not 'Spekülatif') before falling back to fill slots."""
    screen = bist_screen.classify_movers()
    supported = [r for r in screen if r["label"] != "Spekülatif"]
    supported.sort(key=lambda r: r.get("recommendation_score", 0), reverse=True)
    if len(supported) < n:
        rest = [r for r in screen if r["label"] == "Spekülatif"]
        rest.sort(key=lambda r: r.get("recommendation_score", 0), reverse=True)
        supported += rest
    return supported[:n]


def _pick_funds(n: int) -> list[dict]:
    return (funds_mod.leaderboard().get("top") or [])[:n]


def _build_portfolio(key: str) -> Portfolio:
    spec = config.SCENARIOS[key]
    portfolio = Portfolio(
        cash=spec["cash"],
        max_positions=spec["max_stocks"] + spec["max_funds"],
        commission_pct=config.SCENARIO_COMMISSION_PCT,
    )

    # 100% stocks when a scenario has no fund slots (e.g. Senaryo 2) --
    # otherwise the usual stock/fund split.
    if spec["max_funds"] <= 0:
        stock_budget_total = spec["cash"]
    else:
        stock_budget_total = spec["cash"] * config.SCENARIO_STOCK_ALLOCATION_PCT
    fund_budget_total = spec["cash"] - stock_budget_total
    per_stock_budget = stock_budget_total / spec["max_stocks"] if spec["max_stocks"] else 0
    per_fund_budget = fund_budget_total / spec["max_funds"] if spec["max_funds"] else 0
    today = str(dt.date.today())

    for stock in _pick_stocks(spec["max_stocks"]):
        price = stock.get("close")
        if not price:
            continue
        yf_ticker = f"{stock['symbol']}{config.YF_SUFFIX}"
        reason = f"{stock['label']} (sinyal skoru {stock.get('recommendation_score', 0):.1f}) -- {(stock.get('narrative') or '')[:220]}"
        ok = portfolio.open_position(yf_ticker, price, today, spec["cash"], reason=reason,
                                      asset_type="stock", budget_override=per_stock_budget)
        if not ok:
            log.warning("[%s] could not open stock position %s (price=%.2f, budget=%.2f, cash=%.2f)",
                        key, yf_ticker, price, per_stock_budget, portfolio.cash)

    for fnd in _pick_funds(spec["max_funds"]):
        price = _fund_price(fnd["code"])
        if not price:
            continue
        reason = f"Fon lider tablosu, 1 Ay {fnd.get('getiri1a', 0):+.1f}% -- {(fnd.get('reason') or '')[:220]}"
        ok = portfolio.open_position(fnd["code"], price, today, spec["cash"], reason=reason,
                                      asset_type="fund", budget_override=per_fund_budget)
        if not ok:
            log.warning("[%s] could not open fund position %s (price=%.2f, budget=%.2f, cash=%.2f)",
                        key, fnd["code"], price, per_fund_budget, portfolio.cash)

    portfolio.mark_to_market({t: p.entry_price for t, p in portfolio.positions.items()}, today)
    return portfolio


def refresh(key: str) -> Portfolio:
    """Load the scenario (building it once if it doesn't exist yet), refresh
    every position's current price, save, return."""
    path = _state_file(key)
    if path.exists():
        portfolio = Portfolio.load(path)
    else:
        log.info("Building scenario %s for the first time", key)
        portfolio = _build_portfolio(key)

    today = str(dt.date.today())
    prices = {}
    for ticker, pos in portfolio.positions.items():
        price = _current_price(ticker, pos.asset_type)
        if price:
            prices[ticker] = price
    portfolio.mark_to_market(prices, today)
    portfolio.save(path)
    return portfolio, prices


def snapshot(key: str) -> dict:
    spec = config.SCENARIOS[key]
    portfolio, prices = refresh(key)

    positions = []
    positions_value = 0.0
    for ticker, pos in portfolio.positions.items():
        current = prices.get(ticker, pos.entry_price)
        value = current * pos.qty
        cost = pos.entry_price * pos.qty
        positions_value += value
        positions.append({
            "ticker": ticker,
            "asset_type": pos.asset_type,
            "entry_date": pos.entry_date,
            "entry_price": pos.entry_price,
            "current_price": current,
            "qty": pos.qty,
            "value": value,
            "unrealized_pnl": value - cost,
            "unrealized_pnl_pct": (current / pos.entry_price - 1) * 100 if pos.entry_price else 0.0,
            "reason": pos.reason,
            "spark": _price_series(ticker, pos.asset_type),
        })

    equity = portfolio.cash + positions_value
    start_date_str = portfolio.equity_curve[0]["date"] if portfolio.equity_curve else str(dt.date.today())
    start_date = dt.date.fromisoformat(start_date_str)
    days_elapsed = (dt.date.today() - start_date).days
    days_remaining = max(0, config.SCENARIO_HOLD_DAYS - days_elapsed)

    snap = {
        "key": key,
        "label": spec["label"],
        "initial_cash": portfolio.initial_cash,
        "cash": portfolio.cash,
        "equity": equity,
        "positions_value": positions_value,
        "total_return_pct": (equity / portfolio.initial_cash - 1) * 100 if portfolio.initial_cash else 0.0,
        "stock_allocation_pct": 100.0 if spec["max_funds"] <= 0 else config.SCENARIO_STOCK_ALLOCATION_PCT * 100,
        "max_funds": spec["max_funds"],
        "start_date": start_date_str,
        "hold_days": config.SCENARIO_HOLD_DAYS,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "hold_complete": days_elapsed >= config.SCENARIO_HOLD_DAYS,
        "positions": sorted(positions, key=lambda p: p["value"], reverse=True),
        "equity_curve": portfolio.equity_curve,
    }
    try:
        snap["lessons"] = lessons.buyhold_lessons(snap)
    except Exception:
        log.exception("Lessons-learned generation failed for scenario %s (non-fatal).", key)
        snap["lessons"] = {"recent": [], "aggregate_notes": [], "closed_count": 0}
    return snap


def all_snapshots() -> dict:
    return {key: snapshot(key) for key in config.SCENARIOS}
