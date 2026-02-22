# Portfolio Case Study: RedHood Insights
## Building an AI-Powered Market Intelligence Platform from Scratch

**Author:** Tazeem Chowdhury
**Role:** Product Manager | Business Analyst | Financial Markets Analyst
**Timeline:** February 2026 (4 weeks)
**Status:** MVP Complete

---

## TL;DR (Executive Summary)

**Problem:** Retail traders waste 2-4 hours daily aggregating market intelligence from fragmented sources (Twitter, Substack), leading to information overload and missed opportunities.

**Solution:** Built an AI-powered pipeline that aggregates feeds, extracts top narratives using Claude, scores them with "entropy risk", generates a styled **RedHood Reads** HTML briefing every run, and persists all data to SQLite — reducing research time by 83%.

**Outcome:**
- Full pipeline running end-to-end in <60 seconds per run
- Styled editorial HTML report auto-generated each run
- SQLite database with all runs, feeds, narratives, and tracked accounts
- CLI account management for adding/removing tracked X/Twitter handles
- Integrated trading system analysis with thermodynamic position sizing
- Comprehensive PRD with user research and competitive analysis
- Market validation: 66% willingness-to-pay at $49/month price point

---

## The Challenge

### Context

As a trader and product manager, I experienced firsthand the pain of information overload in financial markets. Every morning, I would spend 3+ hours:

1. Checking 30+ Twitter accounts for market-moving news
2. Reading 5 Substack newsletters (Arbitrage Andy, Doomberg, etc.)
3. Synthesizing everything into tradeable insights

**The problem:** This was exhausting, unsustainable, and I often missed critical signals when focused on other work.

### User Research

Before building anything, I validated the problem with 50 traders (survey + interviews):

**Key Findings:**
- 70% spend 1-3 hours daily on market research
- 94% use Twitter as primary source
- 46% cite "too much noise" as biggest pain point
- 66% would pay $50/month for automated solution

**Persona: "Active Alex"**
- Age: 28-42, software engineer/analyst
- Portfolio: $75K-$350K
- Pain: Misses signals during work hours, can't quantify risk systematically
- Quote: *"I need Bloomberg-quality insights without the $24K/year price tag"*

### Problem Statement

**How might we** help serious retail traders identify high-probability market opportunities without spending hours manually aggregating fragmented information sources?

---

## The Solution

### Product Vision

*"Spotify for market intelligence"* — A single platform that aggregates, curates, and analyzes all your market feeds using AI.

### Core Value Proposition

**For** serious retail traders
**Who** follow 10+ information sources but lack time to synthesize them
**RedHood Insights is** an AI-powered aggregation pipeline
**That** extracts top market narratives, scores entropy risk, and delivers a styled briefing every run
**Unlike** Bloomberg Terminal (too expensive) or manual scrolling (too time-consuming)
**Our product** delivers institutional-quality insights at consumer prices using LLM-native architecture

### Key Features (MVP — Shipped)

#### 1. Multi-Source Aggregation
- **What:** Single pipeline for X/Twitter (Nitter RSS) and Substack RSS
- **Why:** No Twitter API key required — free, reliable, zero credential friction
- **How:** feedparser + multi-instance Nitter fallback for resilience

#### 2. AI Narrative Extraction
- **What:** Claude processes 50+ feeds → identifies top 3 market themes
- **Why:** Signal extraction from noise
- **How:** Engineered prompt with structured JSON output; fallback parser strips markdown fences

#### 3. Entropy Risk Scoring
- **What:** Quantifies market uncertainty (1-10 scale)
- **Why:** Physics-inspired differentiator — low entropy = stable consensus, high = conflicting signals
- **How:** AI analyzes signal consensus; sparklines in HTML report visualize risk level

#### 4. RedHood Reads HTML Report
- **What:** Styled editorial card report auto-generated every run
- **Why:** Portfolio-ready output; visualizes narratives in a professional format
- **How:** `%%TOKEN%%` placeholder system (avoids f-string/CSS brace conflicts); Playfair Display + IBM Plex Mono design

#### 5. SQLite Persistence
- **What:** All runs, feeds, narratives, and join tables stored in `redhood.db`
- **Why:** Historical tracking, deduplication, queryable data
- **How:** `INSERT OR IGNORE` for feed deduplication; unique narrative IDs via `f"narrative_{time}_{id(self)}"`

#### 6. Account Management CLI
- **What:** `accounts_db.py` — add, remove, toggle, list tracked X/Twitter accounts
- **Why:** DB-backed config avoids hardcoded lists; supports per-account metadata (category, notes)
- **How:** SQLite `twitter_accounts` table; `get_active_handles()` called each run

#### 7. Trading System (run.ps1)
- **What:** Thermodynamic position-sizing model integrated in PowerShell runner
- **Why:** Ties RedHood narrative signals to actual sizing recommendations
- **How:** Yahoo Finance data; temperature/entropy/momentum/RSI calculations; `IN/OUT/NEUTRAL` recommendations

---

## The Process

### Phase 1: Discovery & Strategy (Week 1)

**Activities:**
1. **User Research** — Surveyed 50 traders on research habits; interviewed 5 power users
2. **Market Analysis** — TAM/SAM/SOM ($7.5B → $1.2B → $5.9M); competitive research
3. **PRD Development** — User stories, acceptance criteria, 4-week roadmap

**Key Decision:** Use Nitter RSS for Twitter (no API key, no rate limits, free). Defer Telegram indefinitely (added complexity with no proportional value).

---

### Phase 2: Technical Execution (Weeks 2–3)

**Build Approach:**
- **Language:** Python (fastest for data processing + API calls)
- **AI:** Anthropic Claude Sonnet 4.6 (best cost/performance for financial analysis)
- **Architecture:** Pipeline (scrape → AI → SQLite + HTML + JSON)

**Technical Challenges & Solutions:**

**Challenge 1: Nitter Instance Reliability**
- Problem: Individual Nitter instances go offline or rate-limit
- Solution: Multi-instance list with automatic fallback; skip on failure, log warning
- Learning: External RSS proxies need resilience baked in from the start

**Challenge 2: LLM Output Consistency**
- Problem: Claude sometimes returned prose instead of JSON
- Solution: Prompt with "ONLY return valid JSON" instruction + fallback parser to strip markdown fences
- Learning: LLM prompt engineering is 50% of the work

**Challenge 3: Narrative ID Collisions**
- Problem: Three narratives created within the same second got identical `narrative_{int(time.time())}` IDs; `INSERT OR IGNORE` silently dropped two of three
- Solution: Changed ID to `f"narrative_{int(time.time())}_{id(self)}"` — Python object identity is unique per instance
- Learning: Time-based IDs are fragile for batch creation; always add object identity or UUID

**Challenge 4: CSS Brace Conflicts in HTML Generation**
- Problem: CSS `{}` blocks can't be inside Python f-strings without doubling every brace
- Solution: Plain string template with `%%TOKEN%%` placeholders + `.replace()` chaining
- Learning: Keep templating systems simple — avoid fighting language escaping rules

**Challenge 5: Cost Control**
- Problem: Processing 100+ feeds = expensive at scale
- Solution: Limited to 50 most recent feeds per run
- Estimated cost: $0.50–2.00/user/month (acceptable unit economics)

---

### Phase 3: Validation & Documentation (Week 4)

**User Testing:**
- Shared with 5 beta users (traders from my network)
- Collected feedback via structured interviews

**Positive Feedback:**
- "This would save me 2 hours every morning"
- "The AI summaries are actually good — better than I expected"
- "I love the entropy scoring — helps me avoid FOMO trades"
- "The HTML report looks like something you'd pay for"

**Critical Feedback:**
- "Need mobile access (currently desktop-only)"
- "Would pay more for real-time alerts (not just batch)"
- "Want to track which signals actually led to profitable trades"

**Iterations:**
- Added trade journal structure to PRD (v2 feature)
- Prioritized backtest feature for v2

---

## Results & Impact

### Quantitative Outcomes

**Time Savings:**
- Before: 180 minutes/day (manual aggregation)
- After: 30 minutes/day (with RedHood)
- **Impact: 83% reduction, 15 hours/week saved**

**Cost Efficiency:**
- Bloomberg Terminal: $24,000/year
- RedHood (projected): $588/year
- **Impact: 97.5% cost reduction for comparable insights**

**Technical Performance:**
- Processes 50 feeds in <60 seconds
- API costs: ~$1.50/day in development
- Projected: $0.50–2.00/user/month at scale

### Qualitative Outcomes

**Product-Market Fit Signals:**
- 66% willingness-to-pay validation (N=50 survey)
- 5/5 beta users requested access to full version
- Positive feedback on "entropy risk" differentiation
- HTML report design validated as professional-grade

---

## Key Learnings

### What Went Well

**1. No-API-Key Twitter Scraping**
- Nitter RSS eliminated the #1 friction point (Twitter API access)
- Delivered real Twitter data with zero credential setup
- Learning: Always look for free-tier alternatives before API integrations

**2. SQLite from Day One**
- DB persistence built in Week 3 instead of "v2"
- Enables historical analysis, deduplication, and queryable data
- Learning: Shipping storage early compounds value with every run

**3. Template-Based HTML Generation**
- `%%TOKEN%%` approach kept the HTML template readable and CSS conflict-free
- Learning: Avoid fighting language escaping rules — use the simplest templating system that works

### What I'd Do Differently

**1. Earlier User Testing**
- Waited until Week 4 to share with beta users
- Should have shown mockups in Week 1–2
- Learning: Fail fast with low-fidelity prototypes

**2. Mobile-First Thinking**
- Built desktop-first; users wanted mobile
- Lesson: Always ask "where/when will users actually use this?"

**3. Metrics Instrumentation**
- Should have built analytics tracking into the DB schema from Day 1
- Learning: "If you can't measure it, you can't improve it"

---

## Next Steps & Roadmap

### Immediate (Month 1–2)
- [ ] Deploy web dashboard (React + FastAPI)
- [ ] Add trade journal with backtest capability
- [ ] Live ticker data in HTML report (wire to Yahoo Finance from run.ps1)
- [ ] Target: 50 users (10 paid at $49/month)

### Short-Term (Month 3–6)
- [ ] Real-time alerts (Telegram bot)
- [ ] Mobile app (React Native)
- [ ] B2B features (team collaboration)
- [ ] Target: 500 users, $15K MRR

### Long-Term (Year 1+)
- [ ] API for developers
- [ ] Marketplace for custom feeds
- [ ] Enterprise tier for RIAs/funds
- [ ] Target: 10K users, $500K ARR

---

## Skills Demonstrated

### Strategy & Business
- Market sizing (TAM/SAM/SOM analysis)
- Competitive analysis (5 direct competitors researched)
- Pricing strategy (validated $49/month price point)
- Go-to-market planning (Product Hunt launch plan)

### Product & User Research
- User interviews (5 deep dives)
- Survey design & analysis (N=50 traders)
- Persona development ("Active Alex")
- Jobs-to-be-done framework

### Technical Execution
- Python development (600+ lines production code)
- Nitter RSS scraping (no API key required)
- AI prompt engineering (Claude for structured analysis)
- SQLite schema design (5 tables, indexes, JOIN table)
- HTML report generation with CSS template system
- PowerShell trading system with thermodynamic sizing

### Communication & Documentation
- PRD writing (comprehensive spec)
- Technical documentation (README, inline comments)
- Case study creation (this document)
- Release notes and version management

---

## Appendix

### Resources & Tools Used

**Development:**
- Python 3.9 (core language)
- Anthropic Claude API (AI analysis)
- feedparser (RSS + Nitter parsing)
- python-dotenv (environment config)
- SQLite (persistence)
- GitHub (version control)
- VS Code (IDE)

**Documentation:**
- Markdown (all docs)
- Notion (project planning)

### Portfolio Links

- **GitHub Repo:** [github.com/tazeemc/Redhood-Systems](https://github.com/tazeemc/Redhood-Systems)
- **LinkedIn:** [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
- **Newsletter:** [RedHood Reads on Substack](https://substack.com/@redhoodcapital)
- **Twitter/X:** [@redhoodcapital](https://x.com/redhoodcapital)

### Testimonials

> "This is exactly what I've been looking for. The entropy risk framework is brilliant — it helps me avoid emotional trading decisions based on FOMO."
> — Beta User #1 (Software Engineer, $200K portfolio)

> "As someone who follows 20+ X accounts, this would save me at least 10 hours per week. I'd easily pay $50/month for this."
> — Beta User #2 (Quant Analyst, $500K portfolio)

> "The HTML report looks like something you'd actually pay for. The AI summaries capture nuance instead of just averaging sentiment."
> — Beta User #3 (Data Scientist, $150K portfolio)

---

## Let's Connect

**Interested in discussing this project or exploring opportunities?**

Email: [ctazeem@gmail.com](mailto:ctazeem@gmail.com)
LinkedIn: [linkedin.com/in/tazeemchowdhury](https://www.linkedin.com/in/tazeemchowdhury/)
Twitter/X: [@redhoodcapital](https://x.com/redhoodcapital)
Newsletter: [RedHood Reads on Substack](https://substack.com/@redhoodcapital)

---

**Project Timeline:** February 2026 (4 weeks)
**Status:** MVP Complete, Live System Running
**Case Study Version:** 1.1 (Updated February 22, 2026)

*This case study was prepared for portfolio and job application purposes. All data and metrics are based on actual research and development work.*
