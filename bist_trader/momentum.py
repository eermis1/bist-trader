"""Checklist for the momentum/KAP paper-trading strategy.

For a candidate that's already spiking (top gainer / near the daily limit),
decide whether the move looks "real" enough to commit virtual cash to,
using four checks:

  1. kap_support        -- a recent high-priority KAP disclosure for this
                            ticker (ownership-threshold crossing, unusual
                            price/volume flag, merger, tender offer, ...).
  2. financials_support  -- latest reported quarter profitable, or net
                            income improving q/q without revenue collapsing.
  3. volume_high         -- today's volume is a clear multiple of its own
                            recent average (real participation, not a thin
                            illiquid spike).
  4. technical_buy_point -- the spike is happening *within* an existing
                            uptrend (price above a rising fast MA, RSI
                            bullish but not already blown-off), not against
                            a downtrend.

None of this is investment advice -- it's a transparent, tunable filter so
a virtual-money experiment isn't just "buy anything that's up 9% today".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

from . import config, strategy

log = logging.getLogger(__name__)


@dataclass
class CandidateEvaluation:
    ticker: str
    technical_buy_point: bool = False
    volume_high: bool = False
    kap_support: bool = False
    financials_support: bool | None = None  # None = data unavailable, not disqualifying
    adx_strong: bool = False        # trending, not choppy (ADX > threshold)
    donchian_breakout: bool = False  # fresh N-day high, not just a same-day wiggle
    kap_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def support_checks_passed(self) -> int:
        return sum([self.kap_support, bool(self.financials_support)])

    @property
    def passes(self) -> bool:
        if config.MOMENTUM_REQUIRE_TECHNICAL and not self.technical_buy_point:
            return False
        if config.MOMENTUM_REQUIRE_VOLUME and not self.volume_high:
            return False
        return self.support_checks_passed >= config.MOMENTUM_MIN_SUPPORT_CHECKS

    @property
    def score(self) -> float:
        s = 0.0
        s += 1.0 if self.technical_buy_point else 0.0
        s += 1.0 if self.volume_high else 0.0
        s += 1.5 if self.kap_support else 0.0
        s += 1.0 if self.financials_support else 0.0
        s += 1.0 if self.adx_strong else 0.0
        s += 1.5 if self.donchian_breakout else 0.0
        return s


def technical_buy_point(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Is today's spike happening within an existing uptrend, not against one?"""
    ind = strategy.compute_indicators(df)
    last = ind.iloc[-1]
    notes = []
    if pd.isna(last["fast_ma"]) or pd.isna(last["slow_ma"]) or pd.isna(last["rsi"]):
        return False, ["indicators unavailable (not enough history)"]

    uptrend = last["Close"] > last["fast_ma"] > last["slow_ma"]
    rsi_ok = config.MOMENTUM_RSI_MIN <= last["rsi"] <= config.MOMENTUM_RSI_MAX
    notes.append(f"close={last['Close']:.2f} fast_ma={last['fast_ma']:.2f} slow_ma={last['slow_ma']:.2f} rsi={last['rsi']:.1f}")
    return bool(uptrend and rsi_ok), notes


def volume_detail(df: pd.DataFrame, lookback: int = config.MOMENTUM_VOLUME_LOOKBACK, ratio: float = config.MOMENTUM_VOLUME_RATIO) -> dict:
    """Structured volume numbers, so callers (e.g. the BIST Ekranı page) can
    show the actual figures instead of just a pass/fail checkmark."""
    if len(df) < lookback + 1:
        return {"today_vol": None, "avg_vol": None, "ratio": None, "is_high": False}
    avg_vol = float(df["Volume"].iloc[-(lookback + 1):-1].mean())
    today_vol = float(df["Volume"].iloc[-1])
    vol_ratio = (today_vol / avg_vol) if avg_vol > 0 else None
    return {
        "today_vol": today_vol,
        "avg_vol": avg_vol,
        "ratio": vol_ratio,
        "is_high": bool(vol_ratio is not None and vol_ratio >= ratio),
    }


def volume_is_high(df: pd.DataFrame, lookback: int = config.MOMENTUM_VOLUME_LOOKBACK, ratio: float = config.MOMENTUM_VOLUME_RATIO) -> tuple[bool, list[str]]:
    d = volume_detail(df, lookback, ratio)
    if d["today_vol"] is None:
        return False, ["not enough history for volume average"]
    if d["avg_vol"] <= 0:
        return False, ["zero average volume"]
    return d["is_high"], [f"volume={d['today_vol']:.0f} vs {lookback}d avg={d['avg_vol']:.0f} (x{d['ratio']:.2f})"]


def adx(df: pd.DataFrame, period: int = config.MOMENTUM_ADX_PERIOD) -> pd.Series:
    """Wilder's Average Directional Index -- trend *strength*, independent
    of direction. RSI/MA already say "up or down"; ADX says whether that
    move is a real trend or just chop, which is exactly what a checklist
    built from MA/RSI alone can't tell you."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-12)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-12)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx_strong(df: pd.DataFrame, period: int = config.MOMENTUM_ADX_PERIOD, threshold: float = config.MOMENTUM_ADX_THRESHOLD) -> tuple[bool, list[str]]:
    if len(df) < period * 2:  # ADX needs a warm-up beyond just `period` bars
        return False, ["not enough history for ADX"]
    value = adx(df, period).iloc[-1]
    if pd.isna(value):
        return False, ["ADX unavailable"]
    return bool(value >= threshold), [f"ADX({period})={value:.1f} (threshold {threshold:.0f})"]


def donchian_breakout(df: pd.DataFrame, lookback: int = config.MOMENTUM_DONCHIAN_LOOKBACK) -> tuple[bool, list[str]]:
    """Did today's close set a fresh `lookback`-day high? The classic Turtle-
    trading breakout check -- maps directly onto "hisse tavan/zirve yapıyor"
    rather than inferring it indirectly from an MA crossover."""
    if len(df) < lookback + 1:
        return False, ["not enough history for Donchian channel"]
    prior_high = df["High"].iloc[-(lookback + 1):-1].max()
    today_close = df["Close"].iloc[-1]
    broke_out = bool(today_close > prior_high)
    return broke_out, [f"close={today_close:.2f} vs prior {lookback}d high={prior_high:.2f}"]


def financials_support(yf_ticker: str) -> tuple[bool | None, list[str]]:
    """Best-effort fundamentals check via yfinance. Returns None (not a hard
    'no') when data just isn't available, since small-cap BIST fundamentals
    coverage is inconsistent."""
    try:
        tk = yf.Ticker(yf_ticker)
        q = tk.quarterly_financials
        info = tk.get_info()
    except Exception as exc:
        return None, [f"fundamentals fetch failed: {exc}"]

    notes = []
    net_income_row = None
    if q is not None and not q.empty:
        for candidate in ("Net Income", "Net Income Common Stockholders"):
            if candidate in q.index:
                net_income_row = q.loc[candidate].dropna()
                break

    latest_positive = None
    improving = None
    if net_income_row is not None and len(net_income_row) >= 1:
        latest = net_income_row.iloc[0]
        latest_positive = latest > 0
        notes.append(f"latest quarterly net income={latest:,.0f}")
        if len(net_income_row) >= 2:
            prev = net_income_row.iloc[1]
            improving = latest > prev
            notes.append(f"prev quarterly net income={prev:,.0f}")

    revenue_growth = info.get("revenueGrowth") if isinstance(info, dict) else None
    if revenue_growth is not None:
        notes.append(f"revenueGrowth={revenue_growth:.2%}")

    if latest_positive is None:
        return None, notes or ["no financial data available"]

    revenue_ok = revenue_growth is None or revenue_growth >= config.MOMENTUM_FINANCIALS_MIN_REVENUE_GROWTH
    support = bool(latest_positive or (improving and revenue_ok))
    return support, notes


def evaluate_candidate(
    yf_ticker: str,
    df: pd.DataFrame,
    kap_flags: list[dict] | None = None,
) -> CandidateEvaluation:
    ev = CandidateEvaluation(ticker=yf_ticker)

    ev.technical_buy_point, tech_notes = technical_buy_point(df)
    ev.notes.extend(tech_notes)

    ev.volume_high, vol_notes = volume_is_high(df)
    ev.notes.extend(vol_notes)

    ev.adx_strong, adx_notes = adx_strong(df)
    ev.notes.extend(adx_notes)

    ev.donchian_breakout, donchian_notes = donchian_breakout(df)
    ev.notes.extend(donchian_notes)

    if kap_flags:
        ev.kap_support = True
        ev.kap_reasons = [f["subject"] for f in kap_flags]

    ev.financials_support, fin_notes = financials_support(yf_ticker)
    ev.notes.extend(fin_notes)

    return ev
