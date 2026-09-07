"""Central configuration for the BIST100 paper-trading agent."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = DATA_DIR / "logs"
REPORT_DIR = ROOT_DIR / "reports"
TICKERS_FILE = DATA_DIR / "bist100_tickers.csv"
ALL_TICKERS_FILE = DATA_DIR / "bist_all_tickers.csv"
ALL_COMPANIES_FILE = DATA_DIR / "bist_all_companies.csv"

# "bist100" -> data/bist100_tickers.csv (100 names, faster to run)
# "all"     -> data/bist_all_tickers.csv (759 KAP-registered tickers, full BIST)
UNIVERSE = "all"

for d in (DATA_DIR, CACHE_DIR, STATE_DIR, LOG_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# yfinance suffix for Borsa Istanbul listings
YF_SUFFIX = ".IS"

# --- Strategy parameters (simple trend + momentum rule) ---
# Tuned via scripts/optimize.py grid search over 3y of BIST100 data
# (216 combos, ranked by Calmar ratio = CAGR / |max drawdown|). This combo:
# CAGR 34.3%, max DD -15.8%, Sharpe 1.50, Calmar 2.17, 289 trades, 53% win
# rate -- vs. the untuned defaults' CAGR 16.2%, DD -22.7%, Sharpe 0.88.
# Full grid: reports/optimization_results.csv. Re-run periodically; markets
# drift and these were fit on one particular 3y window.
FAST_MA = 10
SLOW_MA = 50
RSI_PERIOD = 14
RSI_BUY_MIN = 55       # only buy when momentum confirms (RSI above this)
RSI_SELL_MAX = 35      # exit long when momentum fades below this
STOP_LOSS_PCT = 0.12     # hard stop, per position
TAKE_PROFIT_PCT = 0.15   # optional take-profit, per position

# --- Portfolio / risk parameters ---
INITIAL_CASH = 100_000.0   # virtual TL balance for paper trading / backtest
MAX_OPEN_POSITIONS = 10
POSITION_SIZE_PCT = 1.0 / MAX_OPEN_POSITIONS  # equal-weight sizing
COMMISSION_PCT = 0.0015    # ~ typical Turkish broker commission, round trip approximated per fill
MIN_CASH_BUFFER_PCT = 0.02  # keep a small cash buffer unallocated

# --- Backtest defaults ---
BACKTEST_LOOKBACK_YEARS = 3
BACKTEST_INTERVAL = "1d"

# --- Paper trading loop ---
MARKET_TZ = "Europe/Istanbul"
MARKET_OPEN = "10:00"
MARKET_CLOSE = "18:00"
POLL_SECONDS = 300  # how often to re-check prices/signals while market is open
PAPER_INTERVAL = "1d"  # bar interval used to derive signals during paper trading

# --- Daily momentum / "radar" screener ---
# Most BIST equities move within a +/-10% daily band; some markets
# (Yakin Izleme Pazari, newly listed, etc.) have narrower bands. This is
# used as an approximate "near/at the limit" flag, not an exact rule.
DAILY_LIMIT_PCT = 10.0
NEAR_LIMIT_THRESHOLD_PCT = 9.0  # flag as "yaklasiyor/tavan" from this daily gain up
TOP_GAINERS_COUNT = 20

# --- KAP (Kamuyu Aydinlatma Platformu) disclosure monitoring ---
# Public, unauthenticated endpoint used by kap.org.tr's own disclosure
# search page. No API key needed; be a reasonable citizen about request
# frequency (this is scraping the public site's own backend).
KAP_API_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
KAP_LOOKBACK_DAYS = 3

# Disclosure subjects (KAP disclosureClass="ODA") most relevant to a
# momentum/"who's building a position" watchlist -- notably including
# threshold-crossing "Pay Alim Satim Bildirimi" (mandatory disclosure once
# an investor's stake crosses a regulatory ownership threshold) and KAP's
# own "unusual price/volume movement" flag.
KAP_HIGH_PRIORITY_SUBJECTS = [
    "Pay Alım Satım Bildirimi",
    "Olağan Dışı Fiyat ve Miktar Hareketleri",
    "Pay Alım Teklifi Yoluyla Pay Toplanmasına İlişkin Bildirim",
    "Halka Arz İşlemlerinde Sermaye Piyasası Aracının % 5 inden Fazlasını Satın Alanlara İlişkin Bildirim",
    "Birleşme İşlemlerine İlişkin Bildirim",
    "Önemli Nitelikte İşlem",
]

# --- Momentum/KAP paper-trading strategy ("radar" auto-trader) ---
# Separate, higher-risk sibling of the trend-following strategy above: chases
# stocks at/near the daily limit, gated by a checklist (KAP support, balance
# sheet support, volume, technical entry point) before committing virtual
# cash. Runs its own Portfolio, independent of INITIAL_CASH/MAX_OPEN_POSITIONS.
MOMENTUM_INITIAL_CASH = 10_000.0
MOMENTUM_MAX_POSITIONS = 3
MOMENTUM_POSITION_SIZE_PCT = 1.0 / MOMENTUM_MAX_POSITIONS
MOMENTUM_STOP_LOSS_PCT = 0.07     # tighter than the trend strategy -- these are volatile entries
MOMENTUM_TAKE_PROFIT_PCT = 0.25
MOMENTUM_MIN_CASH_BUFFER_PCT = 0.02
MOMENTUM_COMMISSION_PCT = COMMISSION_PCT

# Candidate pool: today's top gainers / near-limit names (see screener.py)
MOMENTUM_KAP_LOOKBACK_DAYS = 5   # a bit wider than the general radar's 3 days

# Checklist gates. Volume is mandatory (not buying into a thin/illiquid
# move). Technical entry point is NOT mandatory -- a stock already spiking
# to the limit often hasn't "confirmed" an uptrend by MA-crossover terms
# yet, so requiring it blocked otherwise well-supported candidates (e.g.
# KAP+volume confirmed but not yet trend-confirmed). It still counts toward
# the ranking score (see CandidateEvaluation.score), just doesn't gate entry.
# KAP and balance-sheet support are "nice to have" confirmations -- require
# at least this many of the two.
MOMENTUM_REQUIRE_TECHNICAL = False
MOMENTUM_REQUIRE_VOLUME = True
MOMENTUM_MIN_SUPPORT_CHECKS = 1   # out of {kap_support, financials_support}

MOMENTUM_VOLUME_LOOKBACK = 20
MOMENTUM_VOLUME_RATIO = 1.5       # today's volume must be >= 1.5x its 20-day average

# Technical entry point (distinct from the slower MA-crossover strategy --
# a stock already spiking today won't have just crossed its 20/50 MA, so we
# instead confirm it's spiking *within* an existing uptrend, not against one).
MOMENTUM_RSI_MIN = 50.0
MOMENTUM_RSI_MAX = 85.0           # avoid chasing a name already extremely overbought

# "Bilanço destegi": latest reported quarter profitable, or net income
# improving quarter-over-quarter with revenue not deeply contracting.
MOMENTUM_FINANCIALS_MIN_REVENUE_GROWTH = -0.10

# Exit: same stop-loss/take-profit as entry gates above, plus fading momentum
# (RSI back below this, or price closes back under its fast MA).
MOMENTUM_EXIT_RSI_BELOW = 45.0

# Additional technical confirmations (scored, not gating -- they raise a
# candidate's rank but don't block one that lacks them, same philosophy as
# the checklist above). Added 2026-09-06 after a research pass on breakout/
# momentum trading indicators (ADX, Donchian channels, Bollinger squeeze,
# Minervini VCP) -- see README for the comparison.
MOMENTUM_ADX_PERIOD = 14
MOMENTUM_ADX_THRESHOLD = 25.0   # classic "trending, not choppy" cutoff
MOMENTUM_DONCHIAN_LOOKBACK = 20  # "made a fresh N-day high" breakout check

# --- Macro / political / company news feed (dashboard "Haberler" page) ---
# Free public RSS/Atom feeds -- no API key. This is a headline-level "what's
# moving that could move BIST/funds" awareness feed, not a stock-to-news
# mapper: it surfaces items, you judge relevance to your positions. Refreshed
# whenever the dashboard snapshot is (i.e. every trading-hours cycle), so it
# doesn't update outside 10:05-18:05 weekdays.
NEWS_LOOKBACK_HOURS = 30       # a bit over a day, so Monday morning still sees the weekend
NEWS_MAX_ITEMS_PER_CATEGORY = 6

NEWS_SOURCES_TR = [
    {"name": "NTV Ekonomi", "url": "https://www.ntv.com.tr/ekonomi.rss"},
    {"name": "Sabah Ekonomi", "url": "https://www.sabah.com.tr/rss/ekonomi.xml"},
    {"name": "BloombergHT", "url": "https://www.bloomberght.com/rss"},
]

NEWS_SOURCES_US = [
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"name": "CNBC Economy", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
    {"name": "Investing.com", "url": "https://www.investing.com/rss/news_285.rss"},
    {"name": "WSJ World", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
]

NEWS_SOURCES_EU = [
    {"name": "ECB", "url": "https://www.ecb.europa.eu/rss/press.xml"},
    {"name": "Euronews Business", "url": "https://www.euronews.com/rss?level=theme&name=business"},
    {"name": "POLITICO Europe", "url": "https://www.politico.eu/feed/"},
]

# Each region's items are classified into one of these three buckets by
# keyword match (checked in this order -- Şirket first, so a company-earnings
# story doesn't fall into the generic Ekonomi bucket). An item matching none
# of the three categories' keywords is dropped -- there's no separate
# "general relevance" filter anymore, the category keywords *are* the filter.
NEWS_CATEGORY_KEYWORDS_TR = {
    "Şirket": [
        "şirket", "holding", "a.ş.", "kâr", "zarar", "bilanço", "ihale",
        "sözleşme", "genel müdür", "yönetim kurulu", "birleşme", "satın alma",
        "halka arz", "temettü", "iflas", "kap ", "borsa istanbul",
    ],
    "Politika": [
        "seçim", "hükümet", "meclis", "cumhurbaşkanı", "bakan", "yaptırım",
        "darbe", "protesto", "gerilim", "nato", "ab üyelik", "dış politika",
        "diplomasi", "savaş", "anayasa",
    ],
    "Ekonomi": [
        "faiz", "enflasyon", "tcmb", "merkez bankası", "kur", "dolar", "euro",
        "bütçe", "vergi", "ihracat", "ithalat", "cari açık",
        "kredi derecelendirme", "moody's", "fitch", "s&p", "deprem", "opec",
        "petrol", "doğalgaz", "asgari ücret", "işsizlik", "büyüme", "spk",
        "bddk", "hazine",
    ],
}

NEWS_CATEGORY_KEYWORDS_INTL = {
    "Şirket": [
        "ceo", "earnings", "merger", "acquisition", "ipo", "lawsuit",
        "antitrust", "bankruptcy", "profit", "revenue", "dividend",
        "buyback", "layoff", "quarterly results",
    ],
    "Politika": [
        "election", "sanction", "war", "geopolit", "president", "parliament",
        "brussels", "eu commission", "regulation", "policy", "diplomatic",
        "nato", "protest",
    ],
    "Ekonomi": [
        "rate cut", "rate hike", "interest rate", "fed", "federal reserve",
        "fomc", "ecb", "inflation", "cpi", "tariff", "trade war",
        "recession", "gdp", "jobs report", "unemployment", "opec",
        "oil price", "yield", "treasury", "dollar index", "eurozone",
        "stimulus", "debt ceiling", "central bank",
    ],
}

# --- TEFAS (Turkish investment fund) tracking ---
# TEFAS's public API no longer exposes fund portfolio holdings (which stocks
# a fund holds) -- only daily price/NAV and period returns. So this can't
# answer "which fund is buying which stock" (same gap as custody data, see
# README); it's a fund-performance tracker, not a smart-money signal. The
# "why is this fund profitable" text in the Fonlar page is inferred from the
# fund's own name (sector keywords) and, opportunistically, from a name-match
# against recent KAP "Pay Alım Satım Bildirimi" filers -- clearly hedged as a
# guess, never presented as fact.
FUND_WATCHLIST: list[str] = []  # add fund codes here, e.g. ["TTE", "AFA"]
FUND_LEADERBOARD_CATEGORY = "Hisse Senedi Şemsiye Fonu"  # equity umbrella funds
FUND_LEADERBOARD_METRICS = ["getiri1a", "getiri3a", "getiri1y"]  # 1mo/3mo/1y -- what the bulk list exposes
FUND_LEADERBOARD_RANK_METRIC = "getiri1a"
FUND_LEADERBOARD_COUNT = 15
FUND_DAILY_CHANGE_LOOKBACK_DAYS = 5  # per-fund price history window for computing day-over-day change

# Rough sector/theme inference from a fund's title -- used only to write a
# hedged one-line guess about why a top fund might be up, since real holdings
# data isn't available. Order matters: first match wins.
FUND_SECTOR_KEYWORDS = [
    ("İnşaat", ["inşaat", "gyo", "gayrimenkul"]),
    ("Bankacılık", ["banka", "bankacılık"]),
    ("Teknoloji", ["teknoloji", "bilişim"]),
    ("Enerji", ["enerji", "elektrik"]),
    ("Katılım (faizsiz)", ["katılım"]),
    ("Kıymetli Maden/Altın", ["altın", "kıymetli maden"]),
    ("Temettü odaklı", ["temettü"]),
    ("BIST 30", ["bist 30", "bist30"]),
    ("BIST 100 dışı / küçük-orta ölçek", ["bist 100 dışı", "ikinci", "bist100 dışı"]),
    ("Halka arz şirketleri", ["halka arz"]),
    ("Koç Topluluğu", ["koç topluluğu", "koç grubu"]),
    ("Sabancı Topluluğu", ["sabancı"]),
]

# Static informational note, NOT tax advice -- Turkish withholding-tax
# (stopaj) treatment of yatırım fonu gains depends on fund category and
# investor type and changes with legislation; verify current rules with a
# tax advisor / güncel mevzuat before relying on this.
FUND_TAX_NOTES = {
    "Hisse Senedi Şemsiye Fonu": (
        "Genel kural (2026 itibarıyla, gerçek kişi yerleşik yatırımcılar için): "
        "BIST hisselerinin en az %80'ini taşıyan hisse senedi yoğun fonlar "
        "stopajdan muaf tutulur. Bu genel bir bilgidir, yatırım/vergi "
        "tavsiyesi değildir -- güncel mevzuatı ve kendi durumunuzu kontrol edin."
    ),
    "_default": (
        "Diğer fon kategorilerinde (borçlanma araçları, para piyasası, karma, "
        "serbest vb.) genellikle stopaj uygulanır (oranlar zaman zaman "
        "değişebilir). Bu genel bir bilgidir, vergi tavsiyesi değildir."
    ),
}

# --- BIST Ekranı: top movers + "why is this moving" classification ---
BIST_SCREEN_TOP_N = 20
BIST_SCREEN_FR_LOOKBACK_DAYS = 5  # freshly-published financial report/earnings within this window -> "Bilanço"
BIST_SCREEN_SPARK_BARS = 30  # trading days of recent close prices attached to each stock for its mini trend chart

# Index-level charts shown at the top of BIST Ekranı. XUTUM ("BIST TÜM" --
# every listed company) has almost no history on yfinance (tested: 1 bar),
# so XU030 stands in as the "genel piyasa" reference alongside XU100.
BIST_INDICES = [
    {"key": "xu100", "label": "BIST 100", "ticker": "XU100.IS"},
    {"key": "xu030", "label": "BIST 30", "ticker": "XU030.IS"},
]
BIST_INDEX_PERIOD = "3mo"

# --- Senaryolar: one-shot buy-and-hold experiments ---
# Built once (2026-09-06) from that day's best combined signals (Öneriler
# ranking: bist_screen recommendation_score for stocks, 1mo return for
# funds), then held untouched for SCENARIO_HOLD_DAYS to see how the picks
# actually perform -- no rebalancing, no stop-loss, no new entries. This is
# deliberately NOT the same as the momentum/trend strategies above; it's a
# separate, independent pair of portfolios with their own state files.
SCENARIO_HOLD_DAYS = 7
SCENARIO_STOCK_ALLOCATION_PCT = 0.7  # used when a scenario has max_funds > 0; rest goes to funds
SCENARIO_COMMISSION_PCT = COMMISSION_PCT

# Senaryo 2 updated 06.09.2026: 100% stocks, no funds (max_funds=0 -> the
# full cash allocation goes to stocks regardless of SCENARIO_STOCK_ALLOCATION_PCT;
# see scenarios._build_portfolio).
SCENARIOS = {
    "scenario1": {"label": "Senaryo 1", "cash": 100_000.0, "max_stocks": 7, "max_funds": 3},
    "scenario2": {"label": "Senaryo 2", "cash": 10_000.0, "max_stocks": 3, "max_funds": 0},
}

# --- Senaryo 3: the "yaşayan" (living) scenario -- actively managed, not
# buy-and-hold. Reuses the exact same engine as the momentum strategy
# (momentum_trader.run_cycle: technical/volume/KAP/financials/ADX/Donchian
# checklist for entries, stop-loss/take-profit/fading-momentum for exits),
# just with its own capital and its own fully independent state. Stocks
# only (funds aren't part of the active checklist engine). Runs every
# hourly dashboard cycle, same as the momentum strategy.
SCENARIO3_LABEL = "Senaryo 3"
SCENARIO3_CASH = 100_000.0
SCENARIO3_MAX_POSITIONS = 10

# --- Öneriler ("Claude'nin seçimleri"): composite top picks from everything
# above. Ranks *signal agreement* (how many independent checks line up),
# not a return forecast -- there is no guarantee of "maximum" return, and
# this is not investment advice. Refreshed on the same cadence as the rest
# of the dashboard (hourly, market hours).
RECOMMEND_TOP_STOCKS = 15
RECOMMEND_TOP_FUNDS = 5
