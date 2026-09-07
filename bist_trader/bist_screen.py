"""BIST Ekranı: today's top movers, each tagged with a best-guess reason.

For every one of today's top-N gainers/near-limit stocks, checks four things
and picks a single primary label (first match wins):

  1. Bilanço   -- a KAP "Finansal Rapor" (earnings) disclosure landed for
                  this ticker in the last few days.
  2. Haber/KAP -- a high-priority KAP disclosure (ownership-threshold
                  crossing, merger, tender offer, unusual price/volume flag).
  3. Teknik/Hacim -- momentum.py's technical-uptrend or volume-spike check
                  passes, but nothing above does.
  4. Spekülatif -- none of the above; no identifiable driver found. Doesn't
                  mean it IS manipulation, just that this system can't
                  explain the move from public data.

These are "adaylar" (candidates) for you to research further, not a signal
to act on by themselves.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import config, data, kap, momentum, screener, tickers as tickers_mod

log = logging.getLogger(__name__)

_SECTOR_TR = {
    "Technology": "Teknoloji",
    "Healthcare": "Sağlık",
    "Financial Services": "Finansal Hizmetler",
    "Consumer Cyclical": "Dayanıklı Tüketim",
    "Industrials": "Sanayi",
    "Energy": "Enerji",
    "Utilities": "Kamu Hizmetleri (Enerji/Su/Gaz)",
    "Real Estate": "Gayrimenkul",
    "Basic Materials": "Temel Malzemeler",
    "Communication Services": "İletişim Hizmetleri",
    "Consumer Defensive": "Temel Tüketim",
}


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    for sep in (". ", ".\n"):
        if sep in text:
            return text.split(sep)[0].strip() + "."
    return text[:200].strip()


def _narrative(symbol: str, info: dict, row: dict, vol: dict) -> str:
    name = info.get("name") or symbol
    sector = _SECTOR_TR.get(info.get("sector"), info.get("sector"))
    industry = info.get("industry")
    parts = [f"{name}"]
    if sector or industry:
        where = " / ".join(x for x in (sector, industry) if x)
        parts.append(f"({where}) alanında faaliyet gösteriyor.")
    else:
        parts.append("hakkında sektör bilgisi bulunamadı.")

    summary = _first_sentence(info.get("summary"))
    if summary:
        parts.append(summary)

    label = row["label"]
    if label == "Bilanço":
        parts.append("Son günlerde KAP'a düşen bir finansal rapor/bilanço açıklaması bu hareketle zaman olarak örtüşüyor -- olası bir katalizör.")
    elif label == "Haber/KAP":
        reasons = ", ".join(row["kap_reasons"])
        parts.append(f"KAP'a yapılan '{reasons}' bildirimi bu hareketle zaman olarak örtüşüyor -- olası bir katalizör.")
    elif label == "Teknik/Hacim":
        bits = []
        if row["teknik"]:
            bits.append("fiyat yükselen bir ortalamanın üzerinde (trend içi)")
        if vol.get("is_high") and vol.get("ratio"):
            bits.append(f"hacim ortalamanın {vol['ratio']:.1f} katına çıkmış")
        if row.get("adx_strong"):
            bits.append("ADX güçlü bir trendi işaret ediyor (gürültü değil)")
        if row.get("donchian_breakout"):
            bits.append(f"son {config.MOMENTUM_DONCHIAN_LOOKBACK} günün en yükseğini kırmış (taze zirve)")
        if not bits:
            bits.append("teknik/hacim onaylarından en az biri sağlanmış")
        parts.append(f"Kamuya açık bir KAP/bilanço tetikleyicisi bulunamadı, ama {' ve '.join(bits)} -- gerçek katılımla desteklenen organik bir hareket olabilir.")
    else:
        parts.append("KAP bildirimi, taze bilanço ya da teknik/hacim onayı gibi kamuya açık bir açıklama bulunamadı -- haber öncesi veya spekülatif bir hareket olabilir, temkinli yaklaşın.")

    return " ".join(parts)


def fetch_indices() -> list[dict]:
    """Recent close-price series for the index charts at the top of BIST
    Ekranı (config.BIST_INDICES)."""
    out = []
    for idx in config.BIST_INDICES:
        df = data.fetch_history(idx["ticker"], period=config.BIST_INDEX_PERIOD, max_age_hours=6)
        if df.empty:
            continue
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else last
        out.append({
            "key": idx["key"],
            "label": idx["label"],
            "last": last,
            "change_pct": (last / prev - 1) * 100 if prev else 0.0,
            "spark": [round(float(v), 2) for v in df["Close"].tolist()],
        })
    return out


def _fresh_financial_report_tickers(days: int) -> set[str]:
    today = dt.date.today()
    frm = today - dt.timedelta(days=days)
    raw = kap.fetch_disclosures(frm, today, disclosure_class="FR")
    tickers: set[str] = set()
    for d in raw:
        if d.get("subject") == "Finansal Rapor":
            codes = (d.get("stockCodes") or "").split(",")
            tickers.update(c.strip() for c in codes if c.strip())
    return tickers


def classify_movers(top_n: int = config.BIST_SCREEN_TOP_N, universe: list[str] | None = None) -> list[dict]:
    yf_tickers = universe or tickers_mod.load_yfinance_universe()
    known_tickers = {t.replace(config.YF_SUFFIX, "") for t in yf_tickers}

    movers = screener.top_gainers(yf_tickers, n=top_n)
    if movers.empty:
        return []

    fr_tickers = _fresh_financial_report_tickers(config.BIST_SCREEN_FR_LOOKBACK_DAYS)
    kap_df = kap.scan_recent(days=config.MOMENTUM_KAP_LOOKBACK_DAYS, known_tickers=known_tickers)
    kap_by_symbol: dict[str, list[dict]] = {}
    for _, row in kap_df.iterrows():
        kap_by_symbol.setdefault(row["ticker"], []).append(row.to_dict())

    results = []
    for _, row in movers.iterrows():
        yf_t = row["ticker"]
        symbol = yf_t.replace(config.YF_SUFFIX, "")
        df = data.fetch_history(yf_t, period="6mo", max_age_hours=1)

        technical, vol = False, {"today_vol": None, "avg_vol": None, "ratio": None, "is_high": False}
        adx_ok, donchian_ok = False, False
        if not df.empty:
            technical, _ = momentum.technical_buy_point(df)
            vol = momentum.volume_detail(df)
            adx_ok, _ = momentum.adx_strong(df)
            donchian_ok, _ = momentum.donchian_breakout(df)

        bilanco = symbol in fr_tickers
        kap_flags = kap_by_symbol.get(symbol, [])
        haber = bool(kap_flags)

        if bilanco:
            label = "Bilanço"
        elif haber:
            label = "Haber/KAP"
        elif technical or vol["is_high"] or adx_ok or donchian_ok:
            label = "Teknik/Hacim"
        else:
            label = "Spekülatif"

        entry = {
            "symbol": symbol,
            "pct_change": float(row["pct_change"]),
            "close": float(row["close"]),
            "near_limit": bool(row["near_limit"]),
            "label": label,
            "bilanco": bilanco,
            "haber": haber,
            "kap_reasons": [f["subject"] for f in kap_flags],
            "teknik": bool(technical),
            "hacim": bool(vol["is_high"]),
            "adx_strong": bool(adx_ok),
            "donchian_breakout": bool(donchian_ok),
            "today_volume": vol["today_vol"],
            "avg_volume": vol["avg_vol"],
            "avg_volume_lookback": config.MOMENTUM_VOLUME_LOOKBACK,
            "volume_ratio": vol["ratio"],
            "spark": [round(v, 2) for v in df["Close"].tail(config.BIST_SCREEN_SPARK_BARS).tolist()] if not df.empty else [],
        }
        # Composite score for the "Öneriler" page -- how many of our
        # independent signals line up behind this move, weighted by how
        # concrete each one is (a KAP filing beats a generic MA/RSI read).
        # This ranks *signal agreement*, not a return forecast.
        entry["recommendation_score"] = (
            3.0 * bilanco
            + 2.0 * haber
            + 1.0 * technical
            + 1.0 * vol["is_high"]
            + 1.0 * adx_ok
            + 1.5 * donchian_ok
        )

        info = data.get_company_info(yf_t)
        entry["company_name"] = info.get("name") or symbol
        entry["sector"] = _SECTOR_TR.get(info.get("sector"), info.get("sector"))
        entry["narrative"] = _narrative(symbol, info, entry, vol)

        results.append(entry)
    return results
