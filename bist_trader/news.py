"""News feed for the dashboard's "Haberler" page: TR / US / EU, each split
into Şirket (company) / Politika (politics) / Ekonomi (economy).

Pulls free public RSS/Atom feeds and classifies each item into exactly one
category by keyword match (first match wins: Şirket, then Politika, then
Ekonomi). An item matching none of the three is dropped -- there's no
separate "is this relevant at all" filter, the category keywords are the
filter. This is a headline-awareness layer, not a stock-to-news mapper: it
surfaces items, you judge relevance to your positions/funds.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import feedparser

from . import config

log = logging.getLogger(__name__)

_REGIONS = {
    "tr": (config.NEWS_SOURCES_TR, config.NEWS_CATEGORY_KEYWORDS_TR),
    "us": (config.NEWS_SOURCES_US, config.NEWS_CATEGORY_KEYWORDS_INTL),
    "eu": (config.NEWS_SOURCES_EU, config.NEWS_CATEGORY_KEYWORDS_INTL),
}

_CATEGORY_ORDER = ["Şirket", "Politika", "Ekonomi"]


def _entry_time(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            return dt.datetime.fromtimestamp(time.mktime(t), tz=dt.timezone.utc)
    return None


def _categorize(text: str, keyword_map: dict[str, list[str]]) -> str | None:
    # Python's default .lower() turns Turkish "İ" into "i" + a combining dot
    # (U+0307), not plain ASCII "i" -- which silently breaks substring
    # matches against keywords like "inşaat" typed with a normal "i".
    low = text.replace("İ", "i").lower()
    for category in _CATEGORY_ORDER:
        if any(kw in low for kw in keyword_map.get(category, [])):
            return category
    return None


def _fetch_source(source: dict, keyword_map: dict, cutoff: dt.datetime) -> list[dict]:
    items = []
    try:
        parsed = feedparser.parse(source["url"])
    except Exception as exc:
        log.warning("news fetch failed for %s: %s", source["name"], exc)
        return items

    for entry in getattr(parsed, "entries", []):
        title = getattr(entry, "title", "").strip()
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        if not title:
            continue
        published = _entry_time(entry)
        if published and published < cutoff:
            continue
        category = _categorize(f"{title} {summary}", keyword_map)
        if category is None:
            continue
        items.append({
            "title": title,
            "link": getattr(entry, "link", ""),
            "source": source["name"],
            "published": published.isoformat() if published else None,
            "category": category,
        })
    return items


def fetch_region(region: str) -> dict[str, list[dict]]:
    """region: 'tr', 'us', or 'eu'. Returns {"Şirket": [...], "Politika": [...], "Ekonomi": [...]}."""
    sources, keyword_map = _REGIONS[region]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=config.NEWS_LOOKBACK_HOURS)

    all_items: list[dict] = []
    for source in sources:
        all_items.extend(_fetch_source(source, keyword_map, cutoff))
    all_items.sort(key=lambda i: i["published"] or "", reverse=True)

    grouped: dict[str, list[dict]] = {c: [] for c in _CATEGORY_ORDER}
    for item in all_items:
        bucket = grouped[item["category"]]
        if len(bucket) < config.NEWS_MAX_ITEMS_PER_CATEGORY:
            bucket.append(item)
    return grouped


def fetch_all() -> dict:
    return {
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "lookback_hours": config.NEWS_LOOKBACK_HOURS,
        "tr": fetch_region("tr"),
        "us": fetch_region("us"),
        "eu": fetch_region("eu"),
    }
