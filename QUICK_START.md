# QUICK START GUIDE
## Get Up and Running in 15 Minutes

---

## What You Have

A complete, working portfolio project:
- Working Python aggregator with AI narrative extraction (Claude `claude-opus-4-8`)
- Styled **RedHood Reads** HTML report generated each run
- SQLite star-schema database storing runs, feeds, narratives, tickers, grades, and prices
- Narrative scoring/grading and a long-only P&L leaderboard
- Account management CLI for tracked X/Twitter handles
- PowerShell runner with integrated trading system analysis
- Professional PRD and market research documents

---

## Three Ways to Use This

### 1. For Job Applications (Fastest)

**Resume bullet point (copy-paste ready):**
```
• Built RedHood Systems, an AI-powered market intelligence pipeline that
  aggregates X/Twitter and Substack feeds, extracts top narratives via
  Claude AI, generates styled HTML briefings, and persists all data to
  SQLite — reducing trader research time by 83% (180 min → 30 min daily)
```

**Where to host:**
- Personal website portfolio page
- GitHub repo (already public: github.com/tazeemc/Redhood-Systems)
- LinkedIn featured section

---

### 2. Run with Real Data (Requires API Key)

**Setup (5 minutes):**

1. **Get Anthropic API Key** (free tier available)
   - Visit: https://console.anthropic.com/
   - Sign up → Get API key

2. **Create .env file:**
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```
> `yfinance` is an **optional** dependency — only needed for `redhood_pnl.py`
> or scoring with `--with-pnl`. The rest of the pipeline runs without it.

4. **Run via PowerShell (recommended):**
```powershell
.\run.ps1                              # 45-min window (default) + trading analysis
.\run.ps1 -Hours 5                     # last 5 hours
.\run.ps1 -Symbols "AAPL","MSFT"       # custom symbols
.\run.ps1 -Hours 24 -SkipTrading       # 24h RedHood only
.\run.ps1 -SkipRedHood                 # trading analysis only
```

5. **Or run Python directly:**
```bash
python redhood_aggregator.py                       # ~10-min window (default)
python redhood_aggregator.py --hours 1             # last 1 hour
python redhood_aggregator.py --trading-json PATH   # fold in run.ps1 trading output
```

**What it produces:**
- Console summary of top narratives
- `data/redhood_reads_TIMESTAMP.html` — styled editorial briefing
- `data/redhood_insights_TIMESTAMP.json` — raw feed + narrative data
- `redhood.db` entry for the run (all feeds + narratives persisted)

**Expected output:**
```
📰 Fetching RSS feeds...
   ✅ Found 18 RSS items

🐦 Fetching Twitter feeds...
   📋 Active accounts from DB: @unusual_whales, @FirstSquawk...
   ✅ Found 12 tweets

📊 Total feeds collected: 30

🧠 AI Analysis Phase...
✅ Extracted 3 narratives

[1] Fed Signals Dovish Pivot
    Entropy Risk: 🟢 LOW (3/10)
    💡 Hypothesis: Long QQQ calls...

📰 Report saved to: data/redhood_reads_20260222_083045.html
🗄️  DB: run #5 saved — 30 feeds, 3 narratives
```

---

### 3. Manage Tracked Accounts

The aggregator reads tracked Twitter accounts from SQLite. Default accounts are seeded automatically on first run.

```bash
# View all tracked accounts
python accounts_db.py --list

# Add a new account
python accounts_db.py --add FinancialJuice --category news --notes "Real-time headlines"

# Pause/resume an account
python accounts_db.py --toggle unusual_whales

# Remove an account
python accounts_db.py --remove SomeHandle
```

**Default accounts:**
| Handle | Category | Notes |
|--------|----------|-------|
| unusual_whales | market | Options flow and dark pool alerts |
| FirstSquawk | news | Real-time macro and geopolitical headlines |
| AutismCapital | macro | Macro intelligence and geopolitical signals |
| Mayhem4Markets | market | Market structure and volatility commentary |
| BasedBiohacker | bio | Biotech and health sector signals |

---

### 4. Score, Grade & Track P&L

Once you have narratives in the database, you can grade them, extract tickers, and track simulated performance.

```bash
# Grade every narrative -> narrative_tickers + narrative_grades (idempotent)
python score_narratives.py

# Only score narratives created on/after a date
python score_narratives.py --since 2026-06-01

# Preview grades without writing to the DB
python score_narratives.py --dry-run

# Score, then refresh prices and print the P&L leaderboard
python score_narratives.py --with-pnl

# Long-only P&L leaderboard ($2,500/ticker; needs yfinance)
python redhood_pnl.py --report

# Demo mode with sample data — no API key required
python demo.py
```

> `--with-pnl` and `redhood_pnl.py` require the optional `yfinance` package.

---

## File Guide

| File | Purpose |
|------|---------|
| `redhood_aggregator.py` | Main aggregator — scraping, AI, HTML report, DB persistence |
| `accounts_db.py` | CLI for managing tracked X/Twitter accounts in SQLite |
| `score_narratives.py` | Grade narratives + extract tickers into the DB |
| `redhood_pnl.py` | Long-only P&L leaderboard (optional, needs yfinance) |
| `demo.py` | Demo mode with sample data — no API key required |
| `models.py` | SQLite schema definitions + init helpers |
| `run.ps1` | PowerShell runner: trading analysis + RedHood aggregator |
| `redhood.db` | SQLite star-schema database (created automatically on first run) |
| `CASE_STUDY.md` | Portfolio writeup for job applications |
| `README.md` | Technical overview |
| `PRD_RedHood_Systems.md` | Product spec — shows PM thinking |
| `Market_Research_Analysis.md` | Business strategy — shows market acumen |

---

## Talking Points for Interviews

### "Walk me through a project you're proud of"

1. **Problem (30s):** "As a trader, I was spending 3+ hours daily aggregating market intelligence from Twitter, Substack, and newsletters. I validated this was a widespread pain point."

2. **Solution (30s):** "I built RedHood Systems — an AI-powered pipeline that aggregates feeds, uses Claude to extract top narratives with entropy risk scoring, generates styled HTML briefings, and persists everything to SQLite."

3. **Process (60s):** "I followed a full PM cycle: user research → PRD → prototype → validation. The interesting challenge was the Nitter RSS integration for Twitter (no API key needed) and prompt engineering to get consistent JSON from Claude."

4. **Results (30s):** "Reduced research time by 83%, validated 66% willingness-to-pay at $49/month, and shipped a system that generates styled market briefings every run."

5. **Learnings (30s):** "Key learning: I should have done mobile mockups earlier — users wanted mobile access. Next time I'll validate device preference in Week 1."

---

### "How do you approach product-market fit?"

- TAM/SAM/SOM analysis ($7.5B → $1.2B → $5.9M)
- User surveys (N=50) and interviews (N=5)
- Competitive gaps (no AI-native aggregation tool)
- Pricing validation (66% WTP at $49/mo)

**Show file:** `Market_Research_Analysis.md`

---

### "Can you show me code you've written?"

**Highlight in `redhood_aggregator.py`:**
- Modular architecture (scrapers, AI engine, DB layer separated)
- Nitter RSS scraping (multi-instance fallback for reliability)
- Prompt engineering for consistent JSON output
- `%%TOKEN%%` placeholder approach for CSS-safe HTML generation
- SQLite persistence with `INSERT OR IGNORE` deduplication
- Unique narrative ID via `f"narrative_{int(time.time())}_{id(self)}"`

---

## FAQ

**Q: Do I need a Twitter API key?**
A: No! Twitter/X is scraped via Nitter RSS — completely free, no API credentials required.

**Q: How much does Claude API cost?**
A: ~$0.50-2.00/day for personal use. You get free credit to start.

**Q: What if I don't know Python?**
A: For PM roles, showing the PRD and market research is often more valuable than the code itself. Use the CASE_STUDY.md as your primary artifact.

**Q: Where does output go?**
A: The `data/` folder. HTML reports open directly in any browser. JSON files can be viewed in any text editor or VS Code.

**Q: What's in the database?**
A: Open `redhood.db` with any SQLite viewer (DB Browser for SQLite is free). It's a star schema storing runs, feeds, and narratives plus extracted tickers, grades, and prices. Key tables: `runs`, `feeds`, `narratives`, `narrative_feeds`, `narrative_tickers`, `narrative_grades`, `tickers`, `prices`, `twitter_accounts`.

---

## Success Checklist

**Before your next interview:**
- [ ] Set up `.env` and run `python redhood_aggregator.py` successfully
- [ ] Open `data/redhood_reads_*.html` in a browser — see the styled report
- [ ] Run `python accounts_db.py --list` to see tracked accounts
- [ ] Run `python score_narratives.py` to grade narratives and extract tickers
- [ ] (Optional) Run `python redhood_pnl.py --report` for the P&L leaderboard
- [ ] No API key? Run `python demo.py` to see the pipeline on sample data
- [ ] Read and understand `CASE_STUDY.md`
- [ ] Update resume with bullet point above
- [ ] Practice 3-minute walkthrough

---

**You're ready to showcase this. Good luck!**

---

*Last updated: June 24, 2026*
