"""Virtual (paper) portfolio: cash, open positions, trade log, equity curve.

No real broker or money is touched anywhere in this module -- it only
simulates fills at the given price and tracks P&L in memory / on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from . import config


@dataclass
class Position:
    ticker: str
    qty: float
    entry_price: float
    entry_date: str
    asset_type: str = "stock"  # "stock" or "fund" -- lets one Portfolio hold both
    reason: str = ""  # why this was picked, for buy-and-hold scenarios with no separate trade log


@dataclass
class Trade:
    ticker: str
    side: str  # "BUY" or "SELL"
    qty: float
    price: float
    date: str
    reason: str
    pnl: float | None = None


class Portfolio:
    """A virtual (paper) portfolio.

    Sizing/risk knobs default to the bist_trader.config globals but can be
    overridden per instance -- e.g. the momentum/KAP strategy runs its own
    Portfolio with a smaller cash balance, a max of 3 positions, and its own
    stop-loss/take-profit, independent of the trend-following strategy's
    portfolio.
    """

    def __init__(
        self,
        cash: float = config.INITIAL_CASH,
        max_positions: int | None = None,
        position_size_pct: float | None = None,
        commission_pct: float | None = None,
        min_cash_buffer_pct: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ):
        self.initial_cash = cash
        self.cash = cash
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []  # [{date, equity}]

        self.max_positions = max_positions if max_positions is not None else config.MAX_OPEN_POSITIONS
        self.position_size_pct = position_size_pct if position_size_pct is not None else config.POSITION_SIZE_PCT
        self.commission_pct = commission_pct if commission_pct is not None else config.COMMISSION_PCT
        self.min_cash_buffer_pct = min_cash_buffer_pct if min_cash_buffer_pct is not None else config.MIN_CASH_BUFFER_PCT
        self.stop_loss_pct = stop_loss_pct if stop_loss_pct is not None else config.STOP_LOSS_PCT
        self.take_profit_pct = take_profit_pct if take_profit_pct is not None else config.TAKE_PROFIT_PCT

    # ---- sizing / capacity ----

    def open_slots(self) -> int:
        return max(0, self.max_positions - len(self.positions))

    def target_position_value(self, equity: float) -> float:
        return equity * self.position_size_pct

    # ---- trading ----

    def open_position(
        self, ticker: str, price: float, date: str, equity: float,
        reason: str = "entry_signal", asset_type: str = "stock", budget_override: float | None = None,
    ) -> bool:
        if ticker in self.positions or self.open_slots() <= 0 or price <= 0:
            return False
        target = budget_override if budget_override is not None else self.target_position_value(equity)
        budget = min(target, self.cash * (1 - self.min_cash_buffer_pct))
        qty = int(budget // price)
        if qty <= 0:
            return False
        cost = qty * price
        commission = cost * self.commission_pct
        if cost + commission > self.cash:
            return False
        self.cash -= cost + commission
        self.positions[ticker] = Position(ticker=ticker, qty=qty, entry_price=price, entry_date=date,
                                           asset_type=asset_type, reason=reason)
        self.trades.append(Trade(ticker=ticker, side="BUY", qty=qty, price=price, date=date, reason=reason))
        return True

    def close_position(self, ticker: str, price: float, date: str, reason: str) -> bool:
        pos = self.positions.get(ticker)
        if pos is None or price <= 0:
            return False
        proceeds = pos.qty * price
        commission = proceeds * self.commission_pct
        self.cash += proceeds - commission
        pnl = (price - pos.entry_price) * pos.qty - commission
        self.trades.append(Trade(ticker=ticker, side="SELL", qty=pos.qty, price=price, date=date, reason=reason, pnl=pnl))
        del self.positions[ticker]
        return True

    def check_stop_take(self, ticker: str, price: float) -> str | None:
        pos = self.positions.get(ticker)
        if pos is None:
            return None
        change = (price - pos.entry_price) / pos.entry_price
        if change <= -self.stop_loss_pct:
            return "stop_loss"
        if change >= self.take_profit_pct:
            return "take_profit"
        return None

    # ---- accounting ----

    def mark_to_market(self, prices: dict[str, float], date: str) -> float:
        equity = self.cash + sum(
            prices.get(t, pos.entry_price) * pos.qty for t, pos in self.positions.items()
        )
        self.equity_curve.append({"date": date, "equity": equity})
        return equity

    # ---- persistence (for the paper trader, across restarts) ----

    def to_dict(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "max_positions": self.max_positions,
            "position_size_pct": self.position_size_pct,
            "commission_pct": self.commission_pct,
            "min_cash_buffer_pct": self.min_cash_buffer_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "trades": [asdict(t) for t in self.trades],
            "equity_curve": self.equity_curve,
        }

    @classmethod
    def from_dict(cls, d: dict, **overrides) -> "Portfolio":
        """Rebuild a Portfolio from a saved dict. Explicit `overrides` (e.g. a
        strategy re-asserting its own max_positions) win over the saved values,
        so config changes between runs still take effect."""
        sizing = {
            "max_positions": d.get("max_positions"),
            "position_size_pct": d.get("position_size_pct"),
            "commission_pct": d.get("commission_pct"),
            "min_cash_buffer_pct": d.get("min_cash_buffer_pct"),
            "stop_loss_pct": d.get("stop_loss_pct"),
            "take_profit_pct": d.get("take_profit_pct"),
        }
        sizing.update({k: v for k, v in overrides.items() if v is not None})
        p = cls(cash=d.get("initial_cash", config.INITIAL_CASH), **sizing)
        p.cash = d["cash"]
        p.positions = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        p.trades = [Trade(**t) for t in d.get("trades", [])]
        p.equity_curve = d.get("equity_curve", [])
        return p

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path, **overrides) -> "Portfolio":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f), **overrides)
