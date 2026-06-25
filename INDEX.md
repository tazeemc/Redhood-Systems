# RedHood Systems - Portfolio Package
## Everything You Need for PM Job Applications

**Created:** February 15, 2026
**Updated:** June 24, 2026
**Status:** MVP Complete
**Purpose:** Portfolio project demonstrating full PM skillset

---

## What's Inside

A complete, interview-ready portfolio project showcasing:

- Strategic thinking (market research, competitive analysis)
- Product management (PRD, user research, feature specs)
- Technical execution (working Python prototype with AI, SQLite, HTML reports)
- Communication (documentation, case studies)

---

## Files & What to Do With Each

### START HERE
**File:** `QUICK_START.md`
**What it is:** 15-minute guide to get up and running
**Use it for:** Immediate next steps, talking points, action plan

---

### PORTFOLIO CENTERPIECE
**File:** `CASE_STUDY.md`
**What it is:** Professional case study documenting the entire project
**Use it for:**
- Portfolio website content (copy-paste ready)
- Interview presentations
- Written assignment submissions
- LinkedIn featured projects

**Key sections:**
- Problem/Solution/Impact
- User research findings
- Technical challenges & learnings
- Results with metrics

---

### PRODUCT MANAGEMENT ARTIFACTS

#### 1. Product Requirements Document (PRD)
**File:** `PRD_RedHood_Systems.md`
**What it is:** Comprehensive PRD with user stories, acceptance criteria, roadmap
**Use it for:**
- "Show me an example of a PRD you've written"
- Demonstrating systematic product thinking
- Feature prioritization discussions

**Highlights:**
- Detailed user personas ("Active Alex")
- Technical architecture diagrams
- Success metrics & KPIs
- Development roadmap

---

#### 2. Market Research & Competitive Analysis
**File:** `Market_Research_Analysis.md`
**What it is:** Deep dive on market opportunity, competitors, GTM strategy
**Use it for:**
- "How do you size a market?"
- "What's your competitive analysis framework?"
- Business strategy discussions

**Highlights:**
- TAM/SAM/SOM calculation ($7.5B → $1.2B → $5.9M)
- Competitor analyses (Bloomberg, Koyfin, StockTwits, etc.)
- User survey data (N=50 validation)
- Pricing strategy with unit economics

---

### TECHNICAL EXECUTION

#### 3. Working Python Aggregator
**File:** `redhood_aggregator.py`
**What it is:** Production Python code — feed scraping, AI analysis, HTML report generation, SQLite persistence
**Use it for:**
- "Can you read/write code?"
- Demonstrating technical depth
- Live demos in technical interviews

**Features:**
- X/Twitter via Nitter RSS (no API key required)
- Substack RSS aggregation
- Claude AI integration (`claude-opus-4-8`) with prompt engineering
- RedHood Reads HTML report generated every run
- Full SQLite persistence (runs, feeds, narratives, narrative_feeds)

---

#### 4. Account Management CLI
**File:** `accounts_db.py`
**What it is:** CLI tool for managing tracked X/Twitter accounts in SQLite
**Use it for:** Demonstrating end-to-end system thinking (DB-backed config management)

**To run:** `python accounts_db.py --list`

---

#### 5. Database Schema
**File:** `models.py`
**What it is:** SQLite star schema with init helpers
**Tables:** twitter_accounts, runs, feeds, narratives, narrative_feeds, narrative_tickers, narrative_grades, tickers, prices, earnings, date_dim (+ Power BI views)

---

#### 6. PowerShell Runner
**File:** `run.ps1`
**What it is:** Combined runner: thermodynamic trading system analysis + RedHood aggregator (default lookback window: 45 minutes)
**To run:** `.\run.ps1` or `.\run.ps1 -Hours 1 -SkipTrading`

---

#### 7. SQLite Database
**File:** `redhood.db`
**What it is:** Live star-schema database created on first run — browse with DB Browser for SQLite
**Contains:** twitter_accounts, runs, feeds, narratives, narrative_feeds, narrative_tickers, narrative_grades, tickers, prices, earnings, date_dim, plus Power BI views

---

### INSIGHTS & SCORING

#### 8. Regime Detector
**File:** `redhood_regime_detector.py`
**What it is:** Thermodynamic regime detection (temperature/entropy) with auto signal generation; gates and sizes each signal based on the current market regime
**Use it for:** Demonstrating the physics-based framework as a pre-filter layer in the signal pipeline

---

#### 9. Ticker Extraction
**File:** `ticker_extraction.py`
**What it is:** Extracts ticker symbols and Long/Short/Hedge/Pair sides from a narrative's free-text hypothesis into the `narrative_tickers` bridge table

---

#### 10. Hypothesis Grader
**File:** `redhood_grader.py`
**What it is:** Grades a hypothesis 0–20 across four axes (Specificity / Catalyst / Risk Management / Cohesion) → an A–F letter grade, and extracts long-side tickers
**Notes:** Pure stdlib — no external dependencies

---

#### 11. Score Narratives CLI
**File:** `score_narratives.py`
**What it is:** Grades all narratives and writes results to `narrative_tickers` + `narrative_grades` (idempotent; safe to re-run)
**To run:** `python score_narratives.py` (flags: `--since`, `--dry-run`, `--with-pnl`)

---

#### 12. P&L Tracker
**File:** `redhood_pnl.py`
**What it is:** Long-only P&L ledger at $2,500 per ticker, computed from `narrative_tickers` via yfinance
**Notes:** yfinance is an optional dependency — the script exits cleanly with install instructions if it's missing
**To run:** `python redhood_pnl.py --report`

---

#### 13. Backfill
**File:** `backfill.py`
**What it is:** Backfills `narrative_tickers` from historical narratives and brings an existing `redhood.db` up to the post-audit star schema
**To run:** `python backfill.py`

---

#### 14. Demo Mode
**File:** `demo.py`
**What it is:** Demonstrates the full system with sample data — no API key required
**To run:** `python demo.py`

---

### POWER BI EXPORT

#### 15. Power BI Pipeline
**Directory:** `powerbi/`
**What it is:** Export pipeline for Power BI
**Contains:**
- `export_to_powerbi.py` — export script
- `power_query.m` — Power Query (M) source
- `dax_measures.dax` — DAX measures
- `report_layout.md` — report layout spec

---

### SUPPORTING DOCUMENTS

#### 16. README
**File:** `README.md`
**What it is:** Technical documentation & project overview (version 1.2)
**Use it for:** GitHub repository landing page, quick technical reference

---

#### 17. Release Notes
**File:** `RELEASE_NOTES.md`
**What it is:** Version history and feature changelog
**Use it for:** Demonstrating disciplined release management

---

#### 18. Power BI Integration Guide
**File:** `docs/POWERBI_INTEGRATION.md`
**What it is:** Documentation for the Power BI export and reporting integration

---

#### 19. Audit
**File:** `AUDIT_2026-05.md`
**What it is:** May 2026 schema/data audit documenting the move to the star schema and the gaps it closed

---

## How to Use This Package

### For PM Roles at Tech Companies

**Priority order:**
1. Read `CASE_STUDY.md` (understand the story)
2. Run `python redhood_aggregator.py` (see it working)
3. Open `data/redhood_reads_*.html` (see the styled report)
4. Reference GitHub repo in applications

**Resume bullet point:**
```
• Built RedHood Systems, an AI-powered market intelligence platform
  that aggregates X/Twitter and Substack feeds, extracts narratives via
  Claude AI, generates styled HTML briefings, and persists all data to
  SQLite — reducing trader research time by 83% (validated with 50 surveys)
```

---

### For PM Roles at Finance/Trading Companies

**Key talking point:**
"I built this because I experienced the pain firsthand as a trader. The 'entropy risk' framework came from physics — it's a way to quantify market uncertainty that resonates with technical traders. The trading system in run.ps1 uses thermodynamic analogies (temperature, entropy) for position sizing."

---

### For Technical PM Roles

**Interview prep:**
- Be ready to explain: architecture decisions (Nitter RSS vs Twitter API, SQLite vs JSON)
- Be ready to discuss: prompt engineering for consistent JSON output
- Be ready to answer: "How would you scale this to 10K users?"

---

## Interview Scenarios

### "Walk me through a project you've built"

**Structure:**
1. Problem (30s): "Traders spend 3+ hours daily..."
2. Solution (30s): "Built AI-powered pipeline..."
3. Process (60s): "User research → PRD → prototype → SQLite + HTML report..."
4. Results (30s): "83% time savings, 66% WTP validation..."
5. Learnings (30s): "Should have tested mobile earlier..."

---

### "How do you validate a product idea?"

**Show:** `Market_Research_Analysis.md`
- User survey methodology (N=50)
- TAM/SAM/SOM calculation
- Competitive gap analysis
- Willingness-to-pay validation

---

### "Show me something technical you've built"

**Run:** `python redhood_aggregator.py` live
**Explain:**
- Nitter RSS scraping (no API key needed)
- Prompt engineering for Claude
- SQLite persistence design
- `%%TOKEN%%` approach for CSS-safe HTML generation

---

## Pre-Interview Checklist

**72 Hours Before:**
- [ ] Re-read `CASE_STUDY.md`
- [ ] Run `python redhood_aggregator.py` (confirm it works)
- [ ] Open a generated `redhood_reads_*.html` in browser
- [ ] Practice 3-minute walkthrough

**24 Hours Before:**
- [ ] Test screen share (for remote demos)
- [ ] Prepare 3 questions about their product
- [ ] Review PRD metrics/roadmap

---

## Package Version

**v1.0:** February 15, 2026 — Initial MVP (RSS + AI + JSON output)
**v1.1:** February 22, 2026 — SQLite persistence, account management CLI, RedHood Reads HTML report, trading system integration, Nitter RSS (no Twitter API required)
**v1.2:** June 24, 2026 — Star-schema database, thermodynamic regime detection, hypothesis grading + ticker extraction, narrative scoring CLI, long-only P&L tracking, Power BI export pipeline, and the `claude-opus-4-8` model

**Install:** `pip install -r requirements.txt`

*All artifacts are production-ready and can be used immediately in job applications.*
