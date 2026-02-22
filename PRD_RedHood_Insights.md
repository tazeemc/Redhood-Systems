# Product Requirements Document: RedHood Insights
## AI-Powered Market Intelligence Dashboard

**Document Owner:** Tazeem Chowdhury  
**Last Updated:** February 15, 2026  
**Status:** Week 1 - Foundation Phase  
**Target Launch:** March 15, 2026 (MVP)

---

## 📊 Executive Summary

**Problem Statement:**  
Retail traders and small fund analysts spend 2-4 hours daily monitoring 20+ information sources (X/Twitter, Telegram channels, Substack newsletters, financial news) to identify market narratives and trading opportunities. This creates information overload, analysis paralysis, and missed opportunities due to signal fragmentation.

**Solution:**  
RedHood Insights is an AI-powered feed aggregator that consolidates multi-source market intelligence, extracts actionable narratives using LLM analysis, and scores opportunities based on "entropy risk" (market uncertainty/volatility metrics). The product reduces research time by 80% while improving signal quality through systematic narrative extraction.

**Success Metrics (90-day targets):**
- **Time saved:** 2.5 hours → 30 minutes per user daily (83% reduction)
- **Signal accuracy:** 65% of flagged opportunities result in profitable trades
- **User engagement:** 5+ DAU (Daily Active Users) with 70% weekly retention
- **Revenue potential:** $49/month SaaS pricing → $2,450 MRR with 50 users

---

## 🎯 Strategic Context

### Market Opportunity
- **TAM (Total Addressable Market):** 15M retail traders in US (source: Robinhood, Fidelity user counts)
- **SAM (Serviceable Available Market):** 2M "serious" traders who follow 5+ sources daily
- **SOM (Serviceable Obtainable Market):** 10K traders in finance X/Telegram communities (year 1)

### Competitive Landscape
| Competitor | Strengths | Weaknesses | Our Differentiation |
|------------|-----------|------------|---------------------|
| Bloomberg Terminal | Professional-grade data | $24K/year, overwhelming UI | 100x cheaper, AI-native |
| Koyfin | Good charting, free tier | No narrative extraction | LLM-powered insights |
| StockTwits | Social sentiment | Noisy, meme-heavy | Curated feeds + entropy scoring |
| Manual aggregation | Free, customizable | 3+ hours daily | Automated processing |

**Strategic Positioning:** "The AI research assistant for traders who want institutional-quality insights at consumer prices"

---

## 👥 User Research

### Primary Persona: "Active Alex"
**Demographics:**
- Age: 28-45
- Occupation: Software engineer / analyst with side trading income
- Technical literacy: High (comfortable with APIs, Python)
- Trading capital: $50K-$500K
- Time availability: 1-2 hours daily before/after work

**Pain Points:**
1. "I follow 30 accounts but miss critical signals when I'm in meetings"
2. "Too much noise - I need signal extraction, not more feeds"
3. "I can't quantify risk systematically - it's gut feel"
4. "My notes are scattered across Notion/Excel/screenshots"

**Jobs to be Done:**
- ✅ Stay updated on macro narratives without constant checking
- ✅ Identify high-conviction trades with systematic risk scoring
- ✅ Archive and backtest past signals vs. actual outcomes
- ✅ Share insights with trading group without manual summaries

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

## 🏗️ Product Specification

### MVP Feature Set (Week 1-4)

#### **Core Features (Must-Have)**

**1. Feed Aggregation Engine**
- **User Story:** "As a trader, I want to see all relevant posts from my curated sources in one place, so I don't have to check 5 apps"
- **Acceptance Criteria:**
  - [ ] Supports X/Twitter, Telegram, Substack RSS
  - [ ] Updates every 15 minutes (or on-demand refresh)
  - [ ] Displays 50 most recent items with timestamps
  - [ ] Filters by keyword/hashtag (e.g., $SPY, Fed, oil)
- **Technical Requirements:**
  - Python scraper using `tweepy`, `telethon`, `feedparser`
  - Rate limit handling (X API: 300 requests/15 min)
  - Caching to avoid redundant fetches

**2. AI Narrative Extraction**
- **User Story:** "As a trader, I want AI to identify the top 3 market narratives from 100+ posts, so I can focus on what matters"
- **Acceptance Criteria:**
  - [ ] Claude API integration (Sonnet 4 for cost efficiency)
  - [ ] Outputs structured data: Narrative, Supporting Evidence, Risk Score (1-10)
  - [ ] Physics-inspired analogies (entropy, momentum, phase transitions)
  - [ ] Processing time: <60 seconds for 100 posts
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

Output as JSON:
{
  "narratives": [
    {
      "title": "Fed Dovish Pivot",
      "entropy_risk": 3,
      "hypothesis": "Long QQQ calls",
      "rationale": "...",
      "catalysts": ["FOMC minutes 2/21", "CPI data 2/28"]
    }
  ]
}
```

**3. Dashboard UI**
- **User Story:** "As a trader, I want a clean interface that shows insights without clutter"
- **Wireframe Components:**
  - Top Banner: Daily brief (1-sentence summary)
  - Card Grid: 3 narrative cards with expand/collapse
  - Side Panel: Raw feeds (scrollable)
  - Bottom: Trade journal (log executed trades)
- **Tech Stack:**
  - React + Tailwind CSS (responsive, modern)
  - Recharts for entropy timeseries
  - LocalStorage for user preferences

**4. Trade Journal**
- **User Story:** "As a trader, I want to log trades based on signals so I can measure accuracy over time"
- **Acceptance Criteria:**
  - [ ] Manual entry: Symbol, Entry, Thesis, P&L
  - [ ] Links to originating narrative
  - [ ] Win rate calculation (closed trades only)
  - [ ] Export to CSV

#### **Nice-to-Have (Post-MVP)**
- Real-time alerts (Telegram bot: "High entropy event detected")
- Backtesting: "Show me all 'Fed dovish' signals from 2024"
- Social sharing: "Tweet my daily brief"
- Mobile app (React Native)

---

## 📐 Technical Architecture

### System Design (High-Level)

```
┌─────────────────┐
│   Data Sources  │
│ (X, Telegram,   │
│  Substack)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Scraper Layer  │
│  (Python cron)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Data Store    │
│ (SQLite/Postgres│
│  for MVP)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AI Processing  │
│ (Claude API via │
│  FastAPI)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Frontend (React│
│  Dashboard)     │
└─────────────────┘
```

### Data Models

**Feed Item**
```python
{
  "id": "uuid",
  "source": "twitter",
  "author": "@zerohedge",
  "content": "BREAKING: Fed signals...",
  "timestamp": "2026-02-15T08:30:00Z",
  "url": "https://x.com/...",
  "keywords": ["fed", "rates"]
}
```

**Narrative**
```python
{
  "id": "uuid",
  "date": "2026-02-15",
  "title": "Fed Dovish Pivot",
  "entropy_risk": 3,
  "hypothesis": "Long QQQ calls",
  "supporting_feeds": ["feed_id_1", "feed_id_2"],
  "status": "active" | "expired" | "executed"
}
```

**Trade**
```python
{
  "id": "uuid",
  "narrative_id": "uuid",
  "symbol": "QQQ",
  "entry_price": 485.0,
  "exit_price": 490.5,
  "pnl_percent": 1.13,
  "outcome": "win" | "loss"
}
```

---

## 📊 Success Metrics & Analytics

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
- Entropy score correlation with volatility (measure R²)

**Business Metrics:**
- Free → Paid conversion rate (target: 10%)
- Churn rate (target: <20% monthly)
- NPS (Net Promoter Score) (target: 40+)

### Analytics Implementation
```javascript
// Example event tracking
trackEvent('narrative_viewed', {
  narrative_id: 'abc123',
  entropy_risk: 7,
  user_action: 'expanded' | 'ignored'
});

trackEvent('trade_logged', {
  symbol: 'QQQ',
  outcome: 'win',
  pnl_percent: 1.13,
  from_narrative: true
});
```

---

## 🚀 Go-to-Market Strategy

### Phase 1: Portfolio & Early Validation (Month 1)
- Build MVP for personal use
- Document on LinkedIn/Substack (build in public)
- Recruit 5 beta users from trading X/Telegram communities
- Collect qualitative feedback

### Phase 2: Product-Market Fit (Month 2-3)
- Refine based on beta feedback
- Add top 2 requested features
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
- 7-day trade journal history

**Pro Tier ($49/month):**
- Unlimited feeds
- Real-time updates (15-min refresh)
- Unlimited trade journal + backtest
- Export to CSV/Notion
- Priority support

**Enterprise ($499/month):**
- White-label dashboard
- Custom sources (Bloomberg, internal Slack)
- Team collaboration features
- API access

---

## 🗓️ Development Roadmap

### Week 1: Foundation (Current)
- [x] PRD completion
- [ ] Python scraper prototype
- [ ] Market research doc
- [ ] GitHub repo setup

### Week 2: Core Build
- [ ] Working scraper (X + Telegram + RSS)
- [ ] Claude API integration
- [ ] SQLite database schema
- [ ] Basic FastAPI backend

### Week 3: Frontend MVP
- [ ] React dashboard scaffolding
- [ ] Narrative card components
- [ ] Trade journal UI
- [ ] Deployed on Vercel

### Week 4: Polish & Portfolio
- [ ] User testing with 3 traders
- [ ] Case study write-up
- [ ] Demo video
- [ ] LinkedIn launch post

---

## ❓ Open Questions & Risks

### Technical Risks
**Q:** Can we scrape X without getting rate-limited?  
**Mitigation:** Use official API with caching, or fallback to RSS feeds

**Q:** Will Claude API costs blow up with 50+ users?  
**Mitigation:** Batch processing, cache narratives, use Haiku for simple tasks

### Product Risks
**Q:** Will users actually log trades, or is manual entry too much friction?  
**Mitigation:** Auto-import from brokerage APIs (TD Ameritrade, Alpaca) in v2

**Q:** Is "entropy risk" too abstract for non-technical users?  
**Mitigation:** A/B test with simpler label like "Uncertainty Score"

### Market Risks
**Q:** Does this violate X/Telegram ToS?  
**Mitigation:** Review ToS, use official APIs only, add disclaimer

---

## 📚 Appendix

### User Research Interview Script
```
1. Walk me through your morning routine for market research
2. Which sources do you check first? Why?
3. Tell me about a time you missed an important signal
4. How do you currently take notes or log trades?
5. What would make you pay $49/month for a tool like this?
```

### Competitive Feature Matrix
| Feature | Bloomberg | Koyfin | StockTwits | RedHood |
|---------|-----------|--------|------------|---------|
| Social feeds | ❌ | ❌ | ✅ | ✅ |
| AI analysis | ❌ | ❌ | ❌ | ✅ |
| Trade journal | ✅ | ❌ | ❌ | ✅ |
| Price | $24K/yr | Free | Free | $49/mo |

### Related Resources
- [Arbitrage Andy Substack](https://arbitrageandy.substack.com/)
- [Product Hunt: Top Finance Tools 2025](https://producthunt.com)
- [LLM Prompting for Finance](https://docs.anthropic.com)

---

**Document History:**
- v1.0 (Feb 15, 2026): Initial PRD
- v1.1 (TBD): Post-user testing revisions

