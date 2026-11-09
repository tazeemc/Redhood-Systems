# RedHood Systems
## AI-Powered Market Intelligence Dashboard

> **Portfolio Project by Tazeem Chowdhury**
> Transforming information overload into actionable trading insights using AI

![Status](https://img.shields.io/badge/status-MVP%20Complete-green)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![CI](https://github.com/tazeemc/Redhood-Systems/actions/workflows/ci.yml/badge.svg)](https://github.com/tazeemc/Redhood-Systems/actions/workflows/ci.yml)

---

## Project Overview

**Problem:** Retail traders spend 2-4 hours daily monitoring 20+ information sources (X/Twitter, Substack) to identify market opportunities. This creates information overload and missed signals.

**Solution:** RedHood Systems aggregates multi-source feeds and uses Claude AI to extract the top 3 market narratives with entropy risk scoring (quantified uncertainty) and trade hypotheses. Every run generates a styled **RedHood Reads** HTML report and persists all data to SQLite.

**Impact:** Reduces research time by 80% (from 180 min → 30 min) while improving signal quality through systematic AI analysis.

---

## Key Features

- **AI Narrative Extraction:** Claude AI (Opus 4.8) processes 50+ feeds to identify top market themes
- **Entropy Risk Scoring:** Quantifies market uncertainty (1-10 scale) using physics-inspired framework
- **Thermodynamic Regime Detection (v2):** Temperature, fixed-level occupation entropy and a calibrated Boltzmann-departure statistic classify TRENDING / CHOPPY / CRISIS / TRANSITION; every run's state is persisted to `regime_history` (`redhood_regime_detector.py`)
- **Historical Timeline:** Paginated memory of past runs, regimes, narratives and realised returns; feeds a HISTORICAL CONTEXT block into narrative extraction and renders `docs/timeline.html` (`redhood_timeline.py`)
- **Trade Hypothesis Generation:** Specific, actionable trade ideas with entry/exit logic
- **Hypothesis Grading:** 0–20 quality grade (Specificity / Catalyst / Risk Management / Cohesion) + A–F letter, with long-side ticker extraction (`redhood_grader.py`, `score_narratives.py`)
- **Long-Only P&L Tracking (loop closed):** $2,500-per-ticker ledger plus realised 5/20/60-day returns vs SPY per narrative (`narrative_returns`), portfolio heat from the open book, CSV price import when yfinance is unavailable (`redhood_pnl.py`)
- **Star-Schema Persistence:** Runs, feeds, narratives, tickers, grades, prices, earnings + Power BI views in `redhood.db`
- **Power BI Export:** SQLite → Power BI pipeline with Power Query (M), DAX measures, and report layout (`powerbi/`)
- **RedHood Reads HTML Report:** Styled editorial card report generated every run
- **RedHood Terminal:** Keyboard-driven multi-panel terminal over the whole database — candlestick charts with volume and overlays, a sortable monitor, the narrative blotter, regime and realised-alpha analytics, and ▲ markers on the price showing where the system actually had a thesis and what it earned (`redhood_terminal.py`, `docs/terminal.html`)
- **X/Twitter Archive:** the closed X record (2026-02 .. 2026-08) preserved in `twitter_archive` after Nitter's shutdown (`archive_twitter.py`)
- **Trading System Analysis:** Thermodynamic position-sizing model via `run.ps1`
- **Multi-Source Aggregation:** Substack RSS and public Telegram channels (via the `t.me/s/` web preview, no bot token required, paged back via `?before=` for high-volume channels — currently [@marketfeed](https://t.me/marketfeed), [@tradehaven](https://t.me/tradehaven), [@financefeeds](https://t.me/financefeeds), [@WatcherGuru](https://t.me/WatcherGuru), [@walterbloomberg](https://t.me/walterbloomberg), [@financialjuice](https://t.me/financialjuice) and [@ahboyashreads](https://t.me/ahboyashreads)). X/Twitter was dropped on 2026-11-01 when Nitter shut down; [@walterbloomberg](https://t.me/walterbloomberg) and [@financialjuice](https://t.me/financialjuice) are the Telegram mirrors of the X accounts that carried the most signal

---

## Architecture

```
┌─────────────────────────────────┐
│  Data Sources                   │  Substack RSS,
└─────────────┬───────────────────┘  Telegram (t.me/s/ preview), Yahoo Finance
              │
              ▼
┌─────────────────────────────────┐
│  Python Aggregator              │  redhood_aggregator.py
│  - Feed collection              │  + redhood_regime_detector.py (regime)
│  - AI narrative extraction      │  + ticker_extraction.py (tickers/sides)
└──────┬──────────────┬───────────┘
       │              │
       ▼              ▼
┌────────────┐  ┌─────────────────┐
│ SQLite DB  │  │ RedHood Reads   │
│ redhood.db │  │ HTML Report     │
└─────┬──────┘  └─────────────────┘
      │
      ├──▶ score_narratives.py ──▶ grades + long tickers (redhood_grader.py)   ┐ run automatically
      ├──▶ redhood_pnl.py ───────▶ realised returns + heat (narrative_returns) │ after every
      ├──▶ redhood_timeline.py ──▶ regime_history / prompt context / timeline  ┘ aggregation
      └──▶ powerbi/export_to_powerbi.py ──▶ Power BI (Power Query + DAX)
```

---

## Quick Start

### Prerequisites
- Python 3.9+
- Anthropic API key ([Get one here](https://console.anthropic.com/))
- PowerShell 5+ (Windows, for `run.ps1`)

### Installation

```bash
# Clone the repository
git clone https://github.com/tazeemc/Redhood-Systems.git
cd Redhood-Systems

# Install dependencies
pip install -r requirements.txt
# (yfinance is optional — only needed for redhood_pnl.py / scoring with --with-pnl)

# Set up environment variables
echo ANTHROPIC_API_KEY=sk-ant-your-key-here > .env
```

`redhood.db` is local state, not versioned: the first run applies the schema and
builds it up from there, so a fresh clone starts with an empty history. Keep your
own copy out of harm's way — the paper's analysis scripts under `paper/analysis/`
read it, and `backfill.py` brings an older database up to the current schema.

### Run via PowerShell (Recommended)

```powershell
# Last 45 minutes (default), includes trading system analysis
.\run.ps1

# Last 5 hours, custom symbols
.\run.ps1 -Hours 5 -Symbols "AAPL","MSFT"

# Last 24 hours (full day)
.\run.ps1 -Hours 24

# RedHood aggregator only (skip trading analysis)
.\run.ps1 -SkipTrading

# Trading analysis only
.\run.ps1 -SkipRedHood
```

### Run Python Directly

```bash
# Default (last ~10 minutes)
python redhood_aggregator.py

# Last 24 hours
python redhood_aggregator.py --hours 24
```

### Score, Grade & Track P&L (runs automatically after each aggregation)

```bash
# Grade every narrative + extract long-side tickers (idempotent)
python score_narratives.py

# Score recent narratives and (re)compute realised forward returns vs SPY
python score_narratives.py --since 2026-03-01 --forward

# Long-only P&L leaderboard ($2,500/ticker; needs yfinance) ...
python redhood_pnl.py --report
# ... or close the loop from a CSV of daily closes when yfinance is unavailable
python redhood_pnl.py --import-csv data/prices_20261023.csv --forward --heat
```

### Historical Timeline

```bash
python redhood_timeline.py --page 1 --size 10   # newest runs first: regime, narratives, realised returns
python redhood_timeline.py --context             # the HISTORICAL CONTEXT block the LLM reads
python redhood_timeline.py --html                # docs/timeline.html (paginated, filterable)
python redhood_timeline.py --flag                # recompute "seen N× before" flags
```

### The RedHood Terminal

A dense, keyboard-driven terminal over everything in `redhood.db` — price,
narratives, regime and realised alpha on one surface. `run.ps1` rebuilds it
after every run; `-SkipTerminal` opts out.

```bash
python redhood_terminal.py --html            # docs/terminal.html (self-contained, ~3.9 MB)
python redhood_terminal.py --html --open     # ...and open it
python redhood_terminal.py --serve           # live mode on :8787, with polled quotes
python redhood_terminal.py --json out.json   # just the data bundle
python redhood_terminal.py --stats           # what's in the bundle
```

**Panels.** A monitor (watchlist / narrative universe / all symbols, sortable,
with sparklines); a candlestick chart with volume, SMA 20/50/200, Bollinger
bands, log scale and a relative-to-SPY mode; the narrative blotter, filterable
by grade and entropy band; a dossier panel showing either the full narrative
(hypothesis, bear case, catalysts, disconfirming signals, realised return vs
SPY) or the symbol's own narrative history; and six lower tabs — Returns,
Regime, Alpha, Tape, Notes, Runs.

**Narrative markers.** The ▲ markers under the price are the runs where the
system actually had a thesis on that name, coloured by letter grade. Hover for
the thesis and its excess return; click to open it. This is the thing a generic
charting tool cannot show you: where the pipeline spoke, and what happened next.

**Commands.** `/` focuses the command line. Type a symbol (`NVDA`), a symbol
plus a function (`NVDA GP`, `SPY DES`), a function alone (`REG`, `ALPH`,
`TAPE`, `NOTE`, `RUNS`, `TOP`), or free text to search narratives. `?` lists
every key; `F1`–`F4` move between panels, `Z` full-screens one, `t` toggles
light/dark.

**Static vs live.** The static page bakes the bundle in, needs no server and no
CDN, and publishes to GitHub Pages with the rest of `docs/`. `--serve` hands the
identical page the same bundle over HTTP plus `/api/quotes` for polled quotes —
one data adapter, so the UI is the same either way.

### Candlestick data

`redhood_pnl.py` caches closes only. To draw candles, fill the OHLCV columns:

```bash
python backfill_ohlcv.py                  # 2y of daily bars for every known symbol
python backfill_ohlcv.py --missing-only   # only symbols that have no bars yet
python backfill_ohlcv.py --symbols SPY NVDA --period 5y
```

`run.ps1 -Candles` does this before rebuilding the terminal. Symbols without
OHLC still chart — they fall back to a line.

### Run Tests & Static Analysis

```bash
pip install pytest ruff

# Unit tests (141 tests — extraction, grading, Telegram scraper, DB schema, terminal bundle)
pytest

# Static analysis (also runs in CI on every push/PR)
ruff check .
```

### The X/Twitter Archive

X was read through Nitter RSS, which needed no API key but relied on X's guest
access tokens. Once those were withdrawn every public instance shut down
(`nitter.net` answers 410 Gone, `nitter.privacydev.net` resolves to a null
route, `nitter.poast.org` lost its DNS record), and the scraper was removed on
2026-11-01. The last tweet collected was 2026-08-21.

The 2,892 tweets gathered over the X era are preserved in `twitter_archive`:

```bash
# Re-file the archive (idempotent) and print a summary
python archive_twitter.py

# Summary only
python archive_twitter.py --summary
```

The source rows deliberately stay in `feeds`. 1,265 `narrative_feeds` links
reference them `ON DELETE CASCADE`, so deleting them would silently destroy the
sourcing of every past narrative that cited a tweet. `twitter_accounts` keeps
the tracked-handle roster, all rows marked inactive.

### Example Output

```
📰 Fetching RSS feeds...
   ✅ Found 18 RSS items

📢 Fetching Telegram channels...
   📋 Channels: @marketfeed, @tradehaven, @financefeeds, @WatcherGuru, @walterbloomberg...
   ✅ Found 73 Telegram messages

📊 Total feeds collected: 39

🧠 AI Analysis Phase...
✅ Extracted 3 narratives

============================================================
📋 DAILY BRIEF - TOP NARRATIVES
============================================================

[1] Fed Signals Dovish Pivot
    Entropy Risk: 🟢 LOW (3/10)
    💡 Hypothesis: Long QQQ calls, 2-week timeframe
    📝 Rationale: Multiple Fed speakers indicate willingness to pause
        rate hikes if inflation continues cooling.
    📅 Catalysts: CPI data, FOMC minutes

💾 Results saved to: data/redhood_insights_20260222_083045.json
📰 Report saved to:  data/redhood_reads_20260222_083045.html
🗄️  DB: run #5 saved — 30 feeds, 3 narratives
```

---

## Project Structure

```
Redhood-Systems/
├── redhood_aggregator.py       # Main aggregator + RedHood Reads HTML generator
├── redhood_regime_detector.py  # Thermodynamic regime detection v2 (calibrated; CRISIS reachable)
├── redhood_timeline.py         # Paginated history: prompt context, continuation flags, docs/timeline.html
├── redhood_terminal.py         # The RedHood Terminal: data bundle + docs/terminal.html + --serve live mode
├── backfill_ohlcv.py           # Fill open/high/low/volume on `prices` so the terminal can draw candles
├── assets/terminal/            # Terminal front end (inlined into the single-file page at build time)
│   ├── index.html              #   panel skeleton
│   ├── terminal.css            #   theme + layout (dark/light, validated chart palette)
│   ├── util.js                 #   formatting, static/live data adapter, indicator maths
│   ├── chart.js                #   candlestick engine + the lower panels' small multiples
│   ├── panels.js               #   monitor, blotter, dossier, the six lower tabs
│   └── app.js                  #   state, command language, keyboard model
├── ticker_extraction.py        # Extract tickers + Long/Short/Hedge sides from hypotheses
├── redhood_grader.py           # Hypothesis grader (0–20 / A–F) + long-ticker extraction
├── score_narratives.py         # CLI: grade narratives → narrative_tickers + narrative_grades
├── redhood_pnl.py              # CLI: long-only P&L ledger via yfinance
├── backfill.py                 # Backfill narrative_tickers from historical narratives
├── accounts_db.py             # CLI: the retired X/Twitter account roster
├── archive_twitter.py          # CLI: file the closed X record into twitter_archive
├── models.py                  # SQLite star schema (tables + Power BI views) + init helpers
├── demo.py                    # Demo mode with sample data (no API key required)
├── run.ps1                    # PowerShell runner: trading analysis + aggregator
├── redhood.db                 # SQLite database (star schema) — local, not versioned
├── requirements.txt           # Python dependencies
├── pyproject.toml             # pytest + ruff configuration
├── tests/                     # Unit test suite (pytest, network-free)
├── .github/workflows/ci.yml   # CI: ruff static analysis + pytest matrix
├── .env                       # ANTHROPIC_API_KEY (not committed)
├── powerbi/                   # Power BI export pipeline
│   ├── export_to_powerbi.py   #   SQLite → Power BI dataset
│   ├── power_query.m          #   Power Query (M) source
│   ├── dax_measures.dax       #   DAX measures
│   └── report_layout.md       #   Report layout spec
├── docs/                      # Published pages: latest.html, terminal.html, timeline.html, cards.html
├── PRD_RedHood_Systems.md    # Product Requirements Document
├── Market_Research_Analysis.md# Competitive analysis & market sizing
├── CASE_STUDY.md              # Portfolio case study
├── README.md                  # This file
└── data/                      # Output directory (gitignored)
    ├── redhood_insights_*.json # Raw feed + narrative data
    ├── redhood_reads_*.html    # Styled RedHood Reads report
    └── TradingAnalysis_*.json  # Trading system output
```

---

## Portfolio Artifacts

This repository contains key documents demonstrating PM skills:

### 1. Product Requirements Document (PRD)
- **File:** `PRD_RedHood_Systems.md`
- **Contents:** Problem statement, user personas, feature specs, success metrics, roadmap
- **Demonstrates:** Strategic thinking, user research, technical specification

### 2. Market Research & Competitive Analysis
- **File:** `Market_Research_Analysis.md`
- **Contents:** TAM/SAM/SOM analysis, competitive landscape, pricing strategy, GTM plan
- **Demonstrates:** Business acumen, market sizing, competitive positioning

### 3. Working Prototype
- **File:** `redhood_aggregator.py`
- **Contents:** Production Python code — feed scraping, Claude AI integration, HTML report generation, SQLite persistence
- **Demonstrates:** Technical execution, coding ability, systems thinking

---

## Technical Stack

**Backend:**
- Python 3.9+
- Anthropic Claude API (claude-opus-4-8)
- feedparser (RSS parsing)
- urllib + regex (public Telegram channel scraping via `t.me/s/`)
- python-dotenv (environment config)
- yfinance (optional — long-only P&L tracking)

**Data Storage:**
- SQLite via `redhood.db` — star schema (twitter_accounts, runs, feeds, narratives, narrative_feeds, narrative_tickers, narrative_grades, tickers, prices, earnings, date_dim) plus Power BI compatibility views (dim_runs, fact_narratives, fact_narratives_ticker, fact_prices, fact_narrative_grades, …)

**Reporting & BI:**
- Self-contained HTML — RedHood Reads editorial card (Playfair Display + IBM Plex Mono design)
- Power BI export pipeline — Power Query (M) + DAX measures (`powerbi/`)

**Trading Analysis (PowerShell):**
- Yahoo Finance API (market data)
- Thermodynamic position-sizing: temperature, entropy, momentum, RSI

**Deployment:**
- Local execution (MVP)
- AWS Lambda + CloudWatch (planned)
- React dashboard (planned)

---

## Roadmap

### Phase 1: MVP (Complete)
- [x] RSS feed aggregation (Substack)
- [x] X/Twitter via Nitter RSS — retired 2026-11-01, archived in `twitter_archive`
- [x] Claude AI narrative extraction
- [x] Entropy risk scoring
- [x] SQLite persistence (runs, feeds, narratives)
- [x] Account management CLI (accounts_db.py) — roster retired with the X source
- [x] RedHood Reads HTML report (generated each run)
- [x] Trading system analysis with thermodynamic sizing (run.ps1)
- [x] .env support for API key management

### Phase 2: Enhanced Analysis
- [x] Thermodynamic regime detection + auto signal generation
- [x] Ticker/side extraction into a star-schema bridge table
- [x] Hypothesis grading (0–20 / A–F) + narrative scoring CLI
- [x] Long-only P&L tracking ($2,500/ticker, via yfinance)
- [x] Power BI export pipeline (Power Query + DAX)
- [x] Realised-return tracking of every long-side narrative vs SPY (`narrative_returns`)
- [x] Regime history persisted per run; CRISIS reachable; thresholds calibrated
- [x] Paginated historical timeline feeding narrative extraction
- [ ] Pre-registered forward test of the redundancy filter (from 1 Nov 2026)
- [ ] Sentiment trend tracking across runs
- [ ] Live ticker data in HTML report

### Phase 3: Web Dashboard (Planned)
- [ ] React frontend
- [ ] FastAPI backend
- [ ] User authentication
- [ ] Trade journal UI
- [ ] Deployed demo (Vercel)

### Phase 4: Scale (Post-MVP)
- [ ] Real-time alerts (Telegram bot)
- [ ] Mobile app (React Native)
- [ ] B2B features (team collaboration)
- [ ] API access for developers

---

## Success Metrics

**Product Metrics:**
- Time saved: 2.5 hours → 30 min (83% reduction)
- Signal accuracy: 65% of flagged narratives = profitable trades
- User engagement: 5+ DAU with 70% weekly retention

**Business Metrics:**
- Target: 50 users (10 paid) in Month 1
- ARPU: $49/month
- Churn: <20% monthly
- LTV:CAC ratio: >3:1

---

## Contributing

This is a portfolio project, but feedback is welcome!

**How to provide feedback:**
1. Open an issue with suggestions
2. Fork and submit a PR with improvements
3. Reach out directly: [ctazeem@gmail.com](mailto:ctazeem@gmail.com)

---

## License

MIT License - feel free to use this code for your own projects.

---

## About the Creator

**Tazeem Chowdhury**
Scrum Master | Product Manager | Markets Analyst

- **Background:** Engineering degree with specialization in business analysis, data analytics, and enterprise service delivery. Currently pursuing CBAP and PMP certifications.
- **Experience:**
  - Project coordination and infrastructure delivery (Nav Canada, Mitel)
  - Business requirements gathering and solution design (RBC Capital Markets, IRCC)
  - Enterprise software implementation and QA (consulting engagements)
  - Cloud infrastructure and data visualization (Azure, Power BI)
  - Financial markets and cryptocurrency research and analysis
- **LinkedIn:** [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
- **Twitter/X:** [@redhoodcapital](https://x.com/redhoodcapital)
- **Telegram:** [@redhoodtrades](https://t.me/redhoodtrades)
- **Email:** [ctazeem@gmail.com](mailto:ctazeem@gmail.com)
- **Substack:** [RedHood Reads](https://substack.com/@redhoodcapital)

**Why I Built This:**

As a trader and market analyst, I was spending 3+ hours daily across Twitter, Substack, and financial feeds hunting for signals and synthesizing fragmented data. RedHood Systems automates the entire research pipeline — from feed aggregation to AI-extracted narratives to styled HTML briefings — demonstrating full-stack product thinking and technical execution.

---

## Resources & References

**AI & APIs:**
- [Anthropic Claude API](https://docs.anthropic.com/)
- [Nitter](https://nitter.net/) — Twitter RSS proxy, used until its 2026 shutdown
- [Telegram web preview](https://t.me/s/marketfeed) — public channel scraping (no bot token required; also [@tradehaven](https://t.me/s/tradehaven), [@financefeeds](https://t.me/s/financefeeds), [@WatcherGuru](https://t.me/s/WatcherGuru) and [@ahboyashreads](https://t.me/s/ahboyashreads))
- [Yahoo Finance API](https://query1.finance.yahoo.com/) — market data for trading analysis (incl. `$BLSH` / Bullish)

---

## Contact

Have questions about the project or want to discuss product opportunities?

**Email:** [ctazeem@gmail.com](mailto:ctazeem@gmail.com)
**LinkedIn:** [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
**Newsletter:** [RedHood Reads on Substack](https://substack.com/@redhoodcapital)
**Twitter/X:** [@redhoodcapital](https://x.com/redhoodcapital)
**Telegram:** [@redhoodtrades](https://t.me/redhoodtrades)

---

**Last Updated:** October 23, 2026
**Version:** 1.4 (regime detector v2, closed P&L loop, historical timeline — see `paper/` for the audit)
