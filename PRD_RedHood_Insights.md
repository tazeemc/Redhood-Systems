# Product Requirements Document: RedHood Insights
## AI-Powered Market Intelligence Dashboard

**Document Owner:** Tazeem Chowdhury
**Last Updated:** February 22, 2026
**Status:** MVP Complete — v1.1
**Target Launch:** March 15, 2026 (Web Dashboard)

---

## Executive Summary

**Problem Statement:**
Retail traders and small fund analysts spend 2-4 hours daily monitoring 20+ information sources (X/Twitter, Substack newsletters, financial news) to identify market narratives and trading opportunities. This creates information overload, analysis paralysis, and missed opportunities due to signal fragmentation.

**Solution:**
RedHood Insights is an AI-powered feed aggregator that consolidates multi-source market intelligence, extracts actionable narratives using LLM analysis, scores opportunities based on "entropy risk" (market uncertainty/volatility metrics), generates styled HTML briefings, and persists all data to SQLite. The product reduces research time by 80% while improving signal quality through systematic narrative extraction.

**Success Metrics (90-day targets):**
- **Time saved:** 2.5 hours → 30 minutes per user daily (83% reduction)
- **Signal accuracy:** 65% of flagged opportunities result in profitable trades
- **User engagement:** 5+ DAU (Daily Active Users) with 70% weekly retention
- **Revenue potential:** $49/month SaaS pricing → $2,450 MRR with 50 users

---

## Strategic Context

### Market Opportunity
- **TAM (Total Addressable Market):** 15M retail traders in US (source: Robinhood, Fidelity user counts)
- **SAM (Serviceable Available Market):** 2M "serious" traders who follow 5+ sources daily
- **SOM (Serviceable Obtainable Market):** 10K traders in finance X communities (year 1)

### Competitive Landscape
| Competitor | Strengths | Weaknesses | Our Differentiation |
|------------|-----------|------------|---------------------|
| Bloomberg Terminal | Professional-grade data | $24K/year, overwhelming UI | 100x cheaper, AI-native |
| Koyfin | Good charting, free tier | No narrative extraction | LLM-powered insights |
| StockTwits | Social sentiment | Noisy, meme-heavy | Curated feeds + entropy scoring |
| Manual aggregation | Free, customizable | 3+ hours daily | Automated processing |

**Strategic Positioning:** "The AI research assistant for traders who want institutional-quality insights at consumer prices"

---

## User Research

### Primary Persona: "Active Alex"
**Demographics:**
- Age: 28-45
- Occupation: Software engineer / analyst with side trading income
- Technical literacy: High (comfortable with APIs, Python)
- Trading capital: $50K-$500K
- Time availability: 1-2 hours daily before/after work

**Pain Points:**
1. "I follow 30 accounts but miss critical signals when I'm in meetings"
2. "Too much noise — I need signal extraction, not more feeds"
3. "I can't quantify risk systematically — it's gut feel"
4. "My notes are scattered across Notion/Excel/screenshots"

**Jobs to be Done:**
- Stay updated on macro narratives without constant checking
- Identify high-conviction trades with systematic risk scoring
- Archive and backtest past signals vs. actual outcomes
- Share insights with trading group without manual summaries

### Secondary Persona: "Portfolio Pat"
**Demographics:**
- Age: 35-55
- Occupation: Financial advisor / small fund manager
- Technical literacy: Medium (uses Excel, limited Python)
- AUM: $5M-$50M
- Time availability: Morning prep (6-8 AM)

**Pain Points:**
1. "Clients ask me about viral market news I haven't seen"
2. "Need compliance-friendly way to monitor social signals"
3. "Can't justify Bloomberg Terminal cost for social intel"

---

## Product Specification

### MVP Feature Set — Shipped (v1.1)

#### 1. Feed Aggregation Engine
- **User Story:** "As a trader, I want to see all relevant posts from my curated sources in one place"
- **Shipped:**
  - X/Twitter via Nitter RSS (multi-instance fallback, no API key required)
  - Substack RSS aggregation via feedparser
  - Configurable time window (default: 5 minutes; supports hours)
  - 50 most recent items processed per run
- **Tech:** `feedparser`, `NitterScraper` class with instance rotation

#### 2. AI Narrative Extraction
- **User Story:** "As a trader, I want AI to identify the top 3 market narratives from 100+ posts"
- **Shipped:**
  - Claude claude-sonnet-4-6 integration
  - Structured JSON output with fallback parser (strips markdown fences)
  - Physics-inspired analogies (entropy, momentum, phase transitions)
  - Processing time: <60 seconds for 50 posts
- **Prompt Engineering:**
```
You are a portfolio manager with a physics PhD. Analyze these market feeds:

[FEEDS]

Task:
1. Extract top 3 narratives (e.g., "Fed dovish pivot," "Tech earnings beat")
2. Score entropy risk (1-10): Low = stable consensus, High = conflicting signals
3. Generate 1 trade hypothesis per narrative with:
   - Entry logic (why now?)
   - Risk parameters (stop loss, position size)
   - Expected catalysts (events, data releases)
4. Use physics analogies (e.g., "Market in unstable equilibrium—high entropy")

Output as JSON only.
```

#### 3. RedHood Reads HTML Report
- **User Story:** "As a trader, I want a polished briefing I can open and share"
- **Shipped:**
  - Auto-generated every run to `data/redhood_reads_TIMESTAMP.html`
  - Sections: topbar with pulse dot, scrolling ticker, hero masthead, 5-metric strip, 3-column narrative grid, trade hypothesis block, raw signal links table, footer
  - Design: Playfair Display + IBM Plex Mono + DM Serif Display; dark theme (#0A0A0A), red (#C1121F) accent
  - Sparkline bars visualize entropy risk level per narrative
  - `%%TOKEN%%` placeholder system avoids f-string/CSS brace conflicts

#### 4. SQLite Persistence
- **User Story:** "As a trader, I want all runs archived so I can track signal history"
- **Shipped:**
  - 5 tables: `twitter_accounts`, `runs`, `feeds`, `narratives`, `narrative_feeds`
  - `INSERT OR IGNORE` for feed deduplication across runs
  - Unique narrative IDs: `f"narrative_{int(time.time())}_{id(self)}"`
  - All outputs (JSON path, HTML path) recorded per run

#### 5. Account Management CLI
- **User Story:** "As a trader, I want to add/remove tracked accounts without editing code"
- **Shipped:**
  - `python accounts_db.py --list / --add / --remove / --toggle`
  - Per-account metadata: category, notes, active/inactive
  - `get_active_handles()` called each run; falls back to Config defaults if DB empty

#### 6. Trading System Analysis (run.ps1)
- **User Story:** "As a trader, I want position sizing recommendations alongside narrative signals"
- **Shipped:**
  - Thermodynamic position sizing: temperature, entropy, momentum, RSI, heat factor
  - Yahoo Finance market data (MA20, MA50, trend, recommendation: IN/OUT/NEUTRAL)
  - `-SkipTrading` and `-SkipRedHood` flags for selective execution
  - Results saved to `data/TradingAnalysis_TIMESTAMP.json`

---

### Post-MVP Features (Planned)

**Phase 2:**
- Real-time alerts (Telegram bot: "High entropy event detected")
- Live ticker data in HTML report (wire Yahoo Finance prices from run.ps1)
- Backtesting: "Show me all 'Fed dovish' signals from past runs"
- Sentiment trend tracking across runs (DB-powered)

**Phase 3:**
- React + FastAPI web dashboard
- Trade journal UI with P&L tracking
- Mobile app (React Native)
- User authentication

---

## Technical Architecture

### Current System Design (Shipped)

```
┌──────────────────────────────────────────┐
│  Data Sources                            │
│  Nitter RSS (X/Twitter) + Substack RSS   │
└────────────────┬─────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│  redhood_aggregator.py                   │
│  - NitterScraper (multi-instance)        │
│  - RSSFeedScraper                        │
│  - NarrativeExtractor (Claude API)       │
└────────┬───────────────────┬─────────────┘
         │                   │
         ▼                   ▼
┌──────────────┐   ┌─────────────────────────┐
│  redhood.db  │   │  data/                  │
│  (SQLite)    │   │  redhood_reads_*.html   │
│  5 tables    │   │  redhood_insights_*.json│
└──────────────┘   └─────────────────────────┘

┌──────────────────────────────────────────┐
│  run.ps1 (PowerShell)                    │
│  - Yahoo Finance market data             │
│  - Thermodynamic position sizing         │
│  - Calls redhood_aggregator.py           │
└──────────────────────────────────────────┘
```

### Data Models (Implemented in models.py)

**SQLite Tables:**
```sql
twitter_accounts (id, handle, added_at, active, category, notes)
runs             (id, run_at, hours_back, feeds_collected, narratives_extracted, json_path, html_path)
feeds            (id, run_id, source, author, content, published_at, url, nitter_instance)
narratives       (id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at)
narrative_feeds  (narrative_id, feed_id)  -- join table
```

---

## Success Metrics & Analytics

### North Star Metric
**Time to Actionable Insight:** Average minutes from feed update to trade decision
**Target:** <30 minutes (vs. 180 min baseline)

### Key Performance Indicators (KPIs)

**Engagement Metrics:**
- Daily Active Users (DAU)
- Session duration (target: 15-30 min)
- Narratives viewed per session (target: 3+)

**Quality Metrics:**
- Signal accuracy: % of narratives that move markets (±2% within 48h)
- User-reported trade outcomes (win rate)
- Entropy score correlation with volatility (R²)

**Business Metrics:**
- Free → Paid conversion rate (target: 10%)
- Churn rate (target: <20% monthly)
- NPS (target: 40+)

---

## Go-to-Market Strategy

### Phase 1: Portfolio & Early Validation (Month 1) — Active
- MVP complete and running locally
- Document on LinkedIn/Substack (build in public)
- 5 beta users from trading X communities
- Collect qualitative feedback → 66% WTP validated at $49/mo

### Phase 2: Product-Market Fit (Month 2-3)
- Refine based on beta feedback
- Add top 2 requested features (live ticker data, trade journal)
- Launch on Product Hunt / Hacker News
- Target: 50 free users, 10 paid ($49/mo)

### Phase 3: Growth (Month 4-6)
- Content marketing: Weekly market insights blog
- Referral program: "Invite 3 friends → 1 month free"
- B2B pivot: Pitch to small RIAs (Registered Investment Advisors)

### Pricing Strategy
**Free Tier:**
- 10 feeds max
- 1 narrative update daily
- 7-day history

**Pro Tier ($49/month):**
- Unlimited feeds + account management
- Configurable time windows
- Full HTML reports + trade journal + backtest
- Export to CSV/Notion
- Priority support

**Enterprise ($499/month):**
- White-label dashboard
- Custom sources
- Team collaboration features
- API access

---

## Development Roadmap

### Phase 1: MVP — Complete (February 2026)
- [x] Python aggregator (RSS + Nitter RSS)
- [x] Claude AI narrative extraction
- [x] Entropy risk scoring (1-10)
- [x] RedHood Reads HTML report (auto-generated each run)
- [x] SQLite persistence (5 tables)
- [x] Account management CLI (accounts_db.py)
- [x] Trading system analysis (run.ps1)
- [x] .env support for API key management
- [x] GitHub repo published

### Phase 2: Enhanced Analysis (March 2026)
- [ ] Live ticker data in HTML report
- [ ] Historical backtesting across DB runs
- [ ] Sentiment trend charts
- [ ] Alert system for high-entropy events

### Phase 3: Web Dashboard (April 2026)
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

## Open Questions & Risks

### Technical Risks
**Q:** Nitter instances can go offline — how do we ensure feed availability?
**Mitigation:** Multi-instance list with automatic fallback (already implemented); add self-hosted Nitter as ultimate fallback

**Q:** Will Claude API costs blow up with 50+ users?
**Mitigation:** Batch processing, cache narratives, use Haiku for simple tasks

### Product Risks
**Q:** Will users log trades, or is manual entry too much friction?
**Mitigation:** Auto-import from brokerage APIs (Alpaca) in v2

**Q:** Is "entropy risk" too abstract for non-technical users?
**Mitigation:** A/B test with simpler label like "Uncertainty Score"

### Market Risks
**Q:** Does Nitter RSS usage violate X ToS?
**Mitigation:** Nitter is a read-only proxy for public content; usage is within fair use for personal research tools. Monitor Nitter availability.

---

## Appendix

### User Research Interview Script
```
1. Walk me through your morning routine for market research
2. Which sources do you check first? Why?
3. Tell me about a time you missed an important signal
4. How do you currently take notes or log trades?
5. What would make you pay $49/month for a tool like this?
```

### Competitive Feature Matrix
| Feature | Bloomberg | Koyfin | StockTwits | RedHood (v1.1) |
|---------|-----------|--------|------------|----------------|
| Social feeds | No | No | Yes | Yes |
| AI analysis | No | No | No | Yes |
| HTML reports | No | No | No | Yes |
| SQLite persistence | No | No | No | Yes |
| Trade journal | Yes | No | No | Planned |
| Price | $24K/yr | Free | Free | $49/mo |

### Related Resources
- [Anthropic Claude API Docs](https://docs.anthropic.com)
- [Nitter Project](https://github.com/zedeus/nitter)
- [feedparser Docs](https://feedparser.readthedocs.io/)

---

**Document History:**
- v1.0 (Feb 15, 2026): Initial PRD
- v1.1 (Feb 22, 2026): Updated to reflect shipped MVP — SQLite, HTML reports, Nitter RSS, account CLI, trading system
