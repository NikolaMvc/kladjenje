# BetAdvisor – Specifikacija projekta

## 1. Pregled projekta

**BetAdvisor** je mobilna web aplikacija (PWA) koja prikuplja sportske statistike sa
FlashScore, SofaScore i LiveScore platformi koristeći Scrapling biblioteku, analizira ih
algoritmom i prikazuje korisniku JEDAN najsigurniji tip kladjenja za svaku utakmicu —
uz potpuno objašnjenje zašto je taj tip odabran.

---

## 2. Korisnički interfejs

### 2.1 Filozofija dizajna
- **Fiksiran layout** — aplikacija zauzima tačno 100% visine ekrana (100dvh). Telo
  aplikacije se NIKAD ne skroluje. Jedini elementi koji se skroluju su liste utakmica
  unutar odgovarajućih panela.
- Vizuelni uzor: **Flashscore mobilna aplikacija** (tamna tema, kompaktne kartice,
  boje: tamnosiva pozadina #1a1a2e, narandžasta akcent #e8a020, bela/svetlosiva tekst).
- **Bottom navigation bar** sa 3 taba: Predstojeće | Uživo | Istorija

### 2.2 Gornji bar (Header)
```
[ BetAdvisor ]   [🔔]  [⚙]
Predstojeće  |  Uživo  |  Istorija
─────────────────────────────────
```

### 2.3 Tab: Predstojeće utakmice
- Lista kartica utakmica grupisanih po ligi/takmičenju.
- Svaka kartica prikazuje:
  ```
  Liga / Takmičenje                  [vreme]
  Tim domaćin   -  Tim gost
  ────────────────────────────────
  🎯 Tip: Oba tima daju gol (BTTS)   ★★★★☆
  ```
- Zvezdice (1-5) = nivo poverenja (confidence score).
- Klik na karticu → **Detail modal** (vidi sekciju 2.5).
- Badge "NOVO" ako su stigle sveže vesti/povrede u zadnjih 2h.

### 2.4 Tab: Uživo utakmice
- Lista aktivnih utakmica u realnom vremenu.
- Auto-refresh svakih 60 sekundi.
- Svaka kartica:
  ```
  Liga                          [45'+]
  Tim1  2  -  1  Tim2
  ────────────────────────────────
  🎯 Tip: Tim1 pobeda                ★★★☆☆
  xG: 1.8 - 0.7 | Šutevi: 8-3
  ```
- Klik → Detail modal sa live statistikama.

### 2.5 Detail Modal (klick na utakmicu)
Prikazuje se kao full-screen drawer odozdo:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Liga                  [datum/vreme]
  Tim domaćin   vs   Tim gost
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 PREPORUČENI TIP
  [Oba tima daju gol - BTTS]   ★★★★☆ (78%)

📋 OBJAŠNJENJE
  Domaćin je dao gol u 4/5 poslednjih domaćih
  utakmica. Gost je primio gol u 5/5 poslednjih
  gostujućih. H2H: oba tima su dala gol u 3/4
  međusobnih utakmica.

📊 FORMA DOMAĆINA (kod kuće, liga)
  ✅ 2-1 vs XYZ  ✅ 1-0 vs ABC
  ❌ 0-2 vs DEF  ✅ 3-1 vs GHI  ✅ 1-1 vs JKL
  Prosek golova: 1.6 dao / 0.8 primio

📊 FORMA GOSTA (u gostima, liga)
  ✅ 1-2 vs MNO  ❌ 0-3 vs PQR
  ✅ 2-2 vs STU  ✅ 1-1 vs VWX  ❌ 0-1 vs YZA
  Prosek golova: 0.8 dao / 1.6 primio

📰 VESTI I POVREDE
  ⚠️ Kapiten domaćina [Ime] upitan za nastup
  ✅ Nema suspenzija

🔄 H2H (poslednjih 5)
  Tim1 2-1 Tim2 | Tim2 1-0 Tim1 | ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2.6 Tab: Istorija
- Lista prethodnih tipova sa oznakama ✅/❌/⏳ (prošlo/nije/još traje).

---

## 3. Arhitektura sistema

```
┌─────────────────────────────────────┐
│          Browser (Mobile)           │
│     Vanilla JS + CSS (Fixed UI)     │
└────────────────┬────────────────────┘
                 │ HTTP / WebSocket
┌────────────────▼────────────────────┐
│         FastAPI Backend             │
│  /api/upcoming  /api/live           │
│  /api/match/<id>  /api/refresh      │
└──┬──────────────┬───────────────────┘
   │              │
┌──▼──────┐  ┌───▼──────────────────┐
│ Scraper │  │  Betting Analyzer    │
│ Module  │  │  (Python algorithm)  │
└──┬──────┘  └───────────────────────┘
   │
┌──▼──────────────────────────────────┐
│ Scrapling (StealthyFetcher +        │
│           DynamicFetcher)           │
│                                     │
│  flashscore.com                     │
│  sofascore.com                      │
│  livescore.com/en/                  │
└─────────────────────────────────────┘
```

---

## 4. Backend – Scrapling scraper modul

### 4.1 Opšte napomene
- Koristiti `StealthyFetcher` za stranice sa Cloudflare zaštitom.
- Koristiti `DynamicFetcher` za JS-rendered sadržaj.
- Paralelno scrapin sva tri sajta za isti skup utakmica i agregirati rezultate.
- Keš sve podatke u memoriji (dict sa timestamp-om) — TTL 5 min za predstojeće,
  60 sec za uživo.

### 4.2 Šta scraper prikuplja

#### Za predstojeće utakmice (po timu):
| Podatak | Izvor |
|---|---|
| Poslednjih 5 utakmica domaćina KOD KUĆE u ligi (rezultat, golovi, xG ako postoji) | FlashScore / SofaScore |
| Poslednjih 5 utakmica domaćina U GOSTIMA u ligi | FlashScore / SofaScore |
| Poslednjih 5 utakmica gosta KOD KUĆE u ligi | FlashScore / SofaScore |
| Poslednjih 5 utakmica gosta U GOSTIMA u ligi | FlashScore / SofaScore |
| H2H poslednjih 5 međusobnih utakmica | FlashScore |
| Tabela lige (pozicija, forma, golovi+/-) | LiveScore / SofaScore |
| Vesti i povrede (web search) | DuckDuckGo scrape / Google News |

#### Za uživo utakmice:
| Podatak | Izvor |
|---|---|
| Trenutni rezultat i minut | FlashScore |
| Posedovanje lopte % | SofaScore |
| Šutevi na gol / van gola | SofaScore |
| Očekivani golovi (xG) | SofaScore |
| Korneri | FlashScore / SofaScore |
| Žuti/crveni kartoni | FlashScore |
| Opasni napadi | FlashScore |
| Promene (izmene igrača) | FlashScore |

---

## 5. Betting Analyzer – Algoritam

### 5.1 Za predstojeće utakmice

#### Korak 1 – Forma (Form Score)
```python
# Za svaki tim izračunaj form_score iz poslednjih 5 utakmica
# kod kuće (domaćin) odnosno u gostima (gost)
POBEDA = 3 poena, REMI = 1, PORAZ = 0
home_form  = sum(poeni_domaćin_kod_kuće) / 15  # normalizovano 0-1
away_form  = sum(poeni_gost_u_gostima)  / 15
```

#### Korak 2 – Golovi (Goal Stats)
```python
home_avg_scored_home   = prosek golova koje je domaćin dao KK
home_avg_conceded_home = prosek golova koje je domaćin primio KK
away_avg_scored_away   = prosek golova koje je gost dao UG
away_avg_conceded_away = prosek golova koje je gost primio UG

expected_home_goals = (home_avg_scored_home + away_avg_conceded_away) / 2
expected_away_goals = (away_avg_scored_away + home_avg_conceded_home) / 2
expected_total      = expected_home_goals + expected_away_goals
```

#### Korak 3 – BTTS verovatnoća
```python
btts_prob = P(domaćin da gol) * P(gost da gol)
# P(tim da gol) = broj utakmica gde je tim dao makar 1 gol / 5
```

#### Korak 4 – H2H analiza
```python
h2h_home_wins   = % pobeda domaćina u H2H
h2h_draws       = % remija
h2h_btts        = % utakmica gde su oba dala gol
h2h_over25      = % utakmica sa 3+ gola
```

#### Korak 5 – Vesti/Povrede (News Penalty)
```python
# Ako nema bitnog igrača domaćina → penalty -10% na home_form
# Ako nema bitnog igrača gosta → penalty -10% na away_form
# "Bitan igrac" = kapiten, top scorer, goalkeeper
```

#### Korak 6 – Scoring za svaki market
Računamo confidence_score (0-100%) za svaki od sledećih marketa:

| Market | Formula |
|---|---|
| **1 (pobeda domaćina)** | home_form*0.35 + expected_home_goals*0.25 + h2h_home_wins*0.25 + pozicija*0.15 |
| **X (remi)** | h2h_draws*0.4 + (1 - razlika forme)*0.35 + (očekivani ukupni golovi < 2)*0.25 |
| **2 (pobeda gosta)** | away_form*0.35 + expected_away_goals*0.25 + (1-h2h_home_wins)*0.25 + pozicija*0.15 |
| **BTTS Da** | btts_prob*0.5 + h2h_btts*0.3 + (oba prosečno >1 gol)*0.2 |
| **BTTS Ne** | (1-btts_prob)*0.5 + (1-h2h_btts)*0.3 + (jedan tim defanzivno jak)*0.2 |
| **Over 2.5** | (expected_total>2.5)*0.4 + h2h_over25*0.35 + forma*0.25 |
| **Under 2.5** | (expected_total<2.5)*0.4 + (1-h2h_over25)*0.35 + defanzivna_forma*0.25 |
| **Dupla šansa 1X** | max(score_1, score_X) + bonus za defanzivnu čvrstinu |
| **Dupla šansa X2** | max(score_X, score_2) + bonus |
| **Dupla šansa 12** | max(score_1, score_2) + bonus ako su oba favoriti |

#### Korak 7 – Izbor tipa
```python
best_tip = max(svi_marketi, key=lambda m: m.confidence_score)
stars = round(best_tip.confidence_score / 20)  # 0-100 → 1-5 zvezdica

# Minimalan prag za prikazivanje: confidence >= 55%
# Ako nijedan market ne dostigne 55%, prikazuje se "Nedovoljno podataka"
```

### 5.2 Za uživo utakmice

#### Minut-kontekstualna analiza
```python
if minut < 30:
    # Fokus na current_xg, possession, shots_on_target
    ...
elif 30 <= minut < 60:
    # Fokus na momentum: dangerous_attacks trend poslednjih 15 min
    ...
else:  # > 60 min
    # Fokus na rezultat + zamene + preostali golovi
    ...
```

#### Live marketi koje analiziramo:
- Sledeći gol (koji tim)
- Oba tima daju gol — ako jedan tim još nije dao gol
- Over X.5 golova (prilagođeno trenutnom rezultatu)
- Tim koji vodi + verovatnoća zadržavanja
- Korekcija preostajućih golova (Poisson distribucija na osnovu xG)

#### Live scoring formula:
```python
live_score = (
    xg_razlika * 0.30 +
    shots_on_target_razlika * 0.20 +
    possession_razlika * 0.15 +
    dangerous_attacks_razlika * 0.20 +
    corners_razlika * 0.10 +
    cards_penalty * 0.05
)
```

---

## 6. News & Injury Search

### Implementacija:
1. Za svaku predstojeću utakmicu, backend radi Scrapling-based search na:
   - `site:google.com/search?q={tim1}+{tim2}+povrede+tim+{liga}+{datum}`
   - DuckDuckGo HTML scrape: `https://html.duckduckgo.com/html/?q=...`
2. Ekstraktuje ključne reči: "injured", "suspended", "doubt", "ruled out",
   "povređen", "suspenzija", "upitan"
3. Ako se pronađe relevantna vest → prikazuje je u kartici + smanjuje confidence
   za odgovarajući market.

---

## 7. API Endpoints (FastAPI)

```
GET  /api/upcoming          → lista predstojecih utakmica sa tipovima
GET  /api/live              → lista uzivo utakmica sa tipovima
GET  /api/match/{id}        → detalji utakmice (forma, H2H, vesti, obrazlozenje)
POST /api/refresh           → ručno osvežavanje cachea
GET  /api/history           → istorija tipova
```

### Response struktura (primer):
```json
{
  "id": "flashscore_xyz123",
  "league": "Premier League",
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "kickoff": "2026-06-06T19:45:00Z",
  "status": "upcoming",
  "tip": {
    "market": "BTTS - Da",
    "confidence": 74,
    "stars": 4,
    "explanation": "Arsenal je dao gol u 4/5 poslednjih domaćih utakmica...",
    "stats_used": {
      "home_form_home": [{"opp": "Man Utd", "result": "2-1", "scored": 2, "conceded": 1}],
      "away_form_away": [...],
      "h2h": [...],
      "news": ["Kapiten upitan za nastup"]
    }
  }
}
```

---

## 8. Tehnički stack

| Sloj | Tehnologija |
|---|---|
| Frontend | Vanilla HTML5 + CSS3 (CSS Grid/Flex) + Vanilla JS (ES2022) |
| Backend | Python 3.11+ / FastAPI + Uvicorn |
| Scraping | Scrapling (StealthyFetcher + DynamicFetcher) |
| Async | asyncio + httpx |
| Caching | In-memory dict sa TTL (bez baze podataka) |
| Pokretanje | `python run.py` ili `uvicorn app.main:app` |

---

## 9. Struktura projekta

```
kladjenje/
├── backend/
│   ├── main.py              # FastAPI app + rute
│   ├── scraper/
│   │   ├── flashscore.py    # Scrapling scraper za FlashScore
│   │   ├── sofascore.py     # Scrapling scraper za SofaScore
│   │   ├── livescore.py     # Scrapling scraper za LiveScore
│   │   └── aggregator.py   # Agregacija sa sva 3 sajta
│   ├── analyzer/
│   │   ├── upcoming.py      # Algoritam za predstojeće
│   │   ├── live.py          # Algoritam za uživo
│   │   └── news.py          # News/injury search
│   └── cache.py             # In-memory cache sa TTL
├── frontend/
│   ├── index.html           # Jedna HTML stranica (SPA)
│   ├── style.css            # Flashscore-style mobilni CSS
│   └── app.js               # Vanilla JS SPA logika
├── requirements.txt
└── run.py                   # Pokretanje servera
```

---

## 10. Napomene i ograničenja

1. **Scrapling i JS-heavy sajtovi**: FlashScore i SofaScore su React/Angular aplikacije.
   Biće potreban `DynamicFetcher` (Playwright) za inicijalno učitavanje, a zatim
   targetiranje API poziva koje ove stranice rade interno (XHR/fetch) jer je to
   efikasnije od DOM scraping-a.

2. **Rate limiting**: Sva tri sajta imaju rate limiting. Implementirati:
   - Random delay između requestova (1-3 sekunde)
   - Rotacija User-Agent stringova (Scrapling to radi automatski)
   - Cache agresivno — ne scrapovati isti podatak češće nego što je potrebno

3. **Tip za kladjenje nije 100% siguran** — confidence score je statistička
   procena, ne garancija. Ovo je alat za pomoć, ne za slepo praćenje.

4. **Zakonska napomena**: Aplikacija je isključivo za ličnu upotrebu korisnika.
