"""
RedHood Insights — Long-only P&L Tracker
=========================================
Reads narrative_tickers from redhood.db, fetches historical close prices via
yfinance, and computes P&L on a standard $2,500 per-ticker sizing convention.

Entry date = the run_at date of the narrative the ticker was extracted from.
If that day is a weekend or holiday, the next trading-day close is used.
Current price = last close in the cache (or, if --refresh, just-fetched).

Price cache: yfinance >= 0.2.51 returns a two-level column index
(Price, Ticker) even for a single symbol, so df['Close'] is a one-column
DataFrame rather than a Series. closes_from_frame() handles both shapes.
A top-up that writes no rows prints a warning naming the ticker and the
reason (download error, unknown / delisted symbol, empty window, or an
unrecognised frame) instead of silently returning 0.

Optional dependency: yfinance. If not installed, the script prints
installation instructions and exits cleanly — the rest of the codebase
keeps working.

Usage:
    python redhood_pnl.py                # update prices, recompute P&L
    python redhood_pnl.py --refresh      # force refetch (ignore cache)
    python redhood_pnl.py --since 2026-03-01
    python redhood_pnl.py --size 5000    # alternative sizing
    python redhood_pnl.py --report       # print summary leaderboard
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import os
from datetime import datetime, timedelta, date, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')
DEFAULT_SIZE_USD = 2500.0
BENCHMARK = 'SPY'

# When the cache already reaches `since`, re-request from this many calendar
# days before the last cached close. The overlap re-fetches the last session
# or two, so a partial bar written by a mid-session run is corrected on the
# next run, and no sessions are skipped when the pipeline has not run for a
# while (the old code always asked for a fixed 7-day tail).
TOPUP_OVERLAP_DAYS = 3


def _need_yfinance(quiet: bool = False) -> bool:
    try:
        import yfinance  # noqa: F401
        return True
    except ImportError:
        if not quiet:
            print("ERROR: yfinance is not installed.", file=sys.stderr)
            print("  Install with: pip install yfinance --break-system-packages", file=sys.stderr)
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ----------------------------------------------------------------------------
# Price cache
# ----------------------------------------------------------------------------

def _ensure_prices_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            ticker      TEXT NOT NULL,
            price_date  TEXT NOT NULL,
            close       REAL NOT NULL,
            fetched_at  TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT 'yfinance',
            PRIMARY KEY (ticker, price_date)
        )
    """)
    conn.commit()


def last_cached_date(conn: sqlite3.Connection, ticker: str) -> str | None:
    """Most recent price_date cached for `ticker`, or None when nothing is cached."""
    row = conn.execute(
        "SELECT MAX(price_date) FROM prices WHERE ticker = ?", (ticker,)
    ).fetchone()
    return row[0] if row else None


def closes_from_frame(df, ticker: str) -> list:
    """Return [(YYYY-MM-DD, close)] from a yfinance download frame.

    yfinance >= 0.2.51 returns a two-level column index (Price, Ticker) even
    for a single ticker, so df['Close'] is a one-column DataFrame, not a
    Series: iterating it yields (column_name, Series) pairs and float(Series)
    raises TypeError. Older versions, and multi_level_index=False, return flat
    columns. Both shapes are handled here. A tz-aware index keeps its
    wall-clock date (ts.date()), so a New York session stays on its own day.
    """
    if df is None or len(df) == 0:
        return []
    cols = df.columns
    close = None
    if getattr(cols, 'nlevels', 1) > 1:
        if ('Close', ticker) in cols:
            close = df[('Close', ticker)]
        elif 'Close' in cols.get_level_values(0):
            close = df['Close'].iloc[:, 0]
    elif 'Close' in cols:
        close = df['Close']
    if close is None:
        return []
    out = []
    for ts, val in close.dropna().items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        d = ts.date().isoformat() if hasattr(ts, 'date') else str(ts)[:10]
        out.append((d, v))
    return out


def _yf_error(ticker: str) -> str | None:
    """yfinance records per-symbol failures ("possibly delisted; no timezone
    found") in yfinance.shared._ERRORS; surface that text when present."""
    try:
        from yfinance import shared
        err = shared._ERRORS.get(ticker)
    except Exception:
        return None
    return str(err) if err else None


def download_closes(ticker: str, start: str, end: str | None = None) -> tuple:
    """Download daily closes for `ticker` via yfinance.

    Returns (rows, reason): rows is [(date_iso, close)]; reason is None on
    success, otherwise a short string saying why nothing came back.
    """
    import yfinance as yf
    end = end or (date.today() + timedelta(days=1)).isoformat()
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    except Exception as e:
        return [], f"download failed: {e}"
    if df is None or len(df) == 0:
        return [], _yf_error(ticker) or f"no bars returned for {start}..{end}"
    rows = closes_from_frame(df, ticker)
    if not rows:
        return [], f"no Close column in download (columns={list(df.columns)[:6]})"
    return rows, None


def fetch_prices(ticker: str, start: str, end: str | None = None) -> list:
    """Return list of (date_iso, close) tuples for a ticker via yfinance.

    Empty on failure, with the reason printed to stderr.
    """
    rows, reason = download_closes(ticker, start, end)
    if reason:
        print(f"  ! {ticker}: {reason}", file=sys.stderr)
    return rows


def upsert_closes(conn: sqlite3.Connection, ticker: str, rows: list,
                  source: str = 'yfinance') -> int:
    """Insert/replace (date, close) rows for a ticker.

    ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE, so OHLCV columns
    that a CSV import added to `prices` survive a close-only refresh.
    """
    now = _now_iso()
    conn.executemany(
        "INSERT INTO prices (ticker, price_date, close, fetched_at, source) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(ticker, price_date) DO UPDATE SET close = excluded.close, "
        "fetched_at = excluded.fetched_at, source = excluded.source",
        [(ticker, d, c, now, source) for d, c in rows]
    )
    conn.commit()
    return len(rows)


def _warn(msg: str) -> None:
    """Print a loud warning to stdout (which the run log captures); fall back
    to plain text on consoles that cannot encode the emoji prefix."""
    try:
        print(f"   ⚠️  {msg}")
    except UnicodeEncodeError:
        print(f"   WARNING: {msg}")


def update_cache(conn: sqlite3.Connection, ticker: str, since: str,
                 force: bool = False) -> int:
    """Fetch and upsert daily closes for `ticker`; returns the rows written.

    When the cache already reaches `since`, only the tail is requested: from
    TOPUP_OVERLAP_DAYS before the last cached close through today. A top-up
    that writes nothing prints a warning naming the ticker and the reason,
    so a silent "0 rows" can no longer hide a parsing or symbol problem.
    """
    cached_max = None if force else last_cached_date(conn, ticker)
    if cached_max is None or cached_max < since:
        start = since
    else:
        start = (date.fromisoformat(cached_max[:10])
                 - timedelta(days=TOPUP_OVERLAP_DAYS)).isoformat()
    rows, reason = download_closes(ticker, start)
    if not rows:
        _warn(f"{ticker}: price top-up wrote 0 rows (requested from {start}) - {reason}")
        return 0
    return upsert_closes(conn, ticker, rows, 'yfinance')


# ----------------------------------------------------------------------------
# P&L computation
# ----------------------------------------------------------------------------

def _entry_close(conn: sqlite3.Connection, ticker: str, on_or_after: str):
    row = conn.execute(
        "SELECT price_date, close FROM prices "
        "WHERE ticker = ? AND price_date >= ? "
        "ORDER BY price_date ASC LIMIT 1",
        (ticker, on_or_after),
    ).fetchone()
    return row  # (date, close) or None


def _last_close(conn: sqlite3.Connection, ticker: str):
    row = conn.execute(
        "SELECT price_date, close FROM prices WHERE ticker = ? "
        "ORDER BY price_date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return row


def compute_pnl(db_path: str = DB_PATH,
                size_usd: float = DEFAULT_SIZE_USD,
                since: str = '2026-01-01',
                force_refresh: bool = False,
                verbose: bool = True) -> list:
    """Compute long-only P&L for every (narrative, ticker) row.

    Returns list of dicts with: narrative_id, ticker, run_at, entry_date,
    entry_close, current_date, current_close, shares, position, pnl, return_pct.
    """
    if not _need_yfinance():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_prices_table(conn)

    tickers = conn.execute(
        "SELECT DISTINCT ticker FROM narrative_tickers ORDER BY ticker"
    ).fetchall()
    if verbose:
        print(f"Updating price cache for {len(tickers)} ticker(s) + {BENCHMARK} since {since}...")
    for t in [r['ticker'] for r in tickers] + [BENCHMARK]:
        n = update_cache(conn, t, since, force=force_refresh)
        if verbose:
            print(f"  {t:<6}  +{n:>4} rows")

    rows = conn.execute("""
        SELECT nt.narrative_id, nt.ticker, n.created_at, r.run_at
        FROM narrative_tickers nt
        JOIN narratives n ON n.id = nt.narrative_id
        JOIN runs r ON r.id = n.run_id
        WHERE nt.is_long_equity = 1
        ORDER BY r.run_at, nt.ticker
    """).fetchall()

    out = []
    for r in rows:
        entry_after = (r['run_at'] or r['created_at'] or '')[:10]
        entry = _entry_close(conn, r['ticker'], entry_after)
        latest = _last_close(conn, r['ticker'])
        if not entry or not latest:
            continue
        ed, ec = entry
        cd, cc = latest
        shares = size_usd / ec if ec else 0.0
        position = size_usd
        current_value = shares * cc
        pnl = current_value - position
        ret = pnl / position if position else 0.0
        out.append({
            'narrative_id': r['narrative_id'],
            'ticker': r['ticker'],
            'run_at': r['run_at'],
            'entry_date': ed,
            'entry_close': ec,
            'current_date': cd,
            'current_close': cc,
            'shares': shares,
            'position': position,
            'pnl': pnl,
            'return_pct': ret,
        })
    conn.close()
    return out


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def print_leaderboard(rows: list) -> None:
    if not rows:
        print("(no P&L rows — run scoring + price refresh first)")
        return
    # Aggregate by ticker
    agg = {}
    for r in rows:
        a = agg.setdefault(r['ticker'], {'mentions': 0, 'pnl': 0.0, 'positions': 0.0})
        a['mentions'] += 1
        a['pnl']      += r['pnl']
        a['positions'] += r['position']
    print(f"\n{'Ticker':<8}{'Mentions':>10}{'Total $':>14}{'P&L $':>14}{'Avg Ret %':>12}")
    print('-' * 58)
    for t in sorted(agg, key=lambda k: -agg[k]['pnl']):
        a = agg[t]
        avg = a['pnl'] / a['positions'] if a['positions'] else 0.0
        print(f"{t:<8}{a['mentions']:>10}{a['positions']:>14,.0f}{a['pnl']:>14,.2f}{avg*100:>11.1f}%")
    total_pnl = sum(a['pnl'] for a in agg.values())
    total_pos = sum(a['positions'] for a in agg.values())
    print('-' * 58)
    print(f"{'TOTAL':<8}{'':>10}{total_pos:>14,.0f}{total_pnl:>14,.2f}"
          f"{(total_pnl/total_pos if total_pos else 0)*100:>11.1f}%")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="RedHood long-only P&L tracker")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--size", type=float, default=DEFAULT_SIZE_USD,
                   help=f"Standard sizing per ticker (default ${DEFAULT_SIZE_USD:,.0f})")
    p.add_argument("--since", default="2026-01-01",
                   help="Earliest entry date to fetch prices from")
    p.add_argument("--refresh", action="store_true",
                   help="Force refetch of all prices (ignore cache)")
    p.add_argument("--report", action="store_true",
                   help="Print leaderboard summary after computing")
    args = p.parse_args()

    rows = compute_pnl(db_path=args.db, size_usd=args.size,
                       since=args.since, force_refresh=args.refresh)
    if args.report or rows:
        print_leaderboard(rows)


if __name__ == "__main__":
    main()
