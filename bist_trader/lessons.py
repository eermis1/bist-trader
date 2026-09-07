"""Ders çıkarımları (lessons learned) for each Senaryo tab.

Deterministic and data-driven -- no free-form generation, every sentence
traces back to a logged field (checklist flags from the trade CSV, the
saved entry `reason` string, or a BIST 100 comparison). Two flavours:

  * Senaryo 3 (and the momentum strategy) actually closes trades, so we
    FIFO-pair each BUY/SELL per ticker from its trade-log CSV and explain
    the realized pnl using the checklist that was true at entry.
  * Senaryo 1/2 are buy-and-hold with no exits during the hold window, so
    there is nothing "closed" to learn from yet -- instead we explain each
    open position's unrealized pnl relative to the BIST 100 over the same
    holding period, to separate "the pick was right" from "the whole
    market moved".
"""

from __future__ import annotations

import csv
import datetime as dt

from . import config, data

log = __import__("logging").getLogger(__name__)

_EXIT_TR = {
    "stop_loss": "zarar-durdur seviyesine",
    "take_profit": "kâr-al hedefine",
    "momentum_fading_rsi": "RSI zayıflamasına",
    "momentum_fading_below_ma": "fiyatın hareketli ortalamanın altına düşmesine",
}


def _read_trade_rows(trade_log_file) -> list[dict]:
    if not trade_log_file.exists():
        return []
    with open(trade_log_file, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _pair_round_trips(rows: list[dict]) -> list[dict]:
    """FIFO-pair each BUY with the SELL that closed it, per ticker."""
    open_buys: dict[str, list[dict]] = {}
    trips = []
    for row in rows:
        ticker = row["ticker"]
        if row["side"] == "BUY":
            open_buys.setdefault(ticker, []).append(row)
        elif row["side"] == "SELL":
            queue = open_buys.get(ticker)
            entry = queue.pop(0) if queue else None
            trips.append({"ticker": ticker, "entry": entry, "exit": row})
    return trips


def _checklist_bits(entry: dict | None) -> list[str]:
    if not entry:
        return []
    bits = []
    if entry.get("kap_support") == "True":
        reasons = (entry.get("kap_reasons") or "").strip()
        bits.append(f"KAP desteği ({reasons})" if reasons else "KAP desteği")
    if entry.get("financials_support") == "True":
        bits.append("bilanço desteği")
    if entry.get("adx_strong") == "True":
        bits.append("güçlü ADX trendi")
    if entry.get("donchian_breakout") == "True":
        bits.append(f"{config.MOMENTUM_DONCHIAN_LOOKBACK}-günlük zirve kırılımı")
    if entry.get("technical") == "True":
        bits.append("teknik giriş noktası")
    if entry.get("volume_high") == "True":
        bits.append("yüksek hacim")
    return bits


def _has_fundamentals(bits: list[str]) -> bool:
    return any(b.startswith("KAP") or b == "bilanço desteği" for b in bits)


def _trip_lesson(trip: dict) -> dict | None:
    exit_row = trip["exit"]
    pnl_raw = exit_row.get("pnl")
    if pnl_raw in (None, ""):
        return None
    try:
        pnl = float(pnl_raw)
    except ValueError:
        return None

    entry = trip["entry"]
    bits = _checklist_bits(entry)
    fundamentals = _has_fundamentals(bits)
    technical_only = bool(bits) and not fundamentals
    exit_reason_tr = _EXIT_TR.get(exit_row["reason"], exit_row["reason"])

    price_entry = float(entry["price"]) if entry and entry.get("price") else None
    price_exit = float(exit_row["price"])
    pnl_pct = ((price_exit / price_entry) - 1) * 100 if price_entry else None

    is_win = pnl > 0
    if is_win and fundamentals:
        verdict = "Kâr, KAP/bilanço gibi temel bir veriyle desteklenen bir sinyaldi -- bu tür girişlere güven artırılabilir."
    elif is_win and technical_only:
        verdict = "Kâr, sadece teknik/hacim sinyaliyle geldi (KAP/bilanço desteği yoktu) -- işe yaradı, ama temel destek olmadan küçük örneklemle temkinli yorumlanmalı."
    elif is_win:
        verdict = "Kâr geldi ama girişte hiçbir checklist onayı loglanmamış (eski/eksik kayıt)."
    elif not is_win and technical_only:
        verdict = "Zarar, sadece teknik/hacim sinyaliyle (KAP veya bilanço desteği YOK) girilen bir pozisyondan geldi -- ileride salt teknik sinyalle girişte pozisyon küçültülmeli veya KAP/bilanço şartı aranmalı."
    elif not is_win and fundamentals:
        verdict = "Zarar, KAP/bilanço desteği olmasına rağmen geldi -- temel destek tek başına garanti değil, giriş zamanlamasının teknik onayla birlikte aranması gerekir."
    else:
        verdict = "Zarar geldi, girişte hiçbir checklist onayı loglanmamış (eski/eksik kayıt)."

    return {
        "ticker": trip["ticker"],
        "entry_date": entry["date"] if entry else None,
        "exit_date": exit_row["date"],
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason_tr,
        "checklist": bits,
        "verdict": verdict,
    }


def _aggregate_closed(lessons: list[dict]) -> list[str]:
    fundamentals = [l for l in lessons if _has_fundamentals(l["checklist"])]
    technical_only = [l for l in lessons if l["checklist"] and not _has_fundamentals(l["checklist"])]
    out = []
    if len(fundamentals) >= 2 and len(technical_only) >= 2:
        f_pcts = [l["pnl_pct"] for l in fundamentals if l["pnl_pct"] is not None]
        t_pcts = [l["pnl_pct"] for l in technical_only if l["pnl_pct"] is not None]
        if f_pcts and t_pcts:
            f_avg = sum(f_pcts) / len(f_pcts)
            t_avg = sum(t_pcts) / len(t_pcts)
            f_win = sum(1 for l in fundamentals if l["pnl"] > 0) / len(fundamentals) * 100
            t_win = sum(1 for l in technical_only if l["pnl"] > 0) / len(technical_only) * 100
            out.append(
                f"Şimdiye kadar KAP/bilanço destekli girişler ortalama %{f_avg:+.1f} getiri ve %{f_win:.0f} kazanma oranı verdi; "
                f"sadece teknik/hacim sinyaliyle girilenler ortalama %{t_avg:+.1f} getiri ve %{t_win:.0f} kazanma oranı verdi."
            )
            if f_avg > t_avg:
                out.append("Bu, checklist'te KAP/bilanço şartının ağırlığını artırmanın mantıklı olabileceğini gösteriyor.")
            else:
                out.append("Şu ana kadarki (küçük) örneklemde temel destek belirgin bir avantaj sağlamadı -- teknik/hacim sinyali tek başına da işe yaramış.")
    return out


def scenario3_lessons(trade_log_file, limit: int = 8) -> dict:
    rows = _read_trade_rows(trade_log_file)
    trips = _pair_round_trips(rows)
    lessons = [l for l in (_trip_lesson(t) for t in trips) if l]
    lessons.sort(key=lambda l: l["exit_date"], reverse=True)
    return {
        "recent": lessons[:limit],
        "aggregate_notes": _aggregate_closed(lessons),
        "closed_count": len(lessons),
    }


def _index_return_since(start_date_str: str | None, index_ticker: str = "XU100.IS") -> float | None:
    """Index return from the last trading day AT OR BEFORE start_date (the
    same reference close a position's entry_price would have used, since
    scenarios are built once a day and start_date can land on a weekend) to
    today. Using "on or after" instead would, on a weekend start_date,
    collapse the baseline to today's own close and always report ~0%."""
    if not start_date_str:
        return None
    try:
        start_date = dt.date.fromisoformat(start_date_str)
    except ValueError:
        return None
    df = data.fetch_history(index_ticker, period="1mo", max_age_hours=6)
    if df.empty:
        return None
    dates = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
    on_or_before = [c for d, c in zip(dates, df["Close"]) if d <= start_date]
    baseline_close = float(on_or_before[-1]) if on_or_before else float(df["Close"].iloc[0])
    last_close = float(df["Close"].iloc[-1])
    return (last_close / baseline_close - 1) * 100 if baseline_close else None


def _reason_label(reason: str | None) -> str:
    """Just the leading driver label ("Teknik/Hacim", "Bilanço", ...) off a
    scenario position's stored `reason` string -- the full text is already
    shown alongside the verdict in the UI, so the verdict itself only needs
    a short tag, not a repeat of the whole blurb."""
    text = (reason or "").strip()
    if not text:
        return "bilinmeyen sinyal"
    for sep in (" (sinyal skoru", " --"):
        if sep in text:
            return text.split(sep)[0].strip()
    return text[:40].strip()


def buyhold_lessons(snapshot: dict) -> dict:
    positions = [p for p in snapshot.get("positions", []) if p.get("asset_type") == "stock"]
    if not positions:
        return {"recent": [], "aggregate_notes": [], "closed_count": 0}

    index_return = _index_return_since(snapshot.get("start_date"))

    lessons = []
    for p in positions:
        pnl_pct = p.get("unrealized_pnl_pct", 0.0)
        rel = (pnl_pct - index_return) if index_return is not None else None
        is_win = pnl_pct > 0
        label = _reason_label(p.get("reason"))

        if rel is not None and rel > 1.0:
            verdict = f"Piyasanın (BIST 100: %{index_return:+.1f}) belirgin üzerinde -- giriş nedeni ({label}) şimdilik doğrulanıyor."
        elif rel is not None and rel < -1.0:
            verdict = f"Piyasadan (BIST 100: %{index_return:+.1f}) belirgin kötü -- giriş nedeni ({label}) henüz teyit edilmedi, hisseye özgü zayıflık var."
        elif is_win:
            verdict = "Kârda, ama büyük ölçüde piyasa geneliyle uyumlu bir hareket -- hisseye özgü katkı henüz net değil."
        else:
            verdict = "Zararda, ama büyük ölçüde piyasa geneliyle uyumlu bir geri çekilme -- hisseye özgü bir sorun şimdilik görünmüyor."

        lessons.append({
            "ticker": p["ticker"],
            "pnl_pct": pnl_pct,
            "relative_to_index_pct": rel,
            "reason": p.get("reason"),
            "verdict": verdict,
        })
    lessons.sort(key=lambda l: l["pnl_pct"])

    notes = []
    if index_return is not None and lessons:
        avg = sum(l["pnl_pct"] for l in lessons) / len(lessons)
        notes.append(
            f"Portföy ortalaması %{avg:+.1f}, aynı dönemde BIST 100 %{index_return:+.1f} -- "
            + ("piyasayı geçiyor." if avg > index_return else "piyasanın gerisinde kalıyor.")
        )
    if snapshot.get("hold_complete"):
        notes.append(f"{snapshot.get('hold_days')} günlük tutma süresi doldu -- bir sonraki taramada bu sinyallerin ne kadar geçerli kaldığı yeniden değerlendirilecek.")
    return {"recent": lessons, "aggregate_notes": notes, "closed_count": 0}
