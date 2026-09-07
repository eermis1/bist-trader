"""Builds a JSON snapshot of both paper-trading portfolios for reporting.

Pure data assembly -- no rendering here. scripts/generate_dashboard.py
writes this to reports/dashboard_data.json; the published HTML dashboard
embeds that JSON at publish time.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging

from . import config, data

log = logging.getLogger(__name__)


def _read_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _latest_buy_checklist(trade_log_path) -> dict:
    """ticker -> most recent BUY row's checklist columns, from a momentum
    trade log CSV. Empty dict (no checklist data) for the trend strategy,
    which doesn't log one."""
    if not trade_log_path.exists():
        return {}
    latest: dict[str, dict] = {}
    with open(trade_log_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("side") != "BUY":
                continue
            latest[row["ticker"]] = row  # later rows overwrite earlier -> most recent wins
    return latest


def _position_snapshot(ticker: str, pos: dict, checklist: dict | None = None, stop_loss_pct: float | None = None, take_profit_pct: float | None = None) -> dict:
    df = data.fetch_history(ticker, period="3mo", max_age_hours=1)
    current_price = float(df["Close"].iloc[-1]) if not df.empty else pos["entry_price"]
    entry_price = pos["entry_price"]
    qty = pos["qty"]
    cost = entry_price * qty
    value = current_price * qty
    pnl = value - cost
    pnl_pct = (current_price / entry_price - 1) * 100 if entry_price else 0.0
    row = {
        "ticker": ticker,
        "entry_date": pos["entry_date"],
        "entry_price": entry_price,
        "qty": qty,
        "current_price": current_price,
        "cost": cost,
        "value": value,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
        "spark": [round(float(v), 2) for v in df["Close"].tail(config.BIST_SCREEN_SPARK_BARS).tolist()] if not df.empty else [],
    }
    if stop_loss_pct is not None:
        row["stop_loss_price"] = entry_price * (1 - stop_loss_pct)
        row["take_profit_price"] = entry_price * (1 + take_profit_pct)
    cl = (checklist or {}).get(ticker)
    if cl:
        row["checklist"] = {
            "technical": cl.get("technical") == "True",
            "volume_high": cl.get("volume_high") == "True",
            "kap_support": cl.get("kap_support") == "True",
            "kap_reasons": cl.get("kap_reasons") or "",
            "financials_support": cl.get("financials_support") == "True",
            "adx_strong": cl.get("adx_strong") == "True",
            "donchian_breakout": cl.get("donchian_breakout") == "True",
            "score": cl.get("score"),
        }
    return row


def _portfolio_summary(state: dict | None, checklist: dict | None = None) -> dict | None:
    if state is None:
        return None
    stop_loss_pct = state.get("stop_loss_pct")
    take_profit_pct = state.get("take_profit_pct")
    positions = [
        _position_snapshot(t, p, checklist, stop_loss_pct, take_profit_pct)
        for t, p in state.get("positions", {}).items()
    ]
    unrealized = sum(p["unrealized_pnl"] for p in positions)
    positions_value = sum(p["value"] for p in positions)
    equity = state["cash"] + positions_value

    closed = [t for t in state.get("trades", []) if t["side"] == "SELL" and t.get("pnl") is not None]
    realized = sum(t["pnl"] for t in closed)
    wins = [t for t in closed if t["pnl"] > 0]

    return {
        "initial_cash": state["initial_cash"],
        "cash": state["cash"],
        "equity": equity,
        "positions_value": positions_value,
        "total_return_pct": (equity / state["initial_cash"] - 1) * 100 if state["initial_cash"] else 0.0,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "max_positions": state.get("max_positions"),
        "open_positions": positions,
        "closed_trades": sorted(closed, key=lambda t: t["date"], reverse=True),
        "all_trades": sorted(state.get("trades", []), key=lambda t: t["date"], reverse=True),
        "win_rate_pct": (len(wins) / len(closed) * 100) if closed else None,
        "equity_curve": state.get("equity_curve", []),
    }


def _kap_company_news_items(limit: int) -> list[dict]:
    """Recent high-priority KAP disclosures, reshaped to look like a news
    item -- this is a much more BIST-specific "Şirket" source for Turkey
    than generic press RSS feeds."""
    from . import kap, tickers as tickers_mod

    known_tickers = set(tickers_mod.load_all_bist_symbols())
    df = kap.scan_recent(known_tickers=known_tickers)
    items = []
    for _, row in df.head(limit).iterrows():
        title = f"{row['ticker'] or row['kap_title']}: {row['subject']}"
        items.append({
            "title": title,
            "link": row["url"],
            "source": "KAP",
            "published": None,
            "category": "Şirket",
        })
    return items


def build_snapshot() -> dict:
    # momentum_trader/paper_trader's own 10.000/100.000 TL portfolios were
    # retired 2026-09-06 in favor of the Senaryo 1/2/3 framework -- their
    # code and state files remain (untouched, no longer traded) for
    # reference, but the dashboard no longer reads or displays them.
    from . import bist_screen, funds, lessons, news, scenario3, scenarios

    try:
        scenario3.run_once()
    except Exception:
        log.exception("Senaryo 3 trading cycle failed (non-fatal) -- showing last known state.")
    scenario3_state = _read_json(scenario3.STATE_FILE)
    scenario3_checklist = _latest_buy_checklist(scenario3.TRADE_LOG_FILE)
    try:
        scenario3_lessons = lessons.scenario3_lessons(scenario3.TRADE_LOG_FILE)
    except Exception:
        log.exception("Lessons-learned generation failed for Senaryo 3 (non-fatal).")
        scenario3_lessons = {"recent": [], "aggregate_notes": [], "closed_count": 0}

    empty_news = {c: [] for c in ("Şirket", "Politika", "Ekonomi")}
    try:
        news_data = news.fetch_all()
    except Exception:
        log.exception("News fetch failed (non-fatal) -- dashboard will show no news section.")
        news_data = {"fetched_at": None, "lookback_hours": config.NEWS_LOOKBACK_HOURS,
                      "tr": dict(empty_news), "us": dict(empty_news), "eu": dict(empty_news)}

    try:
        kap_items = _kap_company_news_items(config.NEWS_MAX_ITEMS_PER_CATEGORY)
        # KAP items first (more specific/reliable), then fill remaining slots with RSS items
        merged = kap_items + [i for i in news_data["tr"].get("Şirket", []) if i not in kap_items]
        news_data["tr"]["Şirket"] = merged[: config.NEWS_MAX_ITEMS_PER_CATEGORY]
    except Exception:
        log.exception("KAP company-news merge failed (non-fatal).")

    try:
        funds_data = funds.fetch_all()
    except Exception:
        log.exception("TEFAS fund fetch failed (non-fatal) -- dashboard will show no funds section.")
        funds_data = {"fetched_at": None, "watchlist": [], "leaderboard": {
            "top": [], "bottom": [], "metric_labels": {}, "rank_metric": None, "tax_note": ""}}

    try:
        bist_screen_data = bist_screen.classify_movers()
    except Exception:
        log.exception("BIST screen classification failed (non-fatal).")
        bist_screen_data = []

    try:
        indices_data = bist_screen.fetch_indices()
    except Exception:
        log.exception("Index fetch failed (non-fatal).")
        indices_data = []

    recommendations = {
        "stocks": sorted(bist_screen_data, key=lambda r: r.get("recommendation_score", 0), reverse=True)[:config.RECOMMEND_TOP_STOCKS],
        "funds": (funds_data.get("leaderboard") or {}).get("top", [])[:config.RECOMMEND_TOP_FUNDS],
    }

    try:
        scenario_data = scenarios.all_snapshots()
    except Exception:
        log.exception("Scenario snapshot failed (non-fatal).")
        scenario_data = {}

    scenario3_summary = _portfolio_summary(scenario3_state, scenario3_checklist)
    if scenario3_summary is not None:
        scenario3_summary["lessons"] = scenario3_lessons

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "news": news_data,
        "funds": funds_data,
        "bist_screen": bist_screen_data,
        "indices": indices_data,
        "scenarios": scenario_data,
        "scenario3": scenario3_summary,
        "recommendations": recommendations,
    }


TEMPLATE_FILE = config.ROOT_DIR / "bist_trader" / "templates" / "dashboard_template.html"


def _sanitize_nan(obj):
    """Recursively replace float NaN/Infinity with None.

    Python's json.dumps happily emits the literal tokens NaN/Infinity for
    these, which is valid Python/JS syntax but NOT valid JSON -- a strict
    JSON.parse() in the browser throws on them and silently kills the whole
    page's rendering. Better to catch it here, once, than re-discover it in
    every module that might produce a stray NaN (pandas loves to).
    """
    if isinstance(obj, float):
        return obj if obj == obj and abs(obj) != float("inf") else None  # obj != obj  <=>  NaN
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


def write_html(snapshot: dict, path=None) -> "config.Path":
    """Render the local, always-fresh dashboard -- reports/dashboard.html.

    Self-contained (data embedded inline), so it just needs opening in a
    browser. This is the file to actually rely on for up-to-date numbers;
    the published Artifact version is a snapshot that only updates when
    explicitly republished.
    """
    path = path or (config.REPORT_DIR / "dashboard.html")
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    html = template.replace("__SNAPSHOT_JSON__", json.dumps(_sanitize_nan(snapshot), ensure_ascii=False, default=str))
    path.write_text(html, encoding="utf-8")
    log.info("Dashboard HTML written to %s", path)
    return path


def write_snapshot(path=None) -> dict:
    path = path or (config.REPORT_DIR / "dashboard_data.json")
    snapshot = build_snapshot()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
    log.info("Dashboard snapshot written to %s", path)
    write_html(snapshot)
    return snapshot
