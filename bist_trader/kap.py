"""KAP (Kamuyu Aydinlatma Platformu) disclosure monitoring.

Hits the same public JSON endpoint kap.org.tr's own disclosure-search page
uses (no API key / login involved). Market-wide: pass no company filter to
get every disclosure across all BIST-listed entities for a date range, then
filter/flag by subject.

This is a public-disclosure feed, not a trade-execution signal on its own --
useful as an extra "why is this stock suddenly interesting" layer on top of
the price-based screener/strategy.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9]{2,5})\)")


def fetch_disclosures(
    from_date: dt.date,
    to_date: dt.date,
    disclosure_class: str = "ODA",
    subjects: list[str] | None = None,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    """Fetch raw disclosure records from KAP for a date range.

    subjects: optional list of exact KAP subject strings to filter server-side
        isn't supported reliably for free-text subjects, so we filter client-side
        in scan_recent(); this fetches everything in `disclosure_class` for the
        window and lets callers narrow it down.
    """
    payload = {
        "fromDate": str(from_date),
        "toDate": str(to_date),
        "disclosureClass": disclosure_class,
        "subjectList": [],
        "mkkMemberOidList": [],
        "inactiveMkkMemberOidList": [],
        "bdkMemberOidList": [],
        "fromSrc": False,
        "disclosureIndexList": [],
    }
    try:
        resp = requests.post(config.KAP_API_URL, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("KAP fetch failed: %s", exc)
        return []

    data = resp.json()
    if not isinstance(data, list):
        return []
    if stock_codes:
        wanted = set(stock_codes)
        data = [d for d in data if d.get("stockCodes") and set(d["stockCodes"].split(",")) & wanted]
    return data


def extract_ticker(record: dict, known_tickers: set[str]) -> str | None:
    """Best-effort mapping of a disclosure record to a BIST ticker.

    `stockCodes` is often the *disclosing* entity's own code (e.g. a fund
    manager filing on behalf of a position it took in another company), so
    we also look for a parenthesised ticker-looking token in the summary,
    e.g. "Avrasya Gayrimenkul Yatirim Ortakligi A.S. (AVGYO) Pay alim
    bildirimi" -> AVGYO.
    """
    codes = (record.get("stockCodes") or "").split(",")
    for c in codes:
        c = c.strip()
        if c in known_tickers:
            return c

    summary = record.get("summary") or ""
    for m in _TICKER_RE.findall(summary):
        if m in known_tickers:
            return m

    return codes[0].strip() if codes and codes[0].strip() else None


def scan_recent(
    days: int = config.KAP_LOOKBACK_DAYS,
    subjects: list[str] = config.KAP_HIGH_PRIORITY_SUBJECTS,
    known_tickers: set[str] | None = None,
) -> pd.DataFrame:
    """High-priority KAP disclosures from the last `days`, one row per disclosure.

    Columns: date, ticker, subject, kap_title, summary, disclosure_index, url
    """
    today = dt.date.today()
    frm = today - dt.timedelta(days=days)
    raw = fetch_disclosures(frm, today, disclosure_class="ODA")
    if not raw:
        return pd.DataFrame(columns=["date", "ticker", "subject", "kap_title", "summary", "disclosure_index", "url"])

    subject_set = set(subjects)
    rows = []
    for d in raw:
        if d.get("subject") not in subject_set:
            continue
        ticker = extract_ticker(d, known_tickers) if known_tickers else (d.get("stockCodes") or "").split(",")[0]
        rows.append({
            "date": d.get("publishDate"),
            "ticker": ticker,
            "subject": d.get("subject"),
            "kap_title": d.get("kapTitle"),
            "summary": d.get("summary"),
            "disclosure_index": d.get("disclosureIndex"),
            "url": f"https://www.kap.org.tr/tr/Bildirim/{d.get('disclosureIndex')}",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df
