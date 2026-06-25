# RedHood Systems — Power BI Report Layout

## Setup checklist

1. Run `python powerbi/export_to_powerbi.py` to generate `powerbi/data/*.csv`
2. Open Power BI Desktop → Get Data → Text/CSV → import all 5 files
3. Open Transform Data, apply the M scripts in `power_query.m` per table
4. Close & Apply
5. Create a DateTable (formula in `power_query.m`) and mark it as Date Table
6. Build relationships (Model view):
   - `dim_runs[run_id]` → `fact_narratives[run_id]` (1:many)
   - `dim_runs[run_id]` → `fact_feeds[run_id]` (1:many)
   - `fact_narratives[narrative_id]` → `bridge_narrative_feeds[narrative_id]` (1:many)
   - `fact_feeds[feed_id]` → `bridge_narrative_feeds[feed_id]` (1:many)
   - `DateTable[Date]` → `dim_runs[run_date]` (1:many)
7. Add all DAX measures from `dax_measures.dax`

---

## Page 1 — Market Pulse Overview

**Purpose:** Single-glance view of market conditions right now.

| Visual | Type | Fields |
|--------|------|--------|
| Market Pulse Score | KPI Card | `[Market Pulse Score]` |
| Signal Quality Score | KPI Card | `[Signal Quality Score]` |
| Avg Entropy Risk | KPI Card (gauge) | `[Avg Entropy Risk]` |
| Actionable Rate | KPI Card | `[Actionable Rate]` (formatted %) |
| Entropy Risk Over Time | Line chart | X: `dim_runs[run_date]`, Y: `[Avg Entropy Risk]` |
| Conviction Mix | Donut chart | Legend: conviction label (Full/Half/Quarter/Pass), Values: narrative count |
| Latest Narratives | Table | `title`, `entropy_band`, `conviction_adjustment`, `hypothesis` — sorted by `created_at` DESC, top 10 rows |

**Slicer:** `dim_runs[run_date]` (relative date — last 30 days default)

---

## Page 2 — Narrative Deep Dive

**Purpose:** Drill into individual narratives, compare entropy, review hypotheses.

| Visual | Type | Fields |
|--------|------|--------|
| Entropy Risk Distribution | Bar chart | X: `entropy_band` (sorted by `entropy_band_order`), Y: COUNTROWS |
| Narratives by Entropy Band | Matrix | Rows: `entropy_band`, Cols: `conviction_size`, Values: COUNTROWS |
| Narrative Explorer | Table (scrollable) | `title`, `entropy_risk`, `entropy_band`, `hypothesis`, `catalysts`, `bear_case`, `conviction_adjustment`, `supporting_feed_count` |
| Top Catalysts Word Frequency | Word Cloud* | Field: `fact_narratives[catalysts]` |
| Supporting Feed Count by Narrative | Scatter | X: `entropy_risk`, Y: `supporting_feed_count`, Size: bubble, Details: `title` |

*Requires the Word Cloud custom visual from AppSource.

**Slicer:** `entropy_band`, `conviction_adjustment` (multi-select)
**Drill-through page:** From any narrative row → Page 5 (Narrative Detail)

---

## Page 3 — Feed Intelligence

**Purpose:** Understand source volume, timing patterns, and author coverage.

| Visual | Type | Fields |
|--------|------|--------|
| Total Feeds | KPI Card | `[Total Feed Items]` |
| Twitter vs RSS Split | Donut chart | Legend: `source`, Values: COUNTROWS |
| Feeds by Author | Horizontal bar | Y: `author`, X: COUNTROWS — top 15 |
| Feeds by Hour of Day | Column chart | X: `published_hour`, Y: COUNTROWS (show market hours 9-16 in different colour via conditional formatting) |
| Feeds by Day of Week | Column chart | X: `published_dow`, Y: COUNTROWS (sort Mon→Sun) |
| Feed Volume Over Time | Area chart | X: `published_date`, Y: COUNTROWS, Series: `source` |
| Account Status | Table | `dim_accounts`: `handle_at`, `category`, `active`, `added_date` |

**Slicer:** `source`, `author`, date range

---

## Page 4 — Run Analytics

**Purpose:** Track pipeline health and output quality over time.

| Visual | Type | Fields |
|--------|------|--------|
| Total Runs | KPI Card | `[Total Runs]` |
| Avg Feeds Per Run | KPI Card | `[Avg Feeds Per Run]` |
| Avg Narratives Per Run | KPI Card | `[Avg Narratives Per Run]` |
| Feeds Collected Per Run | Line chart | X: `run_date`, Y: `feeds_collected` |
| Narratives Extracted Per Run | Line chart | X: `run_date`, Y: `narratives_extracted` |
| Runs Table | Table | `run_date`, `run_hour`, `feeds_collected`, `narratives_extracted`, `hours_back` |

---

## Page 5 — Narrative Detail (Drill-through)

**Purpose:** Full detail card for a single narrative. Reached via drill-through from Page 2.

| Visual | Type | Fields |
|--------|------|--------|
| Title | Card | `title` |
| Entropy Risk | Gauge | `entropy_risk`, min=1, max=10, target=5 |
| Conviction | Card | `conviction_adjustment` |
| Hypothesis | Multi-row card | `hypothesis` |
| Rationale | Multi-row card | `rationale` |
| Bear Case | Multi-row card | `bear_case` |
| Disconfirming Signals | Multi-row card | `disconfirming_signals` |
| Catalysts | Multi-row card | `catalysts` |
| Supporting Feeds | Table | via `bridge_narrative_feeds` → `fact_feeds`: `author`, `content_clean`, `published_date`, `url` |

---

## Colour theme (RedHood branding)

| Use | Hex |
|-----|-----|
| Primary (red) | `#C0392B` |
| Dark background | `#1A1A1A` |
| Card background | `#242424` |
| Neutral text | `#E5E5E5` |
| Low entropy (calm) | `#27AE60` |
| Medium entropy | `#F39C12` |
| High entropy | `#E74C3C` |
| Critical entropy | `#8E44AD` |

To apply: View → Themes → Customise current theme → paste hex values above.

---

## Conditional formatting rules

**Entropy Risk column in any table:**
- Rules: 1-3 = `#27AE60`, 4-6 = `#F39C12`, 7-8 = `#E74C3C`, 9-10 = `#8E44AD`
- Apply to: Background colour, based on field value

**Conviction column:**
- "Full Size" = `#27AE60`
- "Half Size" = `#F39C12`
- "Quarter Size" = `#E67E22`
- "Pass" = `#7F8C8D`

---

## Page 6 — Ticker Leaderboard (added 2026-05 audit)

**Purpose:** Surface tickers that recur as long winners across runs — the "add to winners" view. Built on `fact_narrative_tickers` and `fact_prices`.

| Visual | Type | Fields |
|--------|------|--------|
| Total Tickets | KPI Card | `[Ticker Mention Count]` |
| Distinct Tickers | KPI Card | `[Distinct Tickers]` |
| Cumulative P&L $ | KPI Card | `[Cumulative P&L $]` (formatted $) |
| Avg Return % | KPI Card | `[Avg Return %]` (formatted %) |
| Win Rate | KPI Card | `[Win Rate]` (formatted %) |
| Leaderboard | Table | `ticker`, `[Ticker Mention Count]`, `[Long Mentions]`, `[Long Mentions L30D]`, `[Total Position $]`, `[Cumulative P&L $]`, `[Avg Return %]` — sorted by Cumulative P&L $ descending |
| P&L by Ticker | Bar | Y: `ticker` (top 20), X: `[Cumulative P&L $]`, conditional formatting on bar colour |

**Slicers:** date range from `dim_runs[run_date]`, `letter_grade`, `entropy_band`, `side`.

**Conditional formatting:**
- `letter_grade` cells: A=green (#27AE60), A-=light green (#9CD49C), B=yellow (#F39C12), C=orange (#E67E22), D=red (#E74C3C), F=purple (#8E44AD).
- `Cumulative P&L $`: red→white→green colour scale.

---

## Page 7 — Mentions Over Time (added 2026-05 audit)

**Purpose:** Catch tickers quietly accumulating recurrence — the leap-frog setup before price moves.

| Visual | Type | Fields |
|--------|------|--------|
| Mentions per Week | Stacked Area | X: `dim_runs[run_date]` (week), Y: `[Long Mentions]`, Series: top-10 `ticker` |
| Heatmap (Ticker × Week) | Matrix | Rows: `ticker`, Cols: `dim_runs[run_date]` (week), Values: `[Long Mentions]`, conditional fill |
| Recurring Streak | Card | New measure (DAX sketch in `dax_measures.dax`); count of consecutive weeks with ≥1 mention for the selected ticker |
| Recent vs Trailing | Combo bar+line | X: `ticker` (top 20), bar: `[Long Mentions L30D]`, line: `[Long Mentions L90D]` — visual gauge of acceleration |

**Slicer:** sector or letter-grade filter so the "winners" view only includes A/A-/B grades.

---

## Calculated columns required on `fact_narrative_tickers`

Add these in the Power BI Modeling pane (not as measures — they need to be at row-level for SUMX-style P&L formulas):

```
entry_close =
LOOKUPVALUE(
    fact_prices[close],
    fact_prices[ticker],     fact_narrative_tickers[ticker],
    fact_prices[price_date], fact_narrative_tickers[entry_date]
)

last_close =
CALCULATE(
    MAX(fact_prices[close]),
    ALLEXCEPT(fact_prices, fact_prices[ticker])
)
```

(Or pre-compute these in `export_to_powerbi.py` — already done as columns
on `fact_narrative_tickers.csv` for convenience.)

---

## Refresh sequence (audit pipeline)

```bash
python redhood_aggregator.py --hours 24      # 1. Pull feeds, extract narratives
python score_narratives.py                   # 2. Grade + extract long tickers
python redhood_pnl.py --report               # 3. Refresh prices + compute P&L
python powerbi/export_to_powerbi.py          # 4. Emit CSVs for Power BI
# Then: open Power BI Desktop → Refresh
```
