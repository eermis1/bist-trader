# BIST Paper Trading Agent

Borsa İstanbul hisselerinde **sanal (paper)** alım-satım yapan bir sistem.
Gerçek para ile hiçbir işlem göndermez. Varsayılan evren: KAP'a kayıtlı ~759
BIST hissesinin tamamı (`config.UNIVERSE = "all"`); istenirse sadece BIST100
alt kümesiyle de çalıştırılabilir.

**Güncel durum (06.09.2026):** Ana takip sistemi **Senaryo 1/2/3**
çerçevesi (dashboard'un "AI Trader" sayfasında) -- aşağıdaki "Strateji 1" ve
"Strateji 2" bölümleri, o çerçeveden önce kurulan ve artık **emekli**
(otomatik çalıştırılmayan, ama kodu/state'i referans için duran) iki ilk
denemedir. Doğrudan Senaryo bölümüne (aşağıda) atlayabilirsiniz.

## [Emekli] Strateji 1: Trend-takip

- **Giriş:** 10 günlük ortalama, 50 günlük ortalamayı yukarı kesince VE RSI(14) > 55 ise.
- **Çıkış:** ortalamalar aşağı kesişince VEYA RSI < 35 olunca VEYA %12 stop-loss / %15 take-profit tetiklenince.
- **Pozisyon boyutu:** eşit ağırlık, aynı anda en fazla 10 pozisyon.

Bu parametreler `scripts/optimize.py` ile 216 kombinasyonluk bir grid-search
sonucu seçildi (Calmar oranına göre en iyi): 3 yıllık BIST100 verisinde
CAGR %34.3, max drawdown %-15.8, Sharpe 1.50, 289 işlem, %53 kazanma oranı
(varsayılan/ince-ayarsız parametrelerde: CAGR %16.2, DD %-22.7, Sharpe 0.88).
Tam tablo: `reports/optimization_results.csv`. Piyasa zamanla değiştiği için
periyodik olarak tekrar çalıştırmak mantıklı.

Tüm parametreler `bist_trader/config.py` içinde.

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Backtest çalıştırma

```bash
python scripts/run_backtest.py --years 3
```

Belirli hisselerle test etmek için:

```bash
python scripts/run_backtest.py --tickers THYAO,GARAN,ASELS
```

Sonuçlar `reports/` klasörüne (equity curve CSV + PNG grafik) kaydedilir.

### Parametre optimizasyonu

```bash
python scripts/optimize.py --years 3 --top 15 --rank calmar
```

Fiyat verisini bir kez çekip (`data/cache/` önbelleğinden) `config.py`
içindeki `GRID` sözlüğünde tanımlı tüm parametre kombinasyonlarını dener,
sonuçları `reports/optimization_results.csv`'ye kaydeder ve en iyi N'i
yazdırır. `--rank calmar|sharpe|cagr_pct|total_return_pct` ile sıralama
ölçütünü değiştirebilirsiniz. Izgarayı genişletmeden önce tek bir
kombinasyonun ne kadar sürdüğünü göz önünde bulundurun (~5sn/kombinasyon,
100 hissede).

## Strateji 1: Paper trading çalıştırma (sanal canlı işlem)

```bash
python scripts/run_paper_trading.py
```

Piyasa saatlerinde (10:00-18:00 Europe/Istanbul, hafta içi) periyodik olarak
fiyatları çeker, sinyalleri değerlendirir ve sanal portföyü günceller. Durum
`data/state/portfolio.json` dosyasında saklanır; script'i durdurup tekrar
başlatsanız bile kaldığı yerden devam eder. İşlem geçmişi `data/logs/trades.csv`
dosyasına yazılır.

Tek seferlik bir döngü için (örn. Windows Görev Zamanlayıcı ile günde bir kez
tetiklemek isterseniz):

```bash
python scripts/run_paper_trading.py --once
```

## Günlük radar: yüksek risk / momentum + KAP taraması

```bash
python scripts/run_daily_radar.py --universe all --kap-days 3
```

Bu **ayrı ve bağımsız** bir izleme aracıdır — hiçbir şeyi otomatik satın almaz,
sadece dikkat çekmesi gereken hisseleri sıralı bir liste halinde sunar. İki
sinyali birleştirir:

1. **Fiyat momentumu:** günün en çok yükselen 20 hissesi + günlük limite
   yakın/ulaşmış olanlar (`config.NEAR_LIMIT_THRESHOLD_PCT`, varsayılan %9).
   Not: veri yfinance EOD/gecikmeli olduğu için bu, "kapanışta tavana yakın
   kapandı" tespitidir -- gün içinde "tavana yaklaşıyor" anlık alarmı değildir.
2. **KAP bildirimleri:** kap.org.tr'nin herkese açık bildirim sorgu API'sinden
   son N güne ait, önceliklendirilmiş bildirim türleri (`config.KAP_HIGH_PRIORITY_SUBJECTS`):
   - `Pay Alım Satım Bildirimi` -- bir yatırım kuruluşunun/kişinin payı
     düzenleyici eşiği (SPK mevzuatındaki oy hakkı/sermaye oranları) geçtiğinde
     zorunlu yapılan bildirim. Örn. Tera Portföy'ün bir hisseye giriş yapması
     tam olarak bu kategoride görünür.
   - `Olağan Dışı Fiyat ve Miktar Hareketleri` -- Borsa İstanbul/KAP'ın kendi
     "anormal fiyat/hacim hareketi" tespiti.
   - Ayrıca pay alım teklifi, halka arzda %5 üstü alım, birleşme vb.

Her hisse için bir `priority_score` hesaplanır (tavana yakınlık + üst-20
listesi + KAP bayrakları) ve `reports/daily_radar_<tarih>.csv` dosyasına
kaydedilir. Script'in ürettiği tüm yüksek öncelikli KAP bildirimleri (fiyat
henüz hareket etmemiş olsa bile) ayrıca ayrı bir tabloda listelenir.

## [Emekli] Strateji 2: Momentum/KAP otomatik paper trading (10.000 TL, maks 3 pozisyon)

Bu stratejinin motoru **emekli değil** -- tam tersine, `momentum_trader.py`
artık genelleştirilmiş bir `run_cycle()` fonksiyonu olarak Senaryo 3'ün
altyapısını oluşturuyor (bkz. "Senaryo 3" bölümü). Emekli olan sadece bu
bölümdeki **kendi 10.000 TL'lik portföyü** -- artık zamanlanmış görev
tarafından tetiklenmiyor, dashboard'da gösterilmiyor.

```bash
python scripts/run_momentum_trading.py --once      # tek döngü
python scripts/run_momentum_trading.py              # piyasa açıkken sürekli (varsayılan: saatte bir)
```

Yukarıdaki radar taramasını (top-20 yükselen + tavana yakın) aday havuzu
olarak kullanır, ama **hiçbir adayı doğrudan almaz** -- her biri şu 4
kriterden geçmeli:

1. **Teknik alım noktası** (zorunlu): fiyat, yükselen bir 20 günlük ortalamanın
   üzerinde VE RSI 50-85 bandında (aşırı alım değil). Yani bugünkü sıçrama
   mevcut bir yükseliş trendi *içinde* mi, yoksa düşüş trendine karşı mı.
2. **Hacim** (zorunlu): bugünkü hacim, son 20 günlük ortalamanın en az 1.5
   katı -- ince/manipülatif bir sıçrama değil, gerçek katılım.
3. **KAP desteği**: son 5 günde bu hisse için yüksek öncelikli bir KAP
   bildirimi var mı (yukarıdaki radar bölümündeki kategoriler).
4. **Bilanço desteği**: yfinance üzerinden son çeyrek net kâr pozitif MI,
   ya da net kâr çeyrek bazında iyileşiyor VE gelir ciddi şekilde
   daralmıyor mu. Küçük şirketlerde bu veri bazen mevcut değil -- o
   durumda bu kriter ne engelleyici ne destekleyici sayılır (nötr).

Ayrıca (06.09.2026'da, teknik analiz araştırması sonrası eklendi -- ikisi de
zorunlu değil, sadece skora katkı sağlar):

5. **ADX (trend gücü):** RSI/MA sadece yönü söyler, ADX(14) > 25 ise bu
   yönün gürültü değil gerçek bir trend olduğunu doğrular.
6. **Donchian kırılımı:** kapanış son 20 günün en yükseğini kırmış mı --
   "tavan/zirve" fikrine MA kesişiminden çok daha doğrudan oturan, klasik
   Turtle Trading tarzı bir kontrol.

**Karar kuralı** (`config.py`'den ayarlanabilir): Hacim zorunlu, Teknik
zorunlu değil (skora dahil ama engellemiyor -- ilk test 04.09.2026'da
teknik zorunluyken KAP+hacim onaylı MIATK bile engellenmişti, o yüzden
gevşetildi), ayrıca {KAP, Bilanço} ikilisinden en az
`MOMENTUM_MIN_SUPPORT_CHECKS` (varsayılan 1) tanesi de sağlanmalı. Geçen
adaylar skora göre sıralanır (KAP ağırlığı en yüksek), en yüksek skorlu
adaylar boş slotlara (maks 3) eşit ağırlıkla (~3.333 TL/pozisyon) girilir.

**Çıkış:** %7 stop-loss / %25 take-profit, VEYA RSI 45'in altına düşerse,
VEYA fiyat 20 günlük ortalamanın altına inerse ("momentum soluyor").

Durum `data/state/momentum_portfolio.json`'da saklanır (trend stratejisinden
tamamen ayrı); her işlemin hangi kriterleri geçtiği `data/logs/momentum_trades.csv`'ye
yazılır, böylece "neden alındı" her zaman geriye dönük izlenebilir.

### Otomatik çalışma (Windows Görev Zamanlayıcı)

`BIST_Momentum_PaperTrading` adıyla bir görev kuruldu (isim tarihsel, artık
sadece bu eski stratejiyle sınırlı değil): hafta içi günde **3 kez (12:00,
15:00, 18:00)** **`scripts/run_dashboard_cycle.py`** çalıştırır
(07.09.2026'da saatlik taramadan bu 3 sabit saate düşürüldü; script'in
kendisi 06.09.2026'da `run_momentum_trading.py`'den değiştirilmişti --
o script hâlâ var ve elle çalıştırılabilir, ama artık zamanlanmış değil).
Bu tek script içinde Senaryo 3'ün aktif alım-satım turu + Senaryo 1/2'nin
fiyat yenilemesi + dashboard'un diğer tüm sayfaları (BIST Ekranı, Fonlar,
Haberler, Öneriler) tetiklenir. Bilgisayar açık/uyku modunda ve `evren`
kullanıcısı oturum açmış olmalı -- "bilgisayarı uyandır" ayarı açık.
Zaman sınırı 30 dakika (Senaryo 3'ün eklenmesiyle döngü uzadığı için
06.09.2026'da 14'ten yükseltildi). Yönetmek için:

```powershell
Get-ScheduledTask -TaskName "BIST_Momentum_PaperTrading"        # durumu gör
Disable-ScheduledTask -TaskName "BIST_Momentum_PaperTrading"    # geçici durdur
Enable-ScheduledTask -TaskName "BIST_Momentum_PaperTrading"     # tekrar aç
Unregister-ScheduledTask -TaskName "BIST_Momentum_PaperTrading" -Confirm:$false  # tamamen kaldır
```

Ya da Görev Zamanlayıcı GUI'sinden ("Task Scheduler" ara, "Task Scheduler
Library" altında bulunur). Bilgisayar uyku modundayken de çalışabilsin diye
"bilgisayarı uyandır" (`WakeToRun`) ayarı açık -- tamamen kapalıyken yine de
çalışmaz.

## Dashboard: "AI Trader"

```bash
python scripts/generate_dashboard.py
```

Bu komut normalde gerekmez -- `scripts/run_dashboard_cycle.py` (saatlik
zamanlanmış görev) her döngü sonunda otomatik çağırır. Üretilen dosyalar:

- **`reports/dashboard.html`** -- her zaman güncel, kendi kendine yeten
  (veri gömülü) yerel dosya. Masaüstünde **"AI Trader"** kısayolu bu
  dosyayı açar. Asıl güvenilir kaynak budur.
- `reports/dashboard_data.json` -- aynı verinin ham JSON hali.
- Ayrıca ayrı bir konuşmada `https://claude.ai/code/artifact/...` altında
  paylaşılabilir bir **snapshot** de yayınlandı -- bu link'in tazelenmesi
  Claude'un elle yeniden yayınlamasını gerektirir (bkz. "Başka
  bilgisayardan erişim" altında).

Dashboard **7 sekmeden** oluşuyor (McKinsey'vari lacivert/koyu tema, sabit
koyu -- sistem ayarına bakmaz), tümü tek bir self-contained HTML
dosyasında, bu sırayla: **Balance Sheet – Senaryo 2** (varsayılan/ilk sekme),
Haberler, BIST Ekranı, Fonlar, Öneriler, Senaryo 1, Senaryo 3. Senaryo 1
sekme başlığı amber/altın, Senaryo 3 yeşil renkte -- al-ve-tut (1) ile
aktif-yönetim (3) arasındaki farkı sekme çubuğunda bile görünür kılmak için
(06.09.2026).

Şablon: `bist_trader/templates/dashboard_template.html` (tasarım/CSS +
sekme mantığı burada); veri toplama: `bist_trader/dashboard.py`.

> **Not (06.09.2026):** Eskiden ilk sekme "Bilançomuz" idi ve
> `momentum_trader.py`'nin kendi 10.000 TL'lik portföyünü gösteriyordu.
> Senaryo 1/2/3 çerçevesi kurulduktan sonra bu, aynı 10.000 TL tutarındaki
> Senaryo 2 ile karıştığı için kaldırıldı -- o portföy artık zamanlanmış
> görev tarafından çalıştırılmıyor, dashboard'da gösterilmiyor (bkz. yukarıda
> "[Emekli] Strateji 2"). Portföy/pozisyon görünümü artık Senaryo 1/2/3
> sekmelerinde.

### 1. BIST Ekranı

`bist_trader/bist_screen.py` -- günün en çok yükselen/tavana yakın
`config.BIST_SCREEN_TOP_N` (varsayılan 20) hissesi, her biri **tek bir
değerlendirme etiketiyle** (ilk uyan kazanır):

1. **Bilanço** -- son `config.BIST_SCREEN_FR_LOOKBACK_DAYS` günde KAP'a
   "Finansal Rapor" (bilanço/faaliyet sonucu) düşmüş mü (market-genelinde
   tek toplu KAP sorgusu).
2. **Haber/KAP** -- yüksek öncelikli bir KAP bildirimi var mı (Pay Alım
   Satım Bildirimi, Olağan Dışı Fiyat/Miktar Hareketi, birleşme vb. --
   Strateji 2'deki aynı liste).
3. **Teknik/Hacim** -- `momentum.py`'deki teknik-trend, hacim-sıçraması,
   ADX (trend gücü) veya Donchian (N-günlük kırılım) kontrollerinden en az
   biri geçiyor mu.
4. **Spekülatif** -- yukarıdakilerin hiçbiri bulunamadı. Bu bir manipülasyon
   iddiası değil, sadece "kamuya açık veriyle bir açıklama bulamadım" demek.

Bu bir alım listesi değil, **araştırma başlangıç noktası** ("adaylarımız").
Test çalıştırmasında TGSAS gerçekten aynı gün taze bir Finansal Rapor
bildirimiyle eşleşip doğru şekilde "Bilanço" etiketi aldı.

Her kart ayrıca (yfinance üzerinden, 30 gün önbelleklenmiş) **şirketin ne iş
yaptığını** (sektör + kısa açıklama), **gerçek hacim rakamlarını** (bugünkü
hacim, 20 günlük ortalama, oran) ve sağ üstte son `config.BIST_SCREEN_SPARK_BARS`
(varsayılan 30) günlük **mini trend grafiğini (sparkline)** gösterir; tüm
bunlar tek bir "olası neden" cümlesinde birleştirilir. Aynı kartlar Öneriler
sayfasında da kullanılır (bkz. aşağıda).

Sayfanın en üstünde **Piyasa Görünümü** paneli var: `config.BIST_INDICES`
(varsayılan BIST 100 / XU100.IS ve BIST 30 / XU030.IS -- "BIST TÜM"/XUTUM'un
yfinance'te neredeyse hiç geçmiş verisi yok, test edildi: 1 bar) için
son ~3 aylık trend grafiği ve günlük değişim.

### 2. Fonlar

`bist_trader/funds.py`, TEFAS'ın (Türkiye Elektronik Fon Alım Satım
Platformu) herkese açık API'sinden fon verisi çeker:

- **Takip listesi:** `config.FUND_WATCHLIST`'e fon kodu ekleyerek (örn.
  `["THF", "TTE"]`) belirli fonları günlük fiyat + günlük değişim + kategori
  sırasıyla takip edin. Varsayılan boş -- hangi fonları izlemek istediğinizi
  söylerseniz kod listesini ben eklerim.
- **Lider tablosu:** "Hisse Senedi Şemsiye Fonu" kategorisindeki ~1000
  fonun tamamı tek API çağrısıyla, 1 Ay / 3 Ay / 1 Yıl getirisiyle birlikte
  (1 Ay'a göre sıralı, en iyi/kötü 15). İlk test çalıştırmasında en iyi fon
  **THF -- TERA PORTFÖY HİSSE SENEDİ FONU, +%29,4** çıktı.
- **Vergi notu:** her kategori için genel bir stopaj bilgisi gösterilir
  (`config.FUND_TAX_NOTES`) -- **yatırım/vergi tavsiyesi değildir**, güncel
  mevzuatı kontrol edin.
- **"Olası neden" (tahmini):** en iyi 15 fon için fon adındaki sektör/tema
  ipuçlarından (`config.FUND_SECTOR_KEYWORDS`) ve KAP'taki "Pay Alım Satım
  Bildirimi" filerlarıyla isim eşleştirmesinden bir cümlelik, açıkça hedge'li
  bir tahmin üretilir (örn. THF için: bu fonu yöneten TERA PORTFÖY'ün KAP'a
  yaptığı son bildirimlere referans). **Kesin bir neden-sonuç kanıtı değil.**

**Önemli kısıt (değişmedi):** TEFAS'ın eski API'si fon **portföy içeriğini**
de yayınlıyordu; bu artık kamuya kapatılmış. "Hangi fon hangi hisseye
giriyor" sorusunun kesin cevabı hâlâ yalnızca KAP'ın `Pay Alım Satım
Bildirimi` kategorisinde veya ücretli bir takas veri aboneliğinde.

### 3. Haberler

`bist_trader/news.py` -- **TR / US / EU** üç bölge, her biri kendi içinde
üç kategoriye ayrılmış, ekranda **Politika / Ekonomi / Şirket** sırasıyla
gösterilir (toplam 9 hücre; Şirket bilinçli olarak sona alındı).
Kaynaklar (`config.NEWS_SOURCES_*`, hepsi ücretsiz RSS/Atom, API anahtarı
gerekmez):

- **TR:** NTV Ekonomi, Sabah Ekonomi, BloombergHT -- ayrıca **Şirket**
  sütunu KAP'ın kendi yüksek öncelikli bildirimleriyle zenginleştirilir
  (genel basından çok daha BIST-spesifik bir kaynak).
- **US:** Federal Reserve (resmi), CNBC Economy, Investing.com, WSJ World.
- **EU:** ECB (resmi), Euronews Business, POLITICO Europe.

Her haber, bölgesine özel bir anahtar kelime haritasından
(`config.NEWS_CATEGORY_KEYWORDS_TR` / `_INTL`) geçirilip ilk uyan kategoriye
yazılır; hiçbirine uymayan haber gösterilmez -- yani kategori anahtar
kelimeleri aynı zamanda genel alaka filtresidir. TCMB'nin resmi bir RSS'i
bulunamadı; Türkiye tarafı bu yüzden gazete/kanal kaynaklarına dayanıyor.

**Dikkat (giderilen bir hata):** Python'un `.lower()` fonksiyonu Türkçe
büyük "İ" harfini yanlış küçültüyor (bir birleştirici nokta karakteri
ekliyor), bu da "İnşaat", "İhracat" gibi kelimelerin anahtar kelime
eşleşmelerini sessizce kaçırmasına yol açıyordu. `news.py` ve `funds.py`'de
düzeltildi -- Türkçe metinle `.lower()` kullanan yeni kod eklerken bu tuzağa
dikkat edin.

### 4. Öneriler — "Claude'nin Seçimleri"

Yukarıdaki tüm sayfaların sinyallerini birleştiren bir özet: **Top 15 hisse
+ Top 5 fon**. Hisse sıralaması, `bist_screen.py`'nin ürettiği
`recommendation_score`'a göre yapılır -- bilanço (3), KAP/haber (2), ADX (1),
Donchian kırılımı (1.5), teknik (1), hacim (1) ağırlıklarıyla toplanan bir
"kaç bağımsız sinyal üst üste biniyor" puanı (aynı kartlar BIST Ekranı'yla
paylaşılır, sadece sıralama ölçütü farklı). Fon sıralaması, Fonlar
sayfasındaki 1 aylık getiri lider tablosunun ilk 5'idir.

**Bu bir getiri tahmini/garantisi değildir** -- sadece elimizdeki kamuya açık
sinyallerden kaçının aynı hisse/fonda çakıştığını gösterir. Dashboard'un geri
kalanıyla aynı döngüde (hafta içi günde 3 kez: 12:00, 15:00, 18:00)
otomatik yenilenir; ayrıca bir işlem tetiklemez, sadece görüntüler.

### 5 & 6. Senaryo 1 / Senaryo 2 — "al ve tut" deneyleri

`bist_trader/scenarios.py` -- momentum/trend stratejilerinden tamamen
**bağımsız**, kendi state dosyalarına sahip iki deney portföyü:

| | Senaryo 1 | Senaryo 2 |
|---|---|---|
| Sermaye | 100.000 TL | 10.000 TL |
| Hisse pozisyonu | 7 | 3 |
| Fon pozisyonu | 3 | **0** |

**Nasıl çalışır:** Her senaryo **sadece bir kez** kurulur -- o günün
Öneriler sıralamasından (hisseler için `recommendation_score`, "Spekülatif"
etiketliler elenerek; fonlar için 1 aylık getiri) en iyi adaylar seçilir.
Senaryo 1'de sermayenin `config.SCENARIO_STOCK_ALLOCATION_PCT`'i (varsayılan
%70) hisselere, kalanı fonlara eşit ağırlıkla dağıtılır. **Senaryo 2
06.09.2026'da güncellendi: `max_funds=0`, yani sermayenin %100'ü hisselere
gidiyor, hiç fon almıyor** (`scenarios._build_portfolio`'da `max_funds<=0`
ise fon bütçesi otomatik hisselere kayar). Sonraki her döngüde (günde 3 kez)
sadece **fiyatlar güncellenir** -- yeni alım, satış, stop-loss, yeniden
dengeleme **yok**. `config.SCENARIO_HOLD_DAYS` (varsayılan 7) gün sonra
"deneme tamamlandı" rozeti çıkar; devamında ne yapılacağına o zaman birlikte
karar veririz.

Fon fiyatları `tefas.Crawler` ile, hisse fiyatları normal yfinance akışıyla
güncellenir. Her pozisyon kartında "neden seçildiği" (BIST Ekranı/Fonlar
sayfasındaki gerekçe metninin bir özeti) gösterilir, böylece bir hafta sonra
"bu seçim gerçekten neye dayanıyordu" sorusu geriye dönük cevaplanabilir.

Yeniden kurmak (örn. farklı bir günün sinyalleriyle baştan başlamak)
isterseniz `data/state/scenario1_portfolio.json` /
`data/state/scenario2_portfolio.json` dosyalarını silmeniz yeterli --
bir sonraki döngüde o günün en iyi sinyalleriyle yeniden kurulur.

### 7. Senaryo 3 — "yaşayan" (aktif yönetilen) portföy

Senaryo 1/2'nin aksine **al-ve-tut değil**. `bist_trader/scenario3.py`,
momentum stratejisiyle (`momentum_trader.py`) **birebir aynı motoru**
(`momentum_trader.run_cycle` -- teknik + hacim + KAP + bilanço + ADX +
Donchian checklist, stop-loss/take-profit/momentum-soluyor ile çıkış)
çalıştırır, ama:

- Kendi sermayesi: **100.000 TL**, maks **10 pozisyon** (momentum
  stratejisinin 10.000 TL / 3 pozisyonluk portföyünden tamamen ayrı).
- Kendi state/trade-log dosyaları: `data/state/scenario3_portfolio.json`,
  `data/logs/scenario3_trades.csv`.
- Sadece hisse (Senaryo 1/2'nin aksine fon almaz).
- Her saatlik döngüde (`dashboard.build_snapshot()` içinden tetiklenir --
  ayrı bir Görev Zamanlayıcı görevi gerekmez) tam bir tarama+değerlendirme+
  al/sat turu yapar.

Bu, mimariyi tekrar kullanan bir refactor sayesinde mümkün oldu:
`momentum_trader.py`'deki asıl motor artık `run_cycle(portfolio, state_file,
trade_log_file, tag)` olarak parametrik -- momentum stratejisinin kendi
`run_once()`'u da, Senaryo 3'ün `run_once()`'u da aynı fonksiyonu farklı
state dosyalarıyla çağırıyor. Aynı checklist/exit mantığında ileride bir
düzeltme yaparsanız, her iki portföye de otomatik yansır.

**Performans notu:** Senaryo 3 kendi tam BIST taramasını yaptığı için
(momentum stratejisininkinden ayrı, ama önbellek büyük ölçüde paylaşılıyor)
saatlik döngü artık daha uzun sürüyor -- bu yüzden Görev Zamanlayıcı'nın
zaman sınırı 30 dakikaya çıkarıldı (06.09.2026). İleride iki motorun aynı
tarama sonucunu paylaşması (şu an ayrı ayrı taranıyor) bir optimizasyon
fırsatı.

## Başka bilgisayardan / telefondan erişim

İki seçenek var, ikisinin de sınırı farklı:

1. **OneDrive senkronizasyonu (önerilen, ek kurulum yok):** Bu proje zaten
   `OneDrive\Desktop\Agent_Workspace\bist_trader` altında, yani
   `reports/dashboard.html` her yenilendiğinde OneDrive'a senkronize olur.
   **Aynı OneDrive hesabıyla giriş yapılmış başka bir Windows/Mac
   bilgisayarda** (OneDrive masaüstü uygulaması kuruluysa) dosya orada da
   otomatik belirir -- tarayıcıda açtığınızda bu bilgisayardakiyle birebir
   aynı, güncel içeriği görürsünüz. Telefonda OneDrive uygulamasından dosyayı
   indirip tarayıcıda açmanız gerekebilir (OneDrive'ın kendi önizlemesi
   `.html` dosyalarını çoğu zaman canlı sayfa olarak değil, indirilecek dosya
   olarak gösterir -- test edilmedi, garanti değil).
2. **Yayınlanan link** (`https://claude.ai/code/artifact/...`): Herhangi bir
   cihaz/tarayıcıdan, OneDrive'a ihtiyaç olmadan açılır. Ama bu bir
   **anlık görüntü** -- ben elle yeniden yayınlamadıkça güncellenmez (bu
   konuşma boyunca birkaç kez elle yaptım). Claude'un otomatik bulut
   zamanlama özelliği (`/schedule`) bunun için kullanılamadı çünkü bulutta
   çalışıyor ve bu bilgisayardaki yerel dosyalara erişemiyor.

Gerçekten her yerden, otomatik ve her zaman güncel bir erişim isterseniz,
üçüncü bir yol var ama ek kurulum gerektiriyor: proje bir GitHub deposuna
bağlanır, yerel Görev Zamanlayıcı her döngüde `dashboard_data.json`'ı oraya
gönderir (push), ve Claude'un bulut zamanlamasına bağlı ayrı bir görev bu
depodan okuyup link'i otomatik tazeler. İsterseniz kurarız -- GitHub hesabı
gerektirir.

### Takas (aracı kurum bazlı) verisi hakkında

Hangi aracı kurumun bir hisseye ne kadar girdiğini gösteren "takas dağılımı"
verisi, 1 Ocak 2025'ten itibaren Borsa İstanbul tarafından **ücretli veri
yayın lisansına** bağlandı (Fintables, Matriks, Finnet2000Plus gibi
sağlayıcılar üzerinden erişilebiliyor). Ücretsiz/açık bir API bulunmuyor.
Böyle bir aboneliğiniz varsa (API erişimi olan biri), bir `custody.py` modülü
yazıp aynı şekilde radar'a KAP gibi bir sinyal olarak ekleyebiliriz -- KAP'taki
`Pay Alım Satım Bildirimi` bildirimleri bu boşluğu büyük ölçüde dolduruyor
zaten (bkz. yukarıdaki Tera Portföy örneği).

## Veri kaynağı ve sınırlamalar

- Fiyatlar [yfinance](https://github.com/ranaroussi/yfinance) üzerinden Yahoo
  Finance'ten çekilir; `.IS` uzantılı BIST sembolleri kullanılır (örn. `THYAO.IS`).
  Bu veri genelde 15-20 dakika gecikmelidir — gerçek zamanlı emir yürütme için
  **uygun değildir**, backtest ve paper trading için yeterlidir.
- `data/bist100_tickers.csv` (BIST100) ve `data/bist_all_tickers.csv` (tüm
  KAP-kayıtlı ~759 BIST hissesi, [pykap](https://github.com/cemsinano/pykap)
  kütüphanesinin paketlediği listeden üretildi) birer anlık görüntüdür.
  `data/bist_all_tickers.csv` bazı fon/GYO/likit olmayan kodlar da içerir --
  bunlar yfinance'te veri dönmezse `data.fetch_universe` otomatik olarak atlar.
- KAP bildirimleri `kap.org.tr`'nin kendi herkese açık (girişsiz) sorgu
  API'sinden çekilir -- bir API anahtarı gerekmez, ama site sahibinin altyapısı
  olduğu için makul bir istek sıklığında kalın.
- **Düzeltilmiş bir önbellek hatası (06.09.2026):** `data.py`'deki fiyat
  önbelleği eskiden yalnızca `ticker+interval`'e göre anahtarlanıyordu --
  `period` dahil değildi. Bu yüzden örn. `period="5d"` ile yapılan bir
  tarama, hemen ardından aynı hisse için `period="6mo"` isteyen bir teknik/
  hacim hesabının önbelleğini "kirletebiliyordu" (sessizce 5 günlük veri
  dönerdi, hata vermezdi). Artık `period` de anahtarın parçası. Yeni kod
  eklerken `data.fetch_history`'yi farklı `period` değerleriyle aynı anda
  kullanıyorsanız bu tuzağı unutmayın.

## Gerçek parayla işlem (henüz kurulmadı)

Bu sistem şu an **sadece paper trading** yapıyor. Gerçek emir göndermek
isterseniz:

1. Bir broker API'si edinin (BIST için Python ile en yaygın kullanılan seçenek:
   AlgoLab / Deniz Yatırım).
2. `bist_trader/execution.py` adında yeni bir modül yazıp broker'ın
   `place_order(ticker, side, qty)` fonksiyonunu implemente edin.
3. Bunu `paper_trader.py` içindeki giriş/çıkış noktalarına, açıkça bir
   config bayrağı (`LIVE_TRADING_ENABLED`) ile korumalı şekilde bağlayın.
4. Küçük pozisyon boyutlarıyla ve yakın takiple başlayın.

Bu adım kritik bir risk sınırı taşıdığı için hazır olduğunuzda ayrıca
konuşarak ilerlemek daha güvenli olur.

## Sorumluluk reddi

Bu sistem eğitim/araştırma amaçlıdır, yatırım tavsiyesi değildir. Geçmiş
performans gelecekteki getiriyi garanti etmez. Gerçek parayla kullanmadan
önce stratejiyi uzun süre paper trading'de test edin.
