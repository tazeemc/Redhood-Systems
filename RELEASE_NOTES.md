# Release Notes — RedHood Insights

---

## v1.1 — February 22, 2026

### Summary
Major feature release completing the MVP pipeline. Every run now generates a styled HTML briefing and persists all data to SQLite. Twitter/X is scraped via Nitter RSS — no API key required.

### New Features

**RedHood Reads HTML Report**
- Auto-generated editorial card report on every run (`data/redhood_reads_TIMESTAMP.html`)
- Sections: live pulse topbar, scrolling ticker tape, Playfair Display masthead, 5-metric strip, 3-column narrative grid, trade hypothesis block, raw signal links table
- Sparkline bars encode entropy risk level per narrative (green = low, gold = medium, red = high)
- `%%TOKEN%%` placeholder system keeps CSS intact inside Python string templates

**SQLite Persistence**
- All run metadata, feeds, narratives, and account data stored in `redhood.db`
- 5 tables: `twitter_accounts`, `runs`, `feeds`, `narratives`, `narrative_feeds`
- `INSERT OR IGNORE` deduplication prevents duplicate feeds across runs
- Narrative IDs use `f"narrative_{int(time.time())}_{id(self)}"` to prevent same-second collisions

**Account Management CLI (`accounts_db.py`)**
- Add, remove, toggle, and list tracked X/Twitter handles from the command line
- Per-account metadata: category, notes, active/inactive status
- Aggregator reads active handles from DB each run; falls back to Config defaults if empty
- Seeds 5 default accounts on first run: unusual_whales, FirstSquawk, AutismCapital, Mayhem4Markets, BasedBiohacker

**Database Schema (`models.py`)**
- Centralised SQLite schema with `init_schema()` — idempotent, safe to call on every startup
- Indexes on `feeds(run_id)`, `feeds(published_at)`, `narratives(run_id)`, `narratives(entropy_risk)`
- `describe()` utility prints column info for all tables

**Trading System Analysis (`run.ps1`)**
- Combined PowerShell runner: thermodynamic trading analysis + RedHood aggregator
- Calculates MA20/MA50, momentum, RSI, temperature (annualised volatility), Shannon entropy
- Position sizing: `equity × tempRatio² × entropyFactor × heatFactor × momentumFactor`
- Recommendation: `IN` (low temp + low entropy + uptrend + RSI 30-70), `OUT` (high temp or high entropy), `NEUTRAL` otherwise
- Flags: `-SkipTrading`, `-SkipRedHood`, `-Hours`, `-Symbols`, `-InitialEquity`
- Results saved to `data/TradingAnalysis_TIMESTAMP.json`

**Nitter RSS Integration**
- X/Twitter scraped via Nitter RSS — no Twitter API key required
- Multi-instance fallback: rotates through Nitter nodes if one is unavailable
- Feed items parsed with feedparser; `nitter_instance` recorded per item in DB

**.env Support**
- `ANTHROPIC_API_KEY` loaded from `.env` file via `python-dotenv`
- run.ps1 also loads `.env` before invoking Python
- `.env.example` provided as setup template

### Changes
- Removed Telegram scraping (dead code eliminated)
- Twitter account list moved from hardcoded `Config.TWITTER_ACCOUNTS` to SQLite DB
- `_save_results()` now returns `(json_path, html_path)` for DB persistence
- Output HTML renamed from `redhood_links_*.html` to `redhood_reads_*.html`
- Default time window changed to 5 minutes (`--hours 0.0833`)

### Bug Fixes
- Fixed narrative ID collision: same-second batch creation no longer causes `INSERT OR IGNORE` to drop narratives silently
- Fixed Unicode encoding errors on Windows: `PYTHONIOENCODING=utf-8` set in run.ps1

### Dependencies
```
anthropic
feedparser
python-dotenv
```

---

## v1.0 — February 15, 2026

### Summary
Initial MVP release. Feed aggregation from Substack RSS + basic Nitter scraping, Claude AI narrative extraction, entropy risk scoring, and JSON output.

### Features
- RSS feed aggregation (Substack newsletters)
- Claude AI narrative extraction — top 3 themes with entropy risk (1-10)
- Trade hypothesis generation per narrative
- JSON output to `data/redhood_insights_TIMESTAMP.json`
- Console summary with narrative titles, entropy scores, hypotheses
- `--hours` flag for configurable time window

### Known Limitations (resolved in v1.1)
- No HTML report output
- No SQLite persistence
- Twitter accounts hardcoded in `Config.TWITTER_ACCOUNTS`
- No account management CLI
- Telegram code present but non-functional (removed in v1.1)
