"""
RedHood Insights - Backfill
============================
Brings an existing redhood.db up to the post-audit star schema:

  1. Applies any pending schema migrations (additive, idempotent).
  2. Populates derived columns on `narratives`:
        catalyst_count, conviction_size, entropy_band
  3. Walks every narrative and writes rows into:
        tickers          (auto-seeded from extracted symbols)
        narrative_tickers (bridge — the audit's fact_narratives_ticker)
  4. Populates `date_dim` over a configurable range (default: 2023-01-01
     through end-of-next-year) so the dim_date view has rows.

Usage:
    python backfill.py
    python backfill.py --rebuild-tickers   # wipe + rebuild bridge from scratch
    python backfill.py --date-from 2024-01-01 --date-to 2027-12-31
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta

from models import DB_PATH, init_schema
from ticker_extraction import (
    extract_tickers,
    entropy_band,
    conviction_size,
    catalyst_count,
)


# ---------------------------------------------------------------------------
# Step 2 — derived columns on `narratives`
# ---------------------------------------------------------------------------

def backfill_derived_columns(conn: sqlite3.Connection) -> int:
    """Populate catalyst_count / conviction_size / entropy_band for every row."""
    rows = conn.execute(
        "SELECT id, entropy_risk, catalysts, conviction_adjustment FROM narratives"
    ).fetchall()
    updated = 0
    for nid, risk, cats_json, conv_adj in rows:
        cc = catalyst_count(cats_json)
        cs = conviction_size(conv_adj)
        eb = entropy_band(risk)
        conn.execute(
            """UPDATE narratives
                  SET catalyst_count  = ?,
                      conviction_size = ?,
                      entropy_band    = ?
                WHERE id = ?""",
            (cc, cs, eb, nid)
        )
        updated += 1
    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Step 3 — ticker bridge
# ---------------------------------------------------------------------------

def backfill_tickers(conn: sqlite3.Connection, *, rebuild: bool = False) -> tuple[int, int, int]:
    """Walk narratives, extract tickers, populate tickers + narrative_tickers.

    Returns (narratives_scanned, ticker_rows_written, distinct_tickers).
    """
    if rebuild:
        conn.execute("DELETE FROM narrative_tickers")
        conn.commit()

    now_iso = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT id, hypothesis FROM narratives WHERE hypothesis IS NOT NULL"
    ).fetchall()

    written = 0
    for nid, hypothesis in rows:
        for r in extract_tickers(hypothesis):
            conn.execute(
                "INSERT OR IGNORE INTO tickers (ticker, first_seen_at) VALUES (?, ?)",
                (r["ticker"], now_iso)
            )
            cur = conn.execute(
                """INSERT OR IGNORE INTO narrative_tickers
                       (narrative_id, ticker, side, extracted_pattern)
                   VALUES (?, ?, ?, ?)""",
                (nid, r["ticker"], r["side"], r["pattern"])
            )
            if cur.rowcount:
                written += 1

    conn.commit()
    distinct = conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    return len(rows), written, distinct


# ---------------------------------------------------------------------------
# Step 4 — date_dim populate
# ---------------------------------------------------------------------------

_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]
_DAY_NAMES   = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]


def populate_date_dim(conn: sqlite3.Connection,
                      start: date,
                      end: date) -> int:
    """Idempotently fill date_dim from `start` through `end` inclusive."""
    inserted = 0
    cur = start
    while cur <= end:
        next_day = cur + timedelta(days=1)
        is_month_end = 1 if next_day.month != cur.month else 0
        cur_iso = cur.isoformat()
        # ISO weekday: Mon=1..Sun=7  ->  we want Mon=0..Sun=6
        dow = cur.isoweekday() - 1
        result = conn.execute(
            """INSERT OR IGNORE INTO date_dim
                   (date, year, quarter, month, month_name, day,
                    day_of_week, day_name, iso_week, is_weekend, is_month_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cur_iso, cur.year, (cur.month - 1) // 3 + 1, cur.month,
             _MONTH_NAMES[cur.month - 1], cur.day,
             dow, _DAY_NAMES[dow], cur.isocalendar().week,
             1 if dow >= 5 else 0, is_month_end)
        )
        inserted += result.rowcount
        cur = next_day
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Verification — short report so users see what landed
# ---------------------------------------------------------------------------

def report(conn: sqlite3.Connection) -> None:
    print("\n=== Post-backfill summary ===")
    counts = {
        "runs":              "SELECT COUNT(*) FROM runs",
        "narratives":        "SELECT COUNT(*) FROM narratives",
        "narrative_tickers": "SELECT COUNT(*) FROM narrative_tickers",
        "tickers":           "SELECT COUNT(*) FROM tickers",
        "date_dim":          "SELECT COUNT(*) FROM date_dim",
    }
    for label, q in counts.items():
        print(f"  {label:<22} {conn.execute(q).fetchone()[0]:>8}")

    print("\n=== Top 10 tickers by mention count ===")
    top = conn.execute(
        """SELECT nt.ticker,
                  COUNT(*)                                                 AS mentions,
                  SUM(CASE WHEN nt.side='Long'  THEN 1 ELSE 0 END)         AS longs,
                  SUM(CASE WHEN nt.side='Short' THEN 1 ELSE 0 END)         AS shorts
             FROM narrative_tickers nt
            GROUP BY nt.ticker
            ORDER BY mentions DESC
            LIMIT 10"""
    ).fetchall()
    print(f"  {'ticker':<8} {'mentions':>9} {'longs':>7} {'shorts':>7}  net")
    for tk, mn, lg, sh in top:
        print(f"  {tk:<8} {mn:>9} {lg:>7} {sh:>7}  {(lg or 0) - (sh or 0):+d}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RedHood DB backfill")
    parser.add_argument("--rebuild-tickers", action="store_true",
                        help="Wipe narrative_tickers and re-extract from scratch.")
    parser.add_argument("--date-from", default="2023-01-01",
                        help="Start of date_dim range (YYYY-MM-DD).")
    parser.add_argument("--date-to",   default=None,
                        help="End of date_dim range (YYYY-MM-DD). "
                             "Defaults to Dec 31 of next year.")
    parser.add_argument("--skip-derived",  action="store_true")
    parser.add_argument("--skip-tickers",  action="store_true")
    parser.add_argument("--skip-dates",    action="store_true")
    args = parser.parse_args()

    init_schema()

    conn = sqlite3.connect(DB_PATH)
    try:
        if not args.skip_derived:
            n = backfill_derived_columns(conn)
            print(f"[1/3] derived columns updated on {n} narratives")

        if not args.skip_tickers:
            scanned, written, distinct = backfill_tickers(
                conn, rebuild=args.rebuild_tickers
            )
            print(f"[2/3] tickers — scanned {scanned} narratives, "
                  f"wrote {written} bridge rows, {distinct} distinct symbols")

        if not args.skip_dates:
            start = date.fromisoformat(args.date_from)
            if args.date_to:
                end = date.fromisoformat(args.date_to)
            else:
                end = date(date.today().year + 1, 12, 31)
            inserted = populate_date_dim(conn, start, end)
            total = conn.execute("SELECT COUNT(*) FROM date_dim").fetchone()[0]
            print(f"[3/3] date_dim - inserted {inserted} new rows "
                  f"({start} to {end}), total {total}")

        report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
