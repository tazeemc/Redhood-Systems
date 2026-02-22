# RedHood Insights
## AI-Powered Market Intelligence Dashboard

> **Portfolio Project by Tazeem Chowdhury**
> Transforming information overload into actionable trading insights using AI

![Status](https://img.shields.io/badge/status-MVP%20Complete-green)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Project Overview

**Problem:** Retail traders spend 2-4 hours daily monitoring 20+ information sources (X/Twitter, Substack) to identify market opportunities. This creates information overload and missed signals.

**Solution:** RedHood Insights aggregates multi-source feeds and uses Claude AI to extract the top 3 market narratives with entropy risk scoring (quantified uncertainty) and trade hypotheses. Every run generates a styled **RedHood Reads** HTML report and persists all data to SQLite.

**Impact:** Reduces research time by 80% (from 180 min → 30 min) while improving signal quality through systematic AI analysis.

---

## Key Features

- **AI Narrative Extraction:** Claude AI processes 50+ feeds to identify top market themes
- **Entropy Risk Scoring:** Quantifies market uncertainty (1-10 scale) using physics-inspired framework
- **Trade Hypothesis Generation:** Specific, actionable trade ideas with entry/exit logic
- **RedHood Reads HTML Report:** Styled editorial card report generated every run
- **SQLite Persistence:** All runs, feeds, and narratives stored in `redhood.db`
- **Account Management:** CLI tool to manage tracked X/Twitter accounts
- **Trading System Analysis:** Thermodynamic position-sizing model via `run.ps1`
- **Multi-Source Aggregation:** X/Twitter (via Nitter RSS, no API key required) and Substack RSS

---

## Architecture

```
┌─────────────────────────────────┐
│  Data Sources                   │  Nitter RSS (X/Twitter), Substack RSS
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Python Aggregator              │  redhood_aggregator.py
│  - Feed collection              │
│  - AI narrative extraction      │
└──────┬──────────────┬───────────┘
       │              │
       ▼              ▼
┌────────────┐  ┌─────────────────┐
│ SQLite DB  │  │ RedHood Reads   │
│ redhood.db │  │ HTML Report     │
└────────────┘  └─────────────────┘
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
pip install anthropic feedparser python-dotenv --break-system-packages

# Set up environment variables
echo ANTHROPIC_API_KEY=sk-ant-your-key-here > .env
```

### Run via PowerShell (Recommended)

```powershell
# Last 5 minutes (default), includes trading system analysis
.\run.ps1

# Last 1 hour, custom symbols
.\run.ps1 -Hours 1 -Symbols "AAPL","MSFT"

# RedHood aggregator only (skip trading analysis)
.\run.ps1 -SkipTrading

# Trading analysis only
.\run.ps1 -SkipRedHood
```

### Run Python Directly

```bash
# Default (last 5 minutes)
python redhood_aggregator.py

# Last 24 hours
python redhood_aggregator.py --hours 24
```

### Manage Tracked Accounts

```bash
# List all tracked Twitter accounts
python accounts_db.py --list

# Add an account
python accounts_db.py --add SomeHandle --category macro --notes "Description"

# Toggle active/inactive
python accounts_db.py --toggle FirstSquawk
```

### Example Output

```
📰 Fetching RSS feeds...
   ✅ Found 18 RSS items

🐦 Fetching Twitter feeds...
   📋 Active accounts from DB: @unusual_whales, @FirstSquawk, @AutismCapital...
   ✅ Found 12 tweets

📊 Total feeds collected: 30

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
├── redhood_aggregator.py      # Main aggregator + RedHood Reads HTML generator
├── accounts_db.py             # CLI: manage tracked X/Twitter accounts in SQLite
├── models.py                  # SQLite schema (5 tables) + init helpers
├── run.ps1                    # PowerShell runner: trading analysis + aggregator
├── redhood.db                 # SQLite database (runs, feeds, narratives)
├── .env                       # ANTHROPIC_API_KEY (not committed)
├── PRD_RedHood_Insights.md    # Product Requirements Document
├── Market_Research_Analysis.md# Competitive analysis & market sizing
├── CASE_STUDY.md              # Portfolio case study
├── README.md                  # This file
└── data/                      # Output directory
    ├── redhood_insights_*.json # Raw feed + narrative data
    ├── redhood_reads_*.html    # Styled RedHood Reads report
    └── TradingAnalysis_*.json  # Trading system output
```

---

## Portfolio Artifacts

This repository contains key documents demonstrating PM skills:

### 1. Product Requirements Document (PRD)
- **File:** `PRD_RedHood_Insights.md`
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
- Anthropic Claude API (claude-sonnet-4-6)
- feedparser (RSS + Nitter RSS parsing)
- python-dotenv (environment config)

**Data Storage:**
- SQLite via `redhood.db` (5 tables: twitter_accounts, runs, feeds, narratives, narrative_feeds)

**Reporting:**
- Self-contained HTML — RedHood Reads editorial card (Playfair Display + IBM Plex Mono design)

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
- [x] X/Twitter via Nitter RSS (no API key required)
- [x] Claude AI narrative extraction
- [x] Entropy risk scoring
- [x] SQLite persistence (runs, feeds, narratives)
- [x] Account management CLI (accounts_db.py)
- [x] RedHood Reads HTML report (generated each run)
- [x] Trading system analysis with thermodynamic sizing (run.ps1)
- [x] .env support for API key management

### Phase 2: Enhanced Analysis (Planned)
- [ ] Historical backtesting of signal accuracy
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
Product Manager | Business Analyst | Financial Markets Analyst

- **Background:** Engineering degree with specialization in business analysis, data analytics, and enterprise service delivery. Currently pursuing CBAP and PMP certifications.
- **Experience:**
  - Project coordination and infrastructure delivery (Nav Canada, Mitel)
  - Business requirements gathering and solution design (RBC Capital Markets, IRCC)
  - Enterprise software implementation and QA (consulting engagements)
  - Cloud infrastructure and data visualization (Azure, Power BI)
  - Financial markets and cryptocurrency research and analysis
- **LinkedIn:** [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
- **Twitter/X:** [@redhoodcapital](https://x.com/redhoodcapital)
- **Email:** [ctazeem@gmail.com](mailto:ctazeem@gmail.com)
- **Substack:** [RedHood Reads](https://substack.com/@redhoodcapital)

**Why I Built This:**

As a trader and market analyst, I was spending 3+ hours daily across Twitter, Substack, and financial feeds hunting for signals and synthesizing fragmented data. RedHood Insights automates the entire research pipeline — from feed aggregation to AI-extracted narratives to styled HTML briefings — demonstrating full-stack product thinking and technical execution.

---

## Resources & References

**AI & APIs:**
- [Anthropic Claude API](https://docs.anthropic.com/)
- [Nitter](https://nitter.net/) — Twitter RSS proxy (no API key required)
- [Yahoo Finance API](https://query1.finance.yahoo.com/) — market data for trading analysis

---

## Contact

Have questions about the project or want to discuss product opportunities?

**Email:** [ctazeem@gmail.com](mailto:ctazeem@gmail.com)
**LinkedIn:** [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
**Newsletter:** [RedHood Reads on Substack](https://substack.com/@redhoodcapital)
**Twitter/X:** [@redhoodcapital](https://x.com/redhoodcapital)

---

**Last Updated:** February 22, 2026
**Version:** 1.1 (MVP Complete)
