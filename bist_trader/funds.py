"""Turkish investment fund (TEFAS) tracking.

TEFAS's current public API exposes daily fund price/NAV and period returns
(1mo/3mo/6mo/1y/YTD/3y/5y) for every fund in one bulk call, but NOT fund
portfolio holdings -- there is no free way to see which stocks a given fund
holds (same gap as broker custody data; see README). So this module is a
fund *performance* tracker, not a "smart money is buying X" signal. The
"why is this fund up" text is inferred (fund-name sector keywords, plus an
opportunistic name-match against recent KAP ownership-disclosure filers) and
clearly hedged -- never presented as a confirmed cause.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
from tefas import Crawler

from . import config

log = logging.getLogger(__name__)

_LIST_PAYLOAD = {
    "dil": "TR",
    "fonTipi": "YAT",
    "kurucuKodu": None,
    "sfonTurKod": None,
    "fonTurAciklama": None,
    "islem": 1,
    "fonTurKod": None,
    "fonGrubu": None,
    "donemGetiri1a": "1",
    "donemGetiri3a": "1",
    "donemGetiri6a": "1",
    "donemGetiri1y": "1",
    "donemGetiriyb": "1",
    "donemGetiri3y": "1",
    "donemGetiri5y": "1",
    "basTarih": None,
    "bitTarih": None,
    "calismaTipi": 2,
    "getiriOrani": "1",
}

_RETURN_FIELD_LABELS = {
    "getiri1a": "1 Ay", "getiri3a": "3 Ay", "getiri6a": "6 Ay",
    "getiri1y": "1 Yıl", "getiriyb": "Yılbaşından", "getiri3y": "3 Yıl", "getiri5y": "5 Yıl",
}


def fetch_fund_list() -> list[dict]:
    """All TEFAS funds with their period returns, in one request."""
    crawler = Crawler()
    try:
        rows = crawler._do_post(crawler.list_endpoint, _LIST_PAYLOAD)  # noqa: SLF001
    except Exception as exc:
        log.warning("TEFAS fund list fetch failed: %s", exc)
        return []
    return rows


def _infer_sector(title: str) -> str | None:
    # see news.py's _categorize -- Python's .lower() mangles Turkish "İ".
    low = title.replace("İ", "i").lower()
    for label, keywords in config.FUND_SECTOR_KEYWORDS:
        if any(kw in low for kw in keywords):
            return label
    return None


def _manager_name(title: str) -> str:
    """'TERA PORTFÖY HİSSE SENEDİ (TL) FONU (...)' -> 'TERA'."""
    idx = title.upper().find(" PORTFÖY")
    if idx > 0:
        return title[:idx].strip()
    return (title.split() or [""])[0]


def _tax_note(category: str) -> str:
    return config.FUND_TAX_NOTES.get(category, config.FUND_TAX_NOTES["_default"])


def _kap_manager_hints(manager_names: set[str], days: int = 10) -> dict[str, list[str]]:
    """manager name -> recent KAP 'Pay Alım Satım Bildirimi' targets filed by
    a KAP entity whose title starts with that manager name. Best-effort only:
    a name-prefix match, not a verified corporate link."""
    from . import kap

    if not manager_names:
        return {}
    today = dt.date.today()
    raw = kap.fetch_disclosures(today - dt.timedelta(days=days), today, disclosure_class="ODA")
    out: dict[str, list[str]] = {}
    for d in raw:
        if d.get("subject") != "Pay Alım Satım Bildirimi":
            continue
        kap_title = (d.get("kapTitle") or "").upper()
        for name in manager_names:
            if name and kap_title.startswith(name):
                target = d.get("summary") or d.get("stockCodes") or ""
                bucket = out.setdefault(name, [])
                if target and target not in bucket and len(bucket) < 3:
                    bucket.append(target)
    return out


def _reason_guess(title: str, manager_hints: dict[str, list[str]]) -> str:
    sector = _infer_sector(title)
    manager = _manager_name(title)
    parts = []
    if sector:
        parts.append(f"Fon adına göre odağı '{sector}' -- bu temaya yakın hisselerdeki hareket katkı sağlamış olabilir.")
    hints = manager_hints.get(manager)
    if hints:
        parts.append(
            f"Ayrıca KAP'a göre bu fonu yöneten {manager} PORTFÖY, son {config.MOMENTUM_KAP_LOOKBACK_DAYS} günde "
            f"şu konularda Pay Alım Satım Bildirimi yapmış: {'; '.join(hints)} (isim eşleşmesine dayalı olası ipucu, kesin bağlantı değil)."
        )
    if not parts:
        parts.append("Portföy içeriği kamuya açık olmadığı için net bir neden çıkarılamıyor.")
    return " ".join(parts)


def leaderboard(
    n: int = config.FUND_LEADERBOARD_COUNT,
    category: str = config.FUND_LEADERBOARD_CATEGORY,
    rank_metric: str = config.FUND_LEADERBOARD_RANK_METRIC,
    metrics: list[str] = config.FUND_LEADERBOARD_METRICS,
) -> dict:
    """Top and bottom `n` funds in `category`, ranked by `rank_metric`, with
    all `metrics` period returns plus a hedged "why" guess for the top funds."""
    empty = {"top": [], "bottom": [], "metric_labels": {m: _RETURN_FIELD_LABELS.get(m, m) for m in metrics},
             "rank_metric": rank_metric, "tax_note": _tax_note(category)}

    rows = fetch_fund_list()
    df = pd.DataFrame(rows)
    if df.empty or rank_metric not in df.columns:
        return empty

    df = df[(df["fonTurAciklama"] == category) & (df["tefasDurum"] == True) & df[rank_metric].notna()]  # noqa: E712
    df = df.sort_values(rank_metric, ascending=False)

    top_df = df.head(n)
    bottom_df = df.tail(n).iloc[::-1]

    manager_names = {_manager_name(t) for t in top_df["fonUnvan"]}
    hints = _kap_manager_hints(manager_names)

    def _rows(d: pd.DataFrame, with_reason: bool) -> list[dict]:
        out = []
        for _, r in d.iterrows():
            row = {"code": r["fonKodu"], "title": r["fonUnvan"]}
            for m in metrics:
                v = r.get(m)
                row[m] = float(v) if pd.notna(v) else None  # NaN isn't valid JSON -- null is
            if with_reason:
                row["reason"] = _reason_guess(r["fonUnvan"], hints)
            out.append(row)
        return out

    return {
        "top": _rows(top_df, with_reason=True),
        "bottom": _rows(bottom_df, with_reason=False),
        "metric_labels": {m: _RETURN_FIELD_LABELS.get(m, m) for m in metrics},
        "rank_metric": rank_metric,
        "tax_note": _tax_note(category),
    }


def watchlist_snapshot(codes: list[str] = config.FUND_WATCHLIST) -> list[dict]:
    """Latest price + day-over-day change for each watched fund code."""
    if not codes:
        return []
    crawler = Crawler()
    out = []
    for code in codes:
        try:
            df = crawler.fetch(
                start=(dt.date.today() - dt.timedelta(days=config.FUND_DAILY_CHANGE_LOOKBACK_DAYS)).isoformat(),
                end=dt.date.today().isoformat(),
                name=code,
            )
        except Exception as exc:
            log.warning("TEFAS fetch failed for %s: %s", code, exc)
            continue
        if df.empty:
            continue
        df = df.sort_values("date")
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None
        pct = (last["price"] / prev["price"] - 1) * 100 if prev is not None and prev["price"] else None
        out.append({
            "code": last["code"],
            "title": last["title"],
            "date": str(last["date"]),
            "price": float(last["price"]),
            "daily_change_pct": pct,
            "category_rank": int(last["category_rank"]) if pd.notna(last["category_rank"]) else None,
            "category_total": int(last["category_total"]) if pd.notna(last["category_total"]) else None,
        })
    return out


def fetch_all() -> dict:
    return {
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "watchlist": watchlist_snapshot(),
        "leaderboard": leaderboard(),
    }
