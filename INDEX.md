# RedHood Insights - Portfolio Package
## Everything You Need for PM Job Applications

**Created:** February 15, 2026
**Updated:** February 22, 2026
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
**File:** `PRD_RedHood_Insights.md`
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
- Claude AI integration with prompt engineering
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
**What it is:** SQLite schema with 5 tables and init helpers
**Tables:** twitter_accounts, runs, feeds, narratives, narrative_feeds

---

#### 6. PowerShell Runner
**File:** `run.ps1`
**What it is:** Combined runner: thermodynamic trading system analysis + RedHood aggregator
**To run:** `.\run.ps1` or `.\run.ps1 -Hours 1 -SkipTrading`

---

#### 7. SQLite Database
**File:** `redhood.db`
**What it is:** Live database created on first run — browse with DB Browser for SQLite
**Contains:** All runs, feeds, narratives, and tracked accounts

---

### SUPPORTING DOCUMENTS

#### 8. README
**File:** `README.md`
**What it is:** Technical documentation & project overview
**Use it for:** GitHub repository landing page, quick technical reference

---

#### 9. Release Notes
**File:** `RELEASE_NOTES.md`
**What it is:** Version history and feature changelog
**Use it for:** Demonstrating disciplined release management

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
• Built RedHood Insights, an AI-powered market intelligence platform
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

*All artifacts are production-ready and can be used immediately in job applications.*
