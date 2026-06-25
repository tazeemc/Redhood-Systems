# Power BI Integration

This document describes how `Redhood Systems Analysis.pbix` should consume
`redhood.db` after the 2026-05-06 model audit. It supersedes the Power Query
rename steps that the original .pbix used to derive `dim_runs` and
`fact_narratives` from the raw `runs` / `narratives` tables.

## Tables vs. views

The Python code keeps idiomatic SQLite names (`runs`, `narratives`,
`narrative_tickers`, `tickers`, `prices`, `earnings`, `date_dim`).

Power BI imports the **views** below — they apply the audit's `dim_/fact_`
naming, surface derived columns, and pre-join FKs that the report needs.

| View                       | Backed by                          | Cardinality |
| -------------------------- | ---------------------------------- | ----------- |
| `dim_runs`                 | `runs`                             | 1 row / run |
| `fact_narratives`          | `narratives`                       | 1 row / narrative |
| `fact_narratives_ticker`   | `narrative_tickers` + `narratives` | many rows / narrative |
| `fact_narrative_grades`    | `narrative_grades` + `narratives`  | 1 row / narrative |
| `dim_ticker`               | `tickers`                          | 1 row / symbol |
| `dim_date`                 | `date_dim`                         | 1 row / day  |
| `fact_prices`              | `prices`                           | 1 row / (ticker, date) |
| `fact_earnings`            | `earnings`                         | 1 row / (ticker, fiscal period) |

## Re-pointing the .pbix

In Power BI Desktop:

1. **Transform data → Data source settings →** confirm the SQLite ODBC source
   still points at the new `redhood.db`.
2. For each existing query, open the **Source** step and replace the table
   name with the corresponding view above (e.g. `runs` → `dim_runs`,
   `narratives` → `fact_narratives`).
3. **Delete the rename / split / type-conversion steps** in each query —
   the views already produce the columns the report needs.
4. **Disable** *File → Options → Data Load → Auto Date/Time* so Power BI
   stops creating per-column hierarchies. Then mark `dim_date` as the date
   table (Modeling → Mark as Date Table → `dim_date[date]`).
5. Wire relationships:
   - `fact_narratives[run_id]` → `dim_runs[run_id]`
   - `fact_narratives_ticker[narrative_id]` → `fact_narratives[narrative_id]`
   - `fact_narrative_grades[narrative_id]` → `fact_narratives[narrative_id]` (1:1)
   - `fact_narratives_ticker[ticker]` → `dim_ticker[ticker]`
   - `dim_runs[run_date]` → `dim_date[date]`
   - `fact_narratives[created_date]` → `dim_date[date]` (inactive — turn on
     for created-date analyses with `USERELATIONSHIP`)
   - `fact_prices[ticker]` → `dim_ticker[ticker]`,
     `fact_prices[date]` → `dim_date[date]`
   - `fact_earnings[ticker]` → `dim_ticker[ticker]`,
     `fact_earnings[report_date]` → `dim_date[date]`

## DAX measures (Section 6 of the audit)

Drop these into a `_Measures` table:

```dax
Mention Count          := COUNTROWS ( fact_narratives_ticker )

Long Mentions          := CALCULATE ( [Mention Count],
                              fact_narratives_ticker[side] = "Long" )

Short Mentions         := CALCULATE ( [Mention Count],
                              fact_narratives_ticker[side] = "Short" )

Net Direction Score    := [Long Mentions] - [Short Mentions]

Conviction Weighted Score :=
    SUMX (
        fact_narratives_ticker,
        COALESCE ( RELATED ( fact_narratives[conviction_size] ), 0 )
            * IF ( fact_narratives_ticker[side] = "Long", 1, -1 )
    )

Mentions L30D :=
    CALCULATE ( [Mention Count],
        DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -30, DAY ) )

Mentions L90D :=
    CALCULATE ( [Mention Count],
        DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -90, DAY ) )
```

`Earnings Window Flag` and `Beat-Aligned Long Rate` from Section 6 unlock
once `fact_earnings` has rows.

## Report pages

The audit's recommended Pages A–E (Leaderboard, Narrative Explorer,
Mentions Over Time, Earnings Overlay, Conviction Basket Tracker) all build
on these views. Page A and Page B are immediately deliverable from the
current dataset; Pages D and E require populating `fact_prices` and
`fact_earnings` first.

## Refresh

`backfill.py` is idempotent — re-running it after each ingestion catches
historical narratives that pre-date a given migration. New narratives
written by `redhood_aggregator.py` already populate the bridge and derived
columns inline, so a vanilla run leaves the dataset Power-BI-ready.
