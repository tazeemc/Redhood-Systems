"""
RedHood Systems — Power BI Data Export
=======================================
Exports the redhood.db SQLite database into flat CSV files optimised
for direct import into Power BI Desktop.

Output files (written to ./powerbi/data/):
    dim_runs.csv          — one row per pipeline run
    dim_accounts.csv      — tracked Twitter/X handles
    fact_narratives.csv   — AI-extracted narratives (one row per narrative)
    fact_feeds.csv        — raw feed items (one row per post/tweet)
    bridge_narrative_feeds.csv — join table for narrative <-> feed relationships

Usage:
    python powerbi/export_to_powerbi.py

Author: Tazeem Chowdhury / RedHood Systems
"""

import sqlite3
import csv
import json
import os
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH     = os.path.join(PROJECT_DIR, 'redhood.db')
OUT_DIR     = os.path.join(SCRIPT_DIR, 'data')

os.makedirs(OUT_DIR, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def write_csv(filename: str, rows: list[dict], fieldnames: list[str]):
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f"  OK {filename}  ({len(rows)} rows)")


def parse_iso(ts: str) -> dict:
    """Split an ISO-8601 timestamp into date / hour / weekday components."""
    if not ts:
        return {'date': None, 'hour': None, 'day_of_week': None}
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return {
            'date':        dt.strftime('%Y-%m-%d'),
            'hour':        dt.hour,
            'day_of_week': dt.strftime('%A'),
        }
    except ValueError:
        return {'date': None, 'hour': None, 'day_of_week': None}


def risk_band(score: int) -> str:
    if score <= 3:   return 'Low (1-3)'
    if score <= 6:   return 'Medium (4-6)'
    if score <= 8:   return 'High (7-8)'
    return 'Critical (9-10)'


def conviction_size(text: str) -> int:
    """Map conviction_adjustment text → numeric position size 0-4 for sorting/charting."""
    t = (text or '').lower()
    if 'full'    in t: return 4
    if 'half'    in t: return 3
    if 'quarter' in t: return 2
    if 'pass'    in t: return 1
    return 0


# ── Export functions ──────────────────────────────────────────────────────────

def export_dim_runs(conn):
    rows = conn.execute("""
        SELECT
            id,
            run_at,
            hours_back,
            feeds_collected,
            narratives_extracted,
            json_path,
            html_path
        FROM runs
        ORDER BY run_at
    """).fetchall()

    out = []
    for r in rows:
        d = parse_iso(r['run_at'])
        out.append({
            'run_id':                r['id'],
            'run_at':                r['run_at'],
            'run_date':              d['date'],
            'run_hour':              d['hour'],
            'run_day_of_week':       d['day_of_week'],
            'hours_back':            r['hours_back'],
            'feeds_collected':       r['feeds_collected'],
            'narratives_extracted':  r['narratives_extracted'],
            'json_path':             r['json_path'],
            'html_path':             r['html_path'],
        })

    fields = [
        'run_id', 'run_at', 'run_date', 'run_hour', 'run_day_of_week',
        'hours_back', 'feeds_collected', 'narratives_extracted',
        'json_path', 'html_path',
    ]
    write_csv('dim_runs.csv', out, fields)


def export_dim_accounts(conn):
    rows = conn.execute("""
        SELECT id, handle, added_at, active, category, notes
        FROM twitter_accounts
        ORDER BY handle
    """).fetchall()

    out = []
    for r in rows:
        d = parse_iso(r['added_at'])
        out.append({
            'account_id':   r['id'],
            'handle':       r['handle'],
            'handle_at':    f"@{r['handle']}",
            'added_at':     r['added_at'],
            'added_date':   d['date'],
            'active':       'Active' if r['active'] else 'Paused',
            'category':     r['category'] or 'Uncategorised',
            'notes':        r['notes'] or '',
        })

    fields = ['account_id', 'handle', 'handle_at', 'added_at', 'added_date',
              'active', 'category', 'notes']
    write_csv('dim_accounts.csv', out, fields)


def export_fact_feeds(conn):
    rows = conn.execute("""
        SELECT
            f.id,
            f.run_id,
            f.source,
            f.author,
            f.content,
            f.published_at,
            f.url,
            f.nitter_instance,
            r.run_at
        FROM feeds f
        JOIN runs r ON r.id = f.run_id
        ORDER BY f.published_at DESC
    """).fetchall()

    out = []
    for r in rows:
        d    = parse_iso(r['published_at'])
        text = (r['content'] or '').replace('<p>', '').replace('</p>', ' ') \
                                   .replace('<br />', ' ').replace('<br>', ' ')
        word_count = len(text.split())
        out.append({
            'feed_id':         r['id'],
            'run_id':          r['run_id'],
            'source':          r['source'],
            'author':          r['author'],
            'content_clean':   text[:500],          # truncated for PBI import
            'word_count':      word_count,
            'published_at':    r['published_at'],
            'published_date':  d['date'],
            'published_hour':  d['hour'],
            'published_dow':   d['day_of_week'],
            'url':             r['url'] or '',
            'nitter_instance': r['nitter_instance'] or '',
        })

    fields = [
        'feed_id', 'run_id', 'source', 'author', 'content_clean', 'word_count',
        'published_at', 'published_date', 'published_hour', 'published_dow',
        'url', 'nitter_instance',
    ]
    write_csv('fact_feeds.csv', out, fields)


def export_fact_narratives(conn):
    rows = conn.execute("""
        SELECT
            n.id,
            n.run_id,
            n.title,
            n.entropy_risk,
            n.hypothesis,
            n.rationale,
            n.catalysts,
            n.bear_case,
            n.disconfirming_signals,
            n.conviction_adjustment,
            n.created_at,
            r.run_at,
            r.hours_back,
            (
                SELECT COUNT(*)
                FROM narrative_feeds nf
                WHERE nf.narrative_id = n.id
            ) AS supporting_feed_count
        FROM narratives n
        JOIN runs r ON r.id = n.run_id
        ORDER BY n.created_at DESC
    """).fetchall()

    out = []
    for r in rows:
        d = parse_iso(r['created_at'])

        # Parse JSON arrays stored as text
        try:
            catalysts = json.loads(r['catalysts'])
            catalysts_str = ' | '.join(catalysts) if isinstance(catalysts, list) else r['catalysts']
            catalyst_count = len(catalysts) if isinstance(catalysts, list) else 0
        except (json.JSONDecodeError, TypeError):
            catalysts_str  = r['catalysts'] or ''
            catalyst_count = 0

        try:
            disconf = json.loads(r['disconfirming_signals'])
            disconf_str = ' | '.join(disconf) if isinstance(disconf, list) else r['disconfirming_signals']
        except (json.JSONDecodeError, TypeError):
            disconf_str = r['disconfirming_signals'] or ''

        out.append({
            'narrative_id':          r['id'],
            'run_id':                r['run_id'],
            'run_at':                r['run_at'],
            'title':                 r['title'],
            'entropy_risk':          r['entropy_risk'],
            'entropy_band':          risk_band(r['entropy_risk']),
            'hypothesis':            r['hypothesis'],
            'rationale':             r['rationale'],
            'catalysts':             catalysts_str,
            'catalyst_count':        catalyst_count,
            'bear_case':             r['bear_case'] or '',
            'disconfirming_signals': disconf_str,
            'conviction_adjustment': r['conviction_adjustment'] or '',
            'conviction_size':       conviction_size(r['conviction_adjustment']),
            'created_at':            r['created_at'],
            'created_date':          d['date'],
            'created_hour':          d['hour'],
            'created_dow':           d['day_of_week'],
            'supporting_feed_count': r['supporting_feed_count'],
        })

    fields = [
        'narrative_id', 'run_id', 'run_at', 'title',
        'entropy_risk', 'entropy_band', 'hypothesis', 'rationale',
        'catalysts', 'catalyst_count',
        'bear_case', 'disconfirming_signals',
        'conviction_adjustment', 'conviction_size',
        'created_at', 'created_date', 'created_hour', 'created_dow',
        'supporting_feed_count',
    ]
    write_csv('fact_narratives.csv', out, fields)


def export_bridge_narrative_feeds(conn):
    rows = conn.execute("""
        SELECT narrative_id, feed_id
        FROM narrative_feeds
    """).fetchall()

    out = [{'narrative_id': r['narrative_id'], 'feed_id': r['feed_id']} for r in rows]
    write_csv('bridge_narrative_feeds.csv', out, ['narrative_id', 'feed_id'])


# ── Audit additions (2026-05) ────────────────────────────────────────────────

def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def export_fact_narrative_tickers(conn):
    """Export ticker-level extractions joined with entry / last close."""
    if not _table_exists(conn, 'narrative_tickers'):
        print("  -- narrative_tickers not present; skipping (run score_narratives.py first)")
        return

    rows = conn.execute("""
        SELECT nt.narrative_id, nt.ticker, nt.side, nt.is_long_equity, nt.extracted_at,
               r.run_at
        FROM narrative_tickers nt
        JOIN narratives n ON n.id = nt.narrative_id
        JOIN runs r       ON r.id = n.run_id
        ORDER BY r.run_at, nt.ticker
    """).fetchall()

    has_prices = _table_exists(conn, 'prices')
    out = []
    for r in rows:
        run_date = (r['run_at'] or '')[:10]
        entry_close = None
        entry_date  = None
        last_close  = None
        if has_prices:
            ec = conn.execute(
                "SELECT price_date, close FROM prices "
                "WHERE ticker=? AND price_date>=? "
                "ORDER BY price_date ASC LIMIT 1",
                (r['ticker'], run_date)
            ).fetchone()
            if ec:
                entry_date  = ec['price_date']
                entry_close = ec['close']
            lc = conn.execute(
                "SELECT close FROM prices WHERE ticker=? "
                "ORDER BY price_date DESC LIMIT 1",
                (r['ticker'],)
            ).fetchone()
            if lc:
                last_close = lc['close']
        out.append({
            'narrative_id':   r['narrative_id'],
            'ticker':         r['ticker'],
            'side':           r['side'],
            'is_long_equity': r['is_long_equity'],
            'extracted_at':   r['extracted_at'],
            'entry_date':     entry_date,
            'entry_close':    entry_close,
            'last_close':     last_close,
        })
    fields = ['narrative_id', 'ticker', 'side', 'is_long_equity',
              'extracted_at', 'entry_date', 'entry_close', 'last_close']
    write_csv('fact_narrative_tickers.csv', out, fields)


def export_fact_narrative_grades(conn):
    if not _table_exists(conn, 'narrative_grades'):
        print("  -- narrative_grades not present; skipping (run score_narratives.py first)")
        return
    rows = conn.execute("""
        SELECT narrative_id, specificity, catalyst_score, risk_score,
               cohesion, total_score, letter_grade, graded_at
        FROM narrative_grades
        ORDER BY graded_at DESC
    """).fetchall()
    out = [dict(r) for r in rows]
    fields = ['narrative_id', 'specificity', 'catalyst_score', 'risk_score',
              'cohesion', 'total_score', 'letter_grade', 'graded_at']
    write_csv('fact_narrative_grades.csv', out, fields)


def export_fact_prices(conn):
    if not _table_exists(conn, 'prices'):
        print("  -- prices not present; skipping (run redhood_pnl.py first)")
        return
    rows = conn.execute("""
        SELECT ticker, price_date, close, fetched_at, source
        FROM prices
        ORDER BY ticker, price_date
    """).fetchall()
    out = [dict(r) for r in rows]
    fields = ['ticker', 'price_date', 'close', 'fetched_at', 'source']
    write_csv('fact_prices.csv', out, fields)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\nRedHood Systems - Power BI Export")
    print(f"Database : {DB_PATH}")
    print(f"Output   : {OUT_DIR}\n")

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = connect()

    export_dim_runs(conn)
    export_dim_accounts(conn)
    export_fact_feeds(conn)
    export_fact_narratives(conn)
    export_bridge_narrative_feeds(conn)

    # Audit additions (2026-05)
    export_fact_narrative_tickers(conn)
    export_fact_narrative_grades(conn)
    export_fact_prices(conn)

    conn.close()
    print(f"\nDone. Import the CSV files from {OUT_DIR} into Power BI Desktop.")
    print("See powerbi/dax_measures.dax and powerbi/power_query.m for formulas.")


if __name__ == '__main__':
    main()
uns r       ON r.id = n.run_id
        ORDER BY r.run_at, nt.ticker
    """).fetchall()

    has_prices = _table_exists(conn, 'prices')
    out = []
    for r in rows:
        run_date = (r['run_at'] or '')[:10]
        entry_close = None
        entry_date  = None
        last_close  = None
        if has_prices:
            ec = conn.execute(
                "SELECT price_date, close FROM prices "
                "WHERE ticker=? AND price_date>=? "
                "ORDER BY price_date ASC LIMIT 1",
                (r['ticker'], run_date)
            ).fetchone()
            if ec:
                entry_date  = ec['price_date']
                entry_close = ec['close']
            lc = conn.execute(
                "SELECT close FROM prices WHERE ticker=? "
                "ORDER BY price_date DESC LIMIT 1",
                (r['ticker'],)
            ).fetchone()
            if lc:
                last_close = lc['close']
        out.append({
            'narrative_id':   r['narrative_id'],
            'ticker':         r['ticker'],
            'side':           r['side'],
            'is_long_equity': r['is_long_equity'],
            'extracted_at':   r['extracted_at'],
            'entry_date':     entry_date,
            'entry_close':    entry_close,
            'last_close':     last_close,
        })
    fields = ['narrative_id', 'ticker', 'side', 'is_long_equity',
              'extracted_at', 'entry_date', 'entry_close', 'last_close']
    write_csv('fact_narrative_tickers.csv', out, fields)


def export_fact_narrative_grades(conn):
    if not _table_exists(conn, 'narrative_grades'):
        print("  -- narrative_grades not present; skipping (run score_narratives.py first)")
        return
    rows = conn.execute(
        "SELECT narrative_id, specificity, catalyst_score, risk_score, "
        "cohesion, total_score, letter_grade, graded_at "
        "FROM narrative_grades ORDER BY graded_at DESC"
    ).fetchall()
    out = [dict(r) for r in rows]
    fields = ['narrative_id', 'specificity', 'catalyst_score', 'risk_score',
              'cohesion', 'total_score', 'letter_grade', 'graded_at']
    write_csv('fact_narrative_grades.csv', out, fields)


def export_fact_prices(conn):
    if not _table_exists(conn, 'prices'):
        print("  -- prices not present; skipping (run redhood_pnl.py first)")
        return
    rows = conn.execute(
        "SELECT ticker, price_date, close, fetched_at, source "
        "FROM prices ORDER BY ticker, price_date"
    ).fetchall()
    out = [dict(r) for r in rows]
    fields = ['ticker', 'price_date', 'close', 'fetched_at', 'source']
    write_csv('fact_prices.csv', out, fields)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\nRedHood Systems - Power BI Export")
    print(f"Database : {DB_PATH}")
    print(f"Output   : {OUT_DIR}\n")

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = connect()

    export_dim_runs(conn)
    export_dim_accounts(conn)
    export_fact_feeds(conn)
    export_fact_narratives(conn)
    export_bridge_narrative_feeds(conn)

    # Audit additions (2026-05)
    export_fact_narrative_tickers(conn)
    export_fact_narrative_grades(conn)
    export_fact_prices(conn)

    conn.close()
    print(f"\nDone. Import the CSV files from {OUT_DIR} into Power BI Desktop.")
    print("See powerbi/dax_measures.dax and powerbi/power_query.m for formulas.")


if __name__ == '__main__':
    main()
__main__':
    main()
