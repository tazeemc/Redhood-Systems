"""
RedHood Insights — Long-only P&L Tracker (v2: the loop is closed)
=================================================================
Reads grader-vetted long tickers (narrative_tickers.is_long_equity = 1) from
redhood.db, keeps a daily-close cache in the `prices` table, and computes:

  * the $2,500-per-ticker ledger (compute_pnl / print_leaderboard), as before;
  * realised FORWARD returns per (narrative, ticker) pair over 5 / 20 / 60
    trading days and to date, against SPY over identical windows, persisted
    to `narrative_returns` (compute_forward_returns) — this is what the
    timeline and the extraction prompt read back;
  * current portfolio HEAT — the fraction of equity that would be lost if the
    stop on every position opened in the last `hold_days` sessions were hit
    (current_heat) — which the regime detector consumes.

Prices can come from yfinance (optional dependency) OR from a CSV
(`--import-csv`, columns: ticker, price_date, close[, open, high, low,
adj_close, volume]) so the loop closes even where yfinance is unavailable.

Entry date = first trading-day close on/after the run_at date of the
narrative the ticker was extracted from — or the NEXT session's close when
the run finished after the US close (no look-ahead).

Usage:
    python redhood_pnl.py                      # update prices (yfinance), recompute P&L
    python redhood_pnl.py --refresh            # force refetch (ignore cache)
    python redhood_pnl.py --import-csv data/prices.csv   # load closes from a CSV
    python redhood_pnl.py --forward            # (re)compute narrative_returns, print novelty summary
    python redhood_pnl.py --heat               # print current heat for a $100k book
    python redhood_pnl.py --since 2026-03-01
    python redhood_pnl.py --size 5000          # alternative sizing
    python redhood_pnl.py --report             # print summary leaderboard
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import os
from bisect import bisect_left
from datetime import datetime, timedelta, date, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')
DEFAULT_SIZE_USD = 2500.0
BENCHMARK = 'SPY'
HORIZONS = (5, 20, 60)


def _need_yfinance(quiet: bool = False) -> bool:
    try:
        import yfinance  # noqa: F401
        return True
    except ImportError:
        if not quiet:
            print("ERROR: yfinance is not installed.", file=sys.stderr)
            print("  Install with: pip install yfinance --break-system-packages", file=sys.stderr)
            print("  Or load closes from a CSV: python redhood_pnl.py --import-csv prices.csv", file=sys.stderr)
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
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            adj_close   REAL,
            volume      INTEGER,
            fetched_at  TEXT,
            source      TEXT DEFAULT 'yfinance',
            PRIMARY KEY (ticker, price_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS narrative_returns (
            narrative_id TEXT NOT NULL, ticker TEXT NOT NULL,
            entry_date TEXT, entry_close REAL,
            h5 REAL, h20 REAL, h60 REAL, todate REAL,
            spy_h5 REAL, spy_h20 REAL, spy_h60 REAL, spy_todate REAL,
            last_date TEXT, computed_at TEXT NOT NULL,
            PRIMARY KEY (narrative_id, ticker)
        )
    """)
    conn.commit()


def _cache_has(conn: sqlite3.Connection, ticker: str, on_or_after: str) -> bool:
    row = conn.execute(
        "SELECT MAX(price_date) FROM prices WHERE ticker = ? AND price_date >= ?",
        (ticker, on_or_after),
    ).fetchone()
    return row[0] is not None


def fetch_prices(ticker: str, start: str, end: str | None = None) -> list:
    """Return list of (date_iso, close) tuples for a ticker via yfinance."""
    import yfinance as yf
    end = end or (date.today() + timedelta(days=1)).isoformat()
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    except Exception as e:
        print(f"  ! {ticker}: download failed: {e}", file=sys.stderr)
        return []
    if df.empty:
        return []
    out = []
    # Handle yfinance's MultiIndex columns when single-ticker
    close_col = df['Close'] if 'Close' in df.columns else df.iloc[:, 3]
    for ts, val in close_col.dropna().items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        out.append((ts.strftime('%Y-%m-%d'), v))
    return out


def upsert_closes(conn: sqlite3.Connection, ticker: str, rows: list, source: str = 'yfinance') -> int:
    """Insert/replace (date, close) rows for a ticker, preserving OHLCV columns if present."""
    now = _now_iso()
    conn.executemany(
        "INSERT INTO prices (ticker, price_date, close, fetched_at, source) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(ticker, price_date) DO UPDATE SET close = excluded.close, "
        "fetched_at = excluded.fetched_at, source = excluded.source",
        [(ticker, d, c, now, source) for d, c in rows]
    )
    conn.commit()
    return len(rows)


def update_cache(conn: sqlite3.Connection, ticker: str, since: str,
                 force: bool = False) -> int:
    """Fetch and upsert price rows for `ticker` since the given date (yfinance)."""
    if not force and _cache_has(conn, ticker, since):
        # Cache extends from `since`; only top up the tail (last 7 days)
        recent = (date.today() - timedelta(days=7)).isoformat()
        rows = fetch_prices(ticker, recent)
    else:
        rows = fetch_prices(ticker, since)
    if not rows:
        return 0
    return upsert_closes(conn, ticker, rows, 'yfinance')


def import_prices_csv(conn: sqlite3.Connection, path: str, source: str | None = None) -> dict:
    """Load daily closes from a CSV with columns ticker, price_date, close[, open, high, low, adj_close, volume].

    Dates may be YYYY-MM-DD or ISO timestamps (the date part is used). Returns
    {'rows': n, 'tickers': k}.
    """
    _ensure_prices_table(conn)
    source = source or f"csv:{os.path.basename(path)}"
    now = _now_iso()
    n = 0
    tickers = set()
    with open(path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        need = ('ticker', 'price_date', 'close')
        if not all(c in cols for c in need):
            alt = {'date': 'price_date', 'symbol': 'ticker'}
            for a, b in alt.items():
                if a in cols and b not in cols:
                    cols[b] = cols[a]
            if not all(c in cols for c in need):
                raise ValueError(f"CSV needs columns {need}; found {reader.fieldnames}")

        def _f(row, name):
            c = cols.get(name)
            if c is None:
                return None
            v = row.get(c, '')
            try:
                return float(v) if v not in ('', None) else None
            except ValueError:
                return None

        batch = []
        for row in reader:
            t = row[cols['ticker']].strip().upper()
            d = row[cols['price_date']].strip()[:10]
            close = _f(row, 'close')
            if not t or not d or close is None:
                continue
            tickers.add(t)
            vol = _f(row, 'volume')
            batch.append((t, d, _f(row, 'open'), _f(row, 'high'), _f(row, 'low'), close,
                          _f(row, 'adj_close'), int(vol) if vol is not None else None, now, source))
            n += 1
    conn.executemany(
        "INSERT INTO prices (ticker, price_date, open, high, low, close, adj_close, volume, fetched_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ticker, price_date) DO UPDATE SET open = COALESCE(excluded.open, prices.open), "
        "high = COALESCE(excluded.high, prices.high), low = COALESCE(excluded.low, prices.low), "
        "close = excluded.close, adj_close = COALESCE(excluded.adj_close, prices.adj_close), "
        "volume = COALESCE(excluded.volume, prices.volume), fetched_at = excluded.fetched_at, "
        "source = excluded.source",
        batch,
    )
    conn.commit()
    return {'rows': n, 'tickers': len(tickers)}


# ----------------------------------------------------------------------------
# Series helpers
# ----------------------------------------------------------------------------

def _series(conn: sqlite3.Connection, ticker: str) -> tuple[list, list]:
    """(dates, closes) sorted ascending for a ticker (empty lists if none)."""
    rows = conn.execute(
        "SELECT price_date, close FROM prices WHERE ticker = ? AND close IS NOT NULL ORDER BY price_date",
        (ticker,)).fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def forward_return(dates: list, closes: list, entry_on_or_after: str, horizon: int | None):
    """(entry_date, entry_close, exit_date, simple_return) or None.

    horizon=None means "to the last cached close".
    """
    if not dates:
        return None
    i = bisect_left(dates, entry_on_or_after[:10])
    if i >= len(dates):
        return None
    j = len(dates) - 1 if horizon is None else i + horizon
    if j >= len(dates):
        return None
    if closes[i] <= 0:
        return None
    return dates[i], closes[i], dates[j], closes[j] / closes[i] - 1.0


def _entry_close(conn: sqlite3.Connection, ticker: str, on_or_after: str):
    row = conn.execute(
        "SELECT price_date, close FROM prices "
        "WHERE ticker = ? AND price_date >= ? AND close IS NOT NULL "
        "ORDER BY price_date ASC LIMIT 1",
        (ticker, on_or_after),
    ).fetchone()
    return row  # (date, close) or None


def _last_close(conn: sqlite3.Connection, ticker: str):
    row = conn.execute(
        "SELECT price_date, close FROM prices WHERE ticker = ? AND close IS NOT NULL "
        "ORDER BY price_date DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return row


AFTER_CLOSE_UTC_HOUR = 20   # 16:00 ET in summer; runs at/after this hour enter at the NEXT session's close


def entry_date_for_run(run_at: str) -> str:
    """First date whose close a narrative produced at `run_at` (UTC) could actually have traded.

    A run that finishes after the US close cannot be filled at that day's
    close; its entry is the next calendar day (the next trading day's close
    is then found by bisect).  Runs before the close enter at that day's close.
    """
    if not run_at:
        return ''
    try:
        ts = datetime.fromisoformat(run_at[:19])
    except ValueError:
        return run_at[:10]
    if ts.hour >= AFTER_CLOSE_UTC_HOUR:
        return (ts.date() + timedelta(days=1)).isoformat()
    return ts.date().isoformat()


def long_pairs(conn: sqlite3.Connection, since: str | None = None) -> list:
    """Grader-vetted long-side (narrative, ticker) pairs with their run date."""
    sql = """
        SELECT nt.narrative_id, nt.ticker, n.created_at, r.run_at
        FROM narrative_tickers nt
        JOIN narratives n ON n.id = nt.narrative_id
        JOIN runs r ON r.id = n.run_id
        WHERE nt.is_long_equity = 1
    """
    params: tuple = ()
    if since:
        sql += " AND r.run_at >= ?"
        params = (since,)
    sql += " ORDER BY r.run_at, nt.ticker"
    return conn.execute(sql, params).fetchall()


# ----------------------------------------------------------------------------
# P&L computation (ledger)
# ----------------------------------------------------------------------------

def compute_pnl(db_path: str = DB_PATH,
                size_usd: float = DEFAULT_SIZE_USD,
                since: str = '2026-01-01',
                force_refresh: bool = False,
                verbose: bool = True,
                fetch: bool = True) -> list:
    """Compute long-only P&L for every (narrative, ticker) row.

    Returns list of dicts with: narrative_id, ticker, run_at, entry_date,
    entry_close, current_date, current_close, shares, position, pnl, return_pct.
    With fetch=False the cached prices are used as-is (no yfinance needed).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_prices_table(conn)

    tickers = [r['ticker'] for r in conn.execute(
        "SELECT DISTINCT ticker FROM narrative_tickers WHERE is_long_equity = 1 ORDER BY ticker").fetchall()]
    if fetch:
        if not _need_yfinance():
            print("  (continuing with cached prices only)", file=sys.stderr)
        else:
            if verbose:
                print(f"Updating price cache for {len(tickers)} ticker(s) + {BENCHMARK} since {since}...")
            for t in tickers + [BENCHMARK]:
                n = update_cache(conn, t, since, force=force_refresh)
                if verbose:
                    print(f"  {t:<6}  +{n:>4} rows")

    out = []
    for r in long_pairs(conn):
        entry_after = entry_date_for_run(r['run_at'] or r['created_at'] or '')
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
# Forward returns (narrative_returns) — closes the loop
# ----------------------------------------------------------------------------

def compute_forward_returns(conn: sqlite3.Connection, since: str | None = None,
                            verbose: bool = False) -> dict:
    """Realised forward returns of each long-side pair vs SPY, persisted to narrative_returns.

    Returns {'pairs': n_considered, 'written': n_written, 'missing_prices': n}.
    """
    _ensure_prices_table(conn)
    spy_dates, spy_closes = _series(conn, BENCHMARK)
    cache: dict[str, tuple[list, list]] = {}
    now = _now_iso()
    written = missing = 0
    pairs = long_pairs(conn, since)
    for r in pairs:
        t = r['ticker'] if isinstance(r, sqlite3.Row) else r[1]
        nid = r['narrative_id'] if isinstance(r, sqlite3.Row) else r[0]
        run_at = (r['run_at'] if isinstance(r, sqlite3.Row) else r[3]) or ''
        created = (r['created_at'] if isinstance(r, sqlite3.Row) else r[2]) or ''
        entry_after = entry_date_for_run(run_at or created)
        if t not in cache:
            cache[t] = _series(conn, t)
        dates, closes = cache[t]
        if not dates:
            missing += 1
            continue
        vals = {}
        base = forward_return(dates, closes, entry_after, None)
        if base is None:
            missing += 1
            continue
        entry_date, entry_close, last_date, todate = base
        vals['todate'] = todate
        for h in HORIZONS:
            fr = forward_return(dates, closes, entry_after, h)
            vals[f'h{h}'] = fr[3] if fr else None
        svals = {}
        sb = forward_return(spy_dates, spy_closes, entry_after, None) if spy_dates else None
        svals['todate'] = sb[3] if sb else None
        for h in HORIZONS:
            fr = forward_return(spy_dates, spy_closes, entry_after, h) if spy_dates else None
            svals[f'h{h}'] = fr[3] if fr else None
        conn.execute(
            "INSERT INTO narrative_returns (narrative_id, ticker, entry_date, entry_close, h5, h20, h60, todate, "
            "spy_h5, spy_h20, spy_h60, spy_todate, last_date, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(narrative_id, ticker) DO UPDATE SET entry_date = excluded.entry_date, entry_close = excluded.entry_close, "
            "h5 = excluded.h5, h20 = excluded.h20, h60 = excluded.h60, todate = excluded.todate, spy_h5 = excluded.spy_h5, "
            "spy_h20 = excluded.spy_h20, spy_h60 = excluded.spy_h60, spy_todate = excluded.spy_todate, "
            "last_date = excluded.last_date, computed_at = excluded.computed_at",
            (nid, t, entry_date, entry_close, vals['h5'], vals['h20'], vals['h60'], vals['todate'],
             svals['h5'], svals['h20'], svals['h60'], svals['todate'], last_date, now))
        written += 1
    conn.commit()
    stats = {'pairs': len(pairs), 'written': written, 'missing_prices': missing}
    if verbose:
        print(f"Forward returns: {written} pairs written, {missing} without prices (of {len(pairs)})")
    return stats


def novelty_summary(conn: sqlite3.Connection) -> dict:
    """Mean excess return vs SPY for first vs repeat mentions of a ticker (the paper's Table 2 rows)."""
    rows = conn.execute("""
        SELECT r.ticker, n.run_id, run.run_at, r.h5, r.h20, r.h60, r.todate,
               r.spy_h5, r.spy_h20, r.spy_h60, r.spy_todate
        FROM narrative_returns r
        JOIN narratives n ON n.id = r.narrative_id
        JOIN runs run ON run.id = n.run_id
        ORDER BY run.run_at, r.ticker
    """).fetchall()
    # A pair is a FIRST mention when its ticker had not appeared as a long on any
    # strictly earlier run DATE (same-day repeats count as first; paper v3, S6.3).
    first_date: dict[str, str] = {}
    for row in rows:
        d = (row[2] or '')[:10]
        if row[0] not in first_date or d < first_date[row[0]]:
            first_date[row[0]] = d
    groups = {'first': [], 'repeat': []}
    for row in rows:
        groups['first' if (row[2] or '')[:10] == first_date[row[0]] else 'repeat'].append(row)
    out = {}
    for g, rs in groups.items():
        d = {'n': len(rs)}
        for i, h in enumerate(('h5', 'h20', 'h60', 'todate')):
            ex = [r[3 + i] - r[7 + i] for r in rs if r[3 + i] is not None and r[7 + i] is not None]
            d[h] = (sum(ex) / len(ex)) if ex else None
            d[h + '_n'] = len(ex)
        out[g] = d
    return out


# ----------------------------------------------------------------------------
# Portfolio heat (Seykota) — computed from the open book
# ----------------------------------------------------------------------------

def current_heat(conn: sqlite3.Connection, equity: float = 100_000.0,
                 size_usd: float = DEFAULT_SIZE_USD, stop_frac: float = 0.08,
                 hold_days: int = 20, as_of: str | None = None) -> dict:
    """Heat = sum over open positions of (size * stop) / equity.

    A position is "open" if its narrative's run date lies within the last
    `hold_days` trading days (approximated with SPY's cached calendar when
    present, else 1.4 x hold_days calendar days).  Returns a dict with heat,
    open_positions, notional and the as_of date used.
    """
    as_of = (as_of or date.today().isoformat())[:10]
    spy_dates, _ = _series(conn, BENCHMARK)
    if spy_dates:
        i = bisect_left(spy_dates, as_of)
        i = min(i, len(spy_dates) - 1)
        j = max(0, i - hold_days)
        window_start = spy_dates[j]
    else:
        window_start = (date.fromisoformat(as_of) - timedelta(days=int(hold_days * 1.4))).isoformat()
    n_open = conn.execute(
        "SELECT COUNT(*) FROM narrative_tickers nt JOIN narratives n ON n.id = nt.narrative_id "
        "JOIN runs r ON r.id = n.run_id WHERE nt.is_long_equity = 1 AND r.run_at >= ? AND r.run_at <= ?",
        (window_start, as_of + 'T23:59:59')).fetchone()[0]
    heat = n_open * size_usd * stop_frac / equity if equity else 0.0
    return {'heat': heat, 'open_positions': int(n_open), 'notional': n_open * size_usd / equity if equity else 0.0,
            'window_start': window_start, 'as_of': as_of, 'equity': equity, 'stop_frac': stop_frac,
            'hold_days': hold_days}


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


def print_novelty(summary: dict) -> None:
    print("\nExcess return vs SPY by novelty of the ticker mention (mean, %)")
    print(f"{'group':<10}{'n':>5}{'5d':>9}{'20d':>9}{'60d':>9}{'to date':>10}")
    for g in ('first', 'repeat'):
        d = summary.get(g, {})
        cells = []
        for h in ('h5', 'h20', 'h60', 'todate'):
            v = d.get(h)
            cells.append(f"{100*v:+8.1f}" if v is not None else f"{'--':>8}")
        print(f"{g:<10}{d.get('n', 0):>5}" + ''.join(f"{c:>9}" for c in cells))


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
    p.add_argument("--no-fetch", action="store_true",
                   help="Do not call yfinance; use cached prices only")
    p.add_argument("--import-csv", metavar="PATH",
                   help="Load daily closes from a CSV (ticker, price_date, close[, ...]) into the cache")
    p.add_argument("--forward", action="store_true",
                   help="(Re)compute realised forward returns into narrative_returns and print the novelty summary")
    p.add_argument("--heat", action="store_true",
                   help="Print current portfolio heat for --equity")
    p.add_argument("--equity", type=float, default=float(os.getenv('REDHOOD_EQUITY', '100000')))
    p.add_argument("--report", action="store_true",
                   help="Print leaderboard summary after computing")
    args = p.parse_args()

    if args.import_csv:
        conn = sqlite3.connect(args.db)
        stats = import_prices_csv(conn, args.import_csv)
        conn.close()
        print(f"Imported {stats['rows']} close rows for {stats['tickers']} tickers from {args.import_csv}")

    rows = compute_pnl(db_path=args.db, size_usd=args.size, since=args.since,
                       force_refresh=args.refresh, fetch=not (args.no_fetch or args.import_csv))
    if args.report or rows:
        print_leaderboard(rows)

    if args.forward or args.heat:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        if args.forward:
            stats = compute_forward_returns(conn, verbose=True)
            print_novelty(novelty_summary(conn))
        if args.heat:
            h = current_heat(conn, equity=args.equity)
            print(f"\nHeat: {100*h['heat']:.2f}% of ${h['equity']:,.0f} at risk "
                  f"({h['open_positions']} open positions since {h['window_start']}, "
                  f"notional {100*h['notional']:.0f}% of equity)")
        conn.close()


if __name__ == "__main__":
    main()
