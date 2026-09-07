"""Senaryo 3: the "yaşayan" (living/actively-managed) scenario portfolio.

Unlike Senaryo 1/2 (one-shot buy-and-hold, see scenarios.py), this one keeps
trading: same engine as the momentum strategy (momentum_trader.run_cycle --
technical/volume/KAP/financials/ADX/Donchian checklist for entries,
stop-loss/take-profit/fading-momentum for exits), but its own capital and
its own fully independent state file. Stocks only. Runs every hourly
dashboard cycle, same cadence as the momentum strategy's own portfolio.
"""

from __future__ import annotations

import logging

from . import config, momentum_trader
from .portfolio import Portfolio

log = logging.getLogger(__name__)

STATE_FILE = config.STATE_DIR / "scenario3_portfolio.json"
TRADE_LOG_FILE = config.LOG_DIR / "scenario3_trades.csv"

_PORTFOLIO_KWARGS = dict(
    max_positions=config.SCENARIO3_MAX_POSITIONS,
    position_size_pct=1.0 / config.SCENARIO3_MAX_POSITIONS,
    commission_pct=config.COMMISSION_PCT,
    min_cash_buffer_pct=config.MIN_CASH_BUFFER_PCT,
    stop_loss_pct=config.MOMENTUM_STOP_LOSS_PCT,
    take_profit_pct=config.MOMENTUM_TAKE_PROFIT_PCT,
)


def _load_or_create_portfolio() -> Portfolio:
    if STATE_FILE.exists():
        return Portfolio.load(STATE_FILE, **_PORTFOLIO_KWARGS)
    log.info("Building Senaryo 3 for the first time with %.2f TL / max %d positions",
              config.SCENARIO3_CASH, config.SCENARIO3_MAX_POSITIONS)
    return Portfolio(cash=config.SCENARIO3_CASH, **_PORTFOLIO_KWARGS)


def run_once() -> Portfolio:
    portfolio = _load_or_create_portfolio()
    return momentum_trader.run_cycle(portfolio, STATE_FILE, TRADE_LOG_FILE, tag="SENARYO3")
