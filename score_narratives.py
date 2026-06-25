"""
RedHood Insights — Score Narratives CLI
========================================
Reads every row in the `narratives` table, runs redhood_grader.grade() on
its hypothesis, and writes results to narrative_tickers + narrative_grades.

Idempotent: existing rows for a narrative are replaced. Safe to re-run.

Usage:
    python score_narratives.py                        # score all
    python score_narratives.py --since 2026-03-01     # score recent only
    python score_narratives.py --dry-run              # print, don't persist
    python score_narratives.py --with-pnl             # also refresh prices/P&L
"""

from __future__ import annotations

import argparse
import sqlite3
import os
import sys
from datetime import datetime, timezone

# Make sibling modules importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import init_schema, DB_PATH
from redhood_grader import grade


def score_all(db_path: str = DB_PATH,
              since: str | None = None,
              dry_run: bool = False) -> dict:
    """Run grader against all narratives, persist tickers + grades.

    Returns a small stats dict so callers / CI can verify expected counts.
    """
    init_schema(db_path)  # idempotent, ensures new tables exist
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT id, hypothesis, catalysts, conviction_adjustment, created_at
        FROM narratives
    """
    params: tuple = ()
    if since:
        sql += " WHERE created_at >= ?"
        params = (since,)
    sql += " ORDER BY created_at"

    narratives = conn.execute(sql, params).fetchall()
    if not narratives:
        print("No narratives found.")
        conn.close()
        return {"narratives": 0, "tickers": 0, "grades": 0}

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    n_grades = 0
    n_tickers = 0

    for n in narratives:
        g = grade(n['hypothesis'],
                  catalysts_json=n['catalysts'],
                  conviction_adjustment=n['conviction_adjustment'])
        if dry_run:
            print(f"[{n['id']}] {g.letter}  total={g.total}/20  "
                  f"long={g.long_tickers}")
            continue

        # Replace any existing rows for this narrative (idempotent)
        conn.execute("DELETE FROM narrative_grades  WHERE narrative_id = ?", (n['id'],))
        conn.execute("DELETE FROM narrative_tickers WHERE narrative_id = ?", (n['id'],))

        conn.execute(
            "INSERT INTO narrative_grades "
            "(narrative_id, specificity, catalyst_score, risk_score, "
            " cohesion, total_score, letter_grade, graded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (n['id'], g.specificity, g.catalyst, g.risk, g.cohesion,
             g.total, g.letter, now)
        )
        n_grades += 1

        for ticker in g.long_tickers:
            try:
                conn.execute(
                    "INSERT INTO narrative_tickers "
                    "(narrative_id, ticker, side, is_long_equity, extracted_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (n['id'], ticker, 'long', now)
                )
                n_tickers += 1
            except sqlite3.IntegrityError:
                pass  # duplicate (narrative, ticker, side)

    conn.commit()
    conn.close()

    stats = {
        "narratives": len(narratives),
        "tickers":    n_tickers,
        "grades":     n_grades,
    }
    print(f"Scored {stats['narratives']} narratives — "
          f"{stats['grades']} grades, {stats['tickers']} long tickers persisted.")
    return stats


def main():
    p = argparse.ArgumentParser(description="Score narratives and write to redhood.db")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--since", help="Only score narratives created on/after this ISO date")
    p.add_argument("--dry-run", action="store_true",
                   help="Print grades but don't write to DB")
    p.add_argument("--with-pnl", action="store_true",
                   help="After scoring, also refresh prices and print P&L leaderboard")
    args = p.parse_args()

    score_all(db_path=args.db, since=args.since, dry_run=args.dry_run)

    if args.with_pnl and not args.dry_run:
        try:
            from redhood_pnl import compute_pnl, print_leaderboard
            rows = compute_pnl(db_path=args.db)
            print_leaderboard(rows)
        except ImportError as e:
            print(f"P&L step skipped: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
