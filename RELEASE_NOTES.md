# Release Notes — RedHood Systems

---

## v1.4.1 — October 26, 2026

### Changes
- **Telegram: added [@tradehaven](https://t.me/tradehaven)** to `Config.TELEGRAM_CHANNELS` alongside
  @marketfeed. It is a macro / geopolitics / rates-FX headline wire that also posts a daily KEY DATA
  calendar; it is scraped through the same `t.me/s/` preview with `?before=` paging, so every run from
  here on feeds it into narrative extraction, the feed anchors and the report.
- **Telegram: paging now reaches the requested window.** `TelegramScraper.fetch` pages back until the
  window's cutoff, pausing 0.3 s between page requests; `TELEGRAM_MAX_PAGES` goes from 5 to 60 and is
  only a safety ceiling. Previously the 5-page cap left the high-volume @marketfeed covering ~5 h of a
  48 h window (100 posts). The run log now prints each channel's coverage (posts, pages, oldest post)
  and warns when a channel stops short of the window.
- **$NVDA** added to the watchlist exports (`watchlists/`, synced into `redhood.db`), the ticker tape and
  the `run.ps1` fallback symbols, so it appears in the Quantitative Signal Analysis cards and the trading scan.
- Ticker tape change is now measured against the prior daily close (it was a permanent +0.00%).
- **Report template aligned with `main`.** The RedHood Reads render (SIGINT signal cards, card history
  page, ticker tape) and `card_history.py` are now the same as on `origin/main`; the local-only
  Cloudscape-token template is retired. Narrative cards keep the v1.4 continuation tag and the regime
  panel names the v2 detector.
- **Tests can no longer publish.** `tests/conftest.py` blanks `GITHUB_TOKEN` and sets `REDHOOD_NO_PUBLISH`,
  which the aggregator honours; the full-pipeline test had been pushing fixture reports to GitHub Pages
  whenever `.env` carried a token.

---

## v1.4 — October 23, 2026

### Summary
"Closing the loop" release, driven by the audit in the paper
*Interpreting Black Swans & Boltzmann with a Thermodynamic Bias* (v3, `paper/`).
The regime detector is rebuilt so that CRISIS/TRANSITION are reachable and
thresholds are calibrated; the P&L loop that was never run now runs after
every aggregation; every run persists its regime state; and a paginated
historical timeline feeds the extraction prompt with what the system has
already said and how it worked out.

### New Features

**Regime detector v2 (`redhood_regime_detector.py`)**
- Entropy on **fixed levels** in units of `T_base` (occupation entropy, Miller–Madow corrected,
  `eta = S / ln k`) with an equilibrium curve `S_eq(T / T_base)`; v1's range-adaptive bins made
  entropy *fall* in crashes and its threshold (2.5 nats) exceeded the 10-bin ceiling (ln 10 = 2.30),
  so CRISIS and TRANSITION were unreachable.
- Departure statistic `D = KL(observed || Laplace at current T)` with bin-integrated reference and
  the correct scale `b = sigma / sqrt(2)`; the alert is the Monte-Carlo 95th percentile of the null
  (cached in `data/regime_calibration.json`), not the fixed 0.25 that fired on every v1 report.
- Taxonomy: CRISIS = hot and occupation spread beyond the base band; CHOPPY = hot, within band;
  TRANSITION = cool with shape drift; TRENDING = cool equilibrium. CRISIS zeroes the multiplier.
- Heat is an input from the ledger (`redhood_pnl.current_heat`) — "heat budget 100%" was a constant in v1.
- `RegimeState.to_dict()`, v1 keywords accepted with deprecation warnings, percentage `base_temp` auto-corrected.

**History layer (`redhood_timeline.py`, new)**
- Paginated timeline of runs → regime → narratives → tickers → realised returns (`get_page`, CLI `--page/--size`).
- Continuation flags: `narratives.prior_mentions` / `continuation_of` (title-token Jaccard, 30-day window).
- `recent_context()` renders a HISTORICAL CONTEXT block (recent narratives, crowded tickers, realised lesson)
  that the extraction prompt now reads; the model returns `continues_prior` per narrative.
- `docs/timeline.html`: self-contained page with client-side pagination and filters (regime, ticker, entropy).

**P&L loop closed (`redhood_pnl.py`, `score_narratives.py`)**
- `--import-csv` loads daily closes without yfinance; `compute_forward_returns()` writes realised
  5/20/60-day and to-date returns vs SPY into the new `narrative_returns` table; `current_heat()`.
- Entry rule: runs after the US close enter at the **next** session's close (no look-ahead).
- `score_narratives.py` no longer deletes the star-schema ticker rows when re-scoring (v1 wiped them).
- The aggregator runs scoring, a yfinance tail top-up (if installed; `REDHOOD_NO_PRICE_REFRESH=1` to skip),
  forward returns and the timeline page after every run (`_post_run`).

**Schema (`models.py`)**
- New tables `regime_history`, `narrative_returns`; new columns `narratives.prior_mentions`, `continuation_of`;
  views `fact_regime_history`, `fact_narrative_returns`; Power BI exports for both.

**Report**
- Regime panel shows equilibrium/crisis entropy bands, the calibrated D threshold, measured heat, and a
  strip of the previous runs' regimes; narrative cards carry a "seen N× in the last 30 days" tag.

### Changes
- `run.ps1`: `BaseTemp` default is now `0.15` (decimal). The old `25.0` was a percentage against a decimal
  temperature and pinned every position at the 2% cap; a guard now divides any value > 1.5 by 100.
  New `-Timeline` switch prints page 1 after a run.
- `redhood_grader.py`: more non-investable tokens excluded (CDS, DOD, DXY, EV, OAT, PCE, TIPS, TO, TTF, XAU, …).
- `Config.EQUITY` (env `REDHOOD_EQUITY`, default 100000), `Config.BASE_TEMP`, `HISTORY_RUNS`.
- CI installs numpy/pandas; 20 new tests (detector, history layer, end-to-end pipeline without network).

### Known limitations
- Regime history starts with this release (earlier runs have no `regime_history` row; the archived
  HTML reports still show their v1 panels).
- The redundancy lesson in the prompt is descriptive of this system's ledger, not a tested trading rule;
  see the paper's forward-test protocol.

---

## v1.2 — June 24, 2026

### Summary
Analytics release adding hypothesis grading, long-only P&L tracking, and a star-schema data model with a full Power BI export pipeline. The Claude model is upgraded to `claude-opus-4-8`.

### New Features

**Hypothesis Grading (`redhood_grader.py`, `score_narratives.py`)**
- Scores each narrative 0–20 across four dimensions: Specificity, Catalyst, Risk Management, Cohesion
- Maps the score to an A–F letter grade
- Extracts long-side tickers from narratives
- Writes results to a new `narrative_grades` table

**Long-Only P&L Tracking (`redhood_pnl.py`)**
- $2,500-per-ticker ledger over extracted tickers
- Prices pulled via yfinance (optional dependency)

**Star-Schema Data Model (`ticker_extraction.py`, `backfill.py`, `models.py`)**
- Ticker/side extraction into a `narrative_tickers` bridge table
- `models.py` reconciled into a star schema: `narrative_tickers`, `narrative_grades`, `tickers`, `prices`, `earnings`, `date_dim`
- Power BI compatibility views

**Thermodynamic Regime Detection (`redhood_regime_detector.py`)**
- Detects market regime and auto-generates signals

**Power BI Export Pipeline (`powerbi/`)**
- `export_to_powerbi.py`, `power_query.m`, `dax_measures.dax`, `report_layout.md`
- Integration guide at `docs/POWERBI_INTEGRATION.md`

### Changes
- Bumped the Claude model to `claude-opus-4-8` (from `claude-sonnet-4-6`)
- `run.ps1` default feed window changed from 5 to 45 minutes

### Dependencies
```
yfinance (optional)
```

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
