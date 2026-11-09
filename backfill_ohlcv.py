"""
RedHood Systems - OHLCV Backfill
=================================
`redhood_pnl.py` caches close-only prices, which is enough for forward-return
maths but not enough to draw a candlestick. This script fills the
open / high / low / adj_close / volume columns that already exist on the
`prices` table so the terminal (docs/terminal.html) can render real candles and
volume bars for every symbol, not just SPY.

Symbols are taken from the union of:
  * every ticker already present in `prices`
  * every active row in `watchlist`
  * every symbol referenced by `narrative_tickers`

Usage:
    python backfill_ohlcv.py                      # 2y of daily bars, all symbols
    python backfill_ohlcv.py --period 5y
    python backfill_ohlcv.py --symbols SPY NVDA   # just these
    python backfill_ohlcv.py --missing-only       # skip symbols that already have OHLC
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')
CHUNK = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def target_symbols(conn: sqlite3.Connection, missing_only: bool = False) -> list[str]:
    """Union of priced / watchlisted / narrative-referenced symbols."""
    rows = conn.execute("""
        SELECT ticker FROM prices
        UNION SELECT symbol FROM watchlist WHERE active = 1
        UNION SELECT ticker FROM narrative_tickers
    """).fetchall()
    syms = sorted({(r[0] or '').strip() for r in rows if (r[0] or '').strip()})

    if missing_only:
        have = {r[0] for r in conn.execute(
            "SELECT ticker FROM prices WHERE open IS NOT NULL GROUP BY ticker HAVING COUNT(*) > 20")}
        syms = [s for s in syms if s not in have]
    return syms


def _clean(v):
    """NaN / inf -> None, numpy scalars -> python floats."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _frame_for(df, symbol: str, multi: bool):
    """Pull the single-symbol sub-frame out of a yfinance download result.

    yfinance returns a two-level column index for multi-symbol downloads, and
    the level order has changed between releases, so probe both.
    """
    if not multi:
        return df
    lvl0 = set(df.columns.get_level_values(0))
    if symbol in lvl0:
        return df[symbol]
    lvl1 = set(df.columns.get_level_values(1))
    if symbol in lvl1:
        return df.xs(symbol, axis=1, level=1)
    return None


def rows_from_frame(sub) -> list[tuple]:
    """-> [(date, open, high, low, close, adj_close, volume)] skipping empty bars."""
    out = []
    cols = {str(c).lower(): c for c in sub.columns}
    def field(row, name):
        c = cols.get(name)
        return _clean(row[c]) if c is not None else None

    for idx, row in sub.iterrows():
        def g(name, _row=row):
            return field(_row, name)

        close = g('close')
        if close is None:
            continue
        date_iso = (idx.date().isoformat() if hasattr(idx, 'date') else str(idx)[:10])
        vol = g('volume')
        out.append((date_iso, g('open'), g('high'), g('low'), close,
                    g('adj close') or g('adj_close'), int(vol) if vol else None))
    return out


def upsert_ohlcv(conn: sqlite3.Connection, ticker: str, rows: list[tuple]) -> int:
    """Insert or update full bars. Existing close-only rows are upgraded in place."""
    now = _now_iso()
    conn.executemany("""
        INSERT INTO prices (ticker, price_date, close, fetched_at, source,
                            open, high, low, adj_close, volume)
        VALUES (?, ?, ?, ?, 'yfinance', ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, price_date) DO UPDATE SET
            close      = excluded.close,
            open       = COALESCE(excluded.open,      prices.open),
            high       = COALESCE(excluded.high,      prices.high),
            low        = COALESCE(excluded.low,       prices.low),
            adj_close  = COALESCE(excluded.adj_close, prices.adj_close),
            volume     = COALESCE(excluded.volume,    prices.volume),
            fetched_at = excluded.fetched_at,
            source     = excluded.source
    """, [(ticker, d, c, now, o, h, lo, ac, v) for (d, o, h, lo, c, ac, v) in rows])
    conn.commit()
    return len(rows)


def backfill(conn: sqlite3.Connection, symbols: list[str], period: str = '2y',
             verbose: bool = True) -> dict:
    import yfinance as yf

    stats = {'symbols': 0, 'bars': 0, 'failed': []}
    for i in range(0, len(symbols), CHUNK):
        batch = symbols[i:i + CHUNK]
        if verbose:
            print(f"[{i + 1:>4}/{len(symbols)}] {' '.join(batch)}", flush=True)
        try:
            df = yf.download(batch, period=period, interval='1d', progress=False,
                             auto_adjust=False, group_by='ticker', threads=True)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! batch failed: {exc}", file=sys.stderr, flush=True)
            stats['failed'].extend(batch)
            continue
        if df is None or df.empty:
            stats['failed'].extend(batch)
            continue

        multi = getattr(df.columns, 'nlevels', 1) > 1
        for sym in batch:
            sub = _frame_for(df, sym, multi)
            if sub is None or sub.empty:
                stats['failed'].append(sym)
                continue
            rows = rows_from_frame(sub.dropna(how='all'))
            if not rows:
                stats['failed'].append(sym)
                continue
            stats['bars'] += upsert_ohlcv(conn, sym, rows)
            stats['symbols'] += 1
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill OHLCV bars into redhood.db")
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--period', default='2y', help="yfinance period (1y, 2y, 5y, max)")
    p.add_argument('--symbols', nargs='*', help="explicit symbol list")
    p.add_argument('--missing-only', action='store_true',
                   help="skip symbols that already have OHLC bars")
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    symbols = args.symbols or target_symbols(conn, args.missing_only)
    if not symbols:
        print("Nothing to do.")
        return 0

    print(f"Backfilling {len(symbols)} symbols, period={args.period}", flush=True)
    stats = backfill(conn, symbols, args.period, verbose=not args.quiet)

    cov = conn.execute("""
        SELECT COUNT(DISTINCT ticker) FROM prices WHERE open IS NOT NULL
    """).fetchone()[0]
    total = conn.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
    print(f"\nDone: {stats['symbols']} symbols, {stats['bars']} bars written.")
    print(f"OHLC coverage: {cov}/{total} symbols in prices")
    if stats['failed']:
        print(f"No data for {len(stats['failed'])}: {' '.join(sorted(set(stats['failed'])))}")
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
