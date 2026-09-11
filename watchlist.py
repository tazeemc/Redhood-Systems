"""
RedHood Systems - Watchlist Integration
=========================================
Merge the user's external watchlists (TradingView + Yahoo Finance) into one
normalized, deduped symbol universe and persist it to the `watchlist` table in
redhood.db. run.ps1 and the Python pipeline then trade/analyze *this* list
instead of a hardcoded default.

Sourcing (see watchlists/README.md for the click-by-click export steps):
    * TradingView  -> "Export watchlist" produces a .txt file of comma-separated
      EXCHANGE:SYMBOL tokens with `###Section` headers.
    * Yahoo Finance -> exporting a portfolio/watchlist produces a .csv whose
      first column is `Symbol`.
Drop those files into the watchlists/ directory and re-run --sync.

Symbol normalization maps every source format onto the yfinance convention that
run.ps1's Yahoo chart endpoint and redhood_pnl.py's yfinance calls expect:
    NASDAQ:AAPL      -> AAPL
    NYSE:BRK.B       -> BRK-B
    BINANCE:BTCUSDT  -> BTC-USD
    OANDA:EURUSD     -> EURUSD=X
    SP:SPX           -> ^GSPC
    TSX:RY           -> RY.TO
Symbols already in yfinance form (AAPL, BTC-USD, ^GSPC, EURUSD=X) pass through
untouched, so a plain one-per-line ticker list works too.

Usage:
    python watchlist.py                 # sync from watchlists/ then list
    python watchlist.py --sync          # parse exports, upsert DB, deactivate drops
    python watchlist.py --list          # show the current watchlist table
    python watchlist.py --symbols       # print active symbols (one per line) for run.ps1
    python watchlist.py --dir PATH      # use a different watchlists directory
    python watchlist.py --dry-run       # parse + show merge result without touching the DB
"""

import argparse
import csv
import glob
import io
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')
WATCHLIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlists')

# Fallback used when no export files exist yet and the DB has no active rows,
# so run.ps1 / the pipeline never end up with an empty symbol list. Mirrors the
# historical run.ps1 default (NU + BTC + FAANG + WMT).
DEFAULT_SYMBOLS = ["NU", "BTC-USD", "META", "AAPL", "AMZN", "NFLX", "GOOGL", "WMT"]

# --- exchange / quote vocabularies used by the normalizer --------------------
US_EQUITY_EXCHANGES = {
    'NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'NYSEARCA', 'BATS', 'CBOE', 'OTC', 'OTCMKTS',
}
CRYPTO_EXCHANGES = {
    'BINANCE', 'COINBASE', 'COINBASEPRO', 'BITSTAMP', 'KRAKEN', 'BYBIT', 'OKX',
    'BITFINEX', 'GEMINI', 'KUCOIN', 'HUOBI', 'GATEIO', 'MEXC', 'CRYPTO', 'CRYPTOCAP',
}
FX_EXCHANGES = {
    'FX', 'FX_IDC', 'OANDA', 'FOREXCOM', 'FXCM', 'SAXO', 'ICMARKETS', 'PEPPERSTONE',
}
# TradingView exchange -> Yahoo Finance ticker suffix for international listings.
EXCHANGE_SUFFIX = {
    'TSX': '.TO', 'TSXV': '.V', 'LSE': '.L', 'LSIN': '.L', 'ASX': '.AX',
    'HKEX': '.HK', 'SEHK': '.HK', 'XETR': '.DE', 'FWB': '.DE', 'EURONEXT': '.PA',
    'EPA': '.PA', 'BIT': '.MI', 'BME': '.MC', 'SIX': '.SW', 'NSE': '.NS', 'BSE': '.BO',
    'TSE': '.T', 'KRX': '.KS', 'SGX': '.SI',
}
# Index tickers (any exchange prefix) -> Yahoo Finance `^` symbols.
INDEX_MAP = {
    'SPX': '^GSPC', 'SPX500': '^GSPC', 'US500': '^GSPC', 'SP500': '^GSPC',
    'NDX': '^NDX', 'US100': '^NDX', 'NAS100': '^NDX', 'USTEC': '^NDX',
    'DJI': '^DJI', 'US30': '^DJI', 'DJIA': '^DJI',
    'VIX': '^VIX', 'RUT': '^RUT', 'US2000': '^RUT',
    'FTSE': '^FTSE', 'DAX': '^GDAXI', 'NKY': '^N225', 'NI225': '^N225', 'HSI': '^HSI',
}
# Crypto quote currencies. Stablecoins collapse to Yahoo's canonical USD pair.
STABLE_QUOTES = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USD'}
FIAT_QUOTES = {'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'BTC', 'ETH'}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _normalize_crypto(base_quote: str):
    """`BTCUSDT` -> `BTC-USD`, `ETHBTC` -> `ETH-BTC`. Returns None if unparseable."""
    s = base_quote.upper().replace('-', '').replace('/', '').replace('PERP', '')
    for quote in sorted(STABLE_QUOTES | FIAT_QUOTES, key=len, reverse=True):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[:-len(quote)]
            yahoo_quote = 'USD' if quote in STABLE_QUOTES else quote
            return f"{base}-{yahoo_quote}"
    return None


def normalize_symbol(raw: str):
    """Map one source token to (yfinance_symbol, asset_class) or (None, None)."""
    if not raw:
        return None, None
    token = raw.strip().strip('"').strip()
    if not token or token.startswith('#'):
        return None, None

    # Already in yfinance form: ^INDEX, PAIR=X, or BASE-QUOTE crypto.
    if token.startswith('^'):
        return token.upper(), 'index'
    if token.upper().endswith('=X'):
        return token.upper(), 'fx'

    exchange, _, symbol = token.partition(':') if ':' in token else ('', '', token)
    exchange = exchange.upper().strip()
    symbol = symbol.upper().strip()
    if not symbol:
        return None, None

    # Passthrough crypto already written as BASE-USD (and not an equity with a
    # class suffix like BRK-B — crypto quotes are a fixed, known set).
    if '-' in symbol:
        base, _, quote = symbol.partition('-')
        if quote in (STABLE_QUOTES | FIAT_QUOTES):
            return f"{base}-{'USD' if quote in STABLE_QUOTES else quote}", 'crypto'

    # Index by symbol regardless of prefix (SP:SPX, TVC:VIX, CAPITALCOM:US100).
    if symbol in INDEX_MAP:
        return INDEX_MAP[symbol], 'index'

    # Crypto by exchange, or by a recognizable stable/fiat quote suffix.
    if exchange in CRYPTO_EXCHANGES:
        c = _normalize_crypto(symbol)
        if c:
            return c, 'crypto'
    if any(symbol.endswith(q) for q in STABLE_QUOTES) and len(symbol) >= 5:
        c = _normalize_crypto(symbol)
        if c:
            return c, 'crypto'

    # FX: 6-letter pair on an FX venue -> EURUSD=X.
    if exchange in FX_EXCHANGES and len(symbol) == 6 and symbol.isalpha():
        return f"{symbol}=X", 'fx'

    # International equity listing -> Yahoo suffix (TSX:RY -> RY.TO).
    if exchange in EXCHANGE_SUFFIX:
        return symbol.replace('.', '-') + EXCHANGE_SUFFIX[exchange], 'equity'

    # US / default equity: drop the exchange, TradingView '.' class -> Yahoo '-'.
    return symbol.replace('.', '-'), 'equity'


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_tradingview(path: str):
    """Yield (raw_token, section) from a TradingView .txt export.

    Export format is comma-separated tokens (often on one line) where a token
    like `###Watchlist` marks the start of a section. Newlines are tolerated so
    a hand-written one-per-line list also parses.
    """
    with open(path, encoding='utf-8-sig') as fh:
        text = fh.read()
    section = None
    for chunk in text.replace('\n', ',').split(','):
        tok = chunk.strip()
        if not tok:
            continue
        if tok.startswith('###'):
            section = tok.lstrip('#').strip() or None
            continue
        yield tok, section


def parse_yahoo(path: str):
    """Yield (raw_symbol, None) from a Yahoo Finance .csv export.

    Yahoo's export puts the ticker in a `Symbol` column. If no such header is
    found (a bare list saved as .csv), fall back to the first column.
    """
    with open(path, encoding='utf-8-sig', newline='') as fh:
        content = fh.read()
    reader = csv.DictReader(io.StringIO(content))
    field = None
    if reader.fieldnames:
        for name in reader.fieldnames:
            if name and name.strip().lower() == 'symbol':
                field = name
                break
    if field:
        for row in reader:
            sym = (row.get(field) or '').strip()
            if sym and sym.lower() != 'symbol':
                yield sym, None
    else:
        # No 'Symbol' header — treat the first column of every row as the ticker.
        for row in csv.reader(io.StringIO(content)):
            if row and row[0].strip() and row[0].strip().lower() != 'symbol':
                yield row[0].strip(), None


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
def _iter_source_files(directory: str):
    """Yield (source_name, path, parser) for each export file, skipping examples."""
    for path in sorted(glob.glob(os.path.join(directory, '*.txt'))):
        if '.example.' not in os.path.basename(path).lower():
            yield 'tradingview', path, parse_tradingview
    for path in sorted(glob.glob(os.path.join(directory, '*.csv'))):
        if '.example.' not in os.path.basename(path).lower():
            yield 'yahoo', path, parse_yahoo


def merge_watchlists(directory: str = WATCHLIST_DIR):
    """Parse every export file and merge into an ordered list of symbol dicts.

    Returns a list (first-seen order) of dicts with keys:
        symbol, sources, raw_symbols, section, asset_class
    plus a list of (source, token) tokens that could not be normalized.
    """
    merged = {}       # symbol -> dict
    order = []        # symbols in first-seen order
    skipped = []      # (source, raw_token)

    for source, path, parser in _iter_source_files(directory):
        for raw, section in parser(path):
            symbol, asset_class = normalize_symbol(raw)
            if not symbol:
                skipped.append((source, raw))
                continue
            if symbol not in merged:
                merged[symbol] = {
                    'symbol': symbol,
                    'sources': [],
                    'raw_symbols': [],
                    'section': section,
                    'asset_class': asset_class,
                }
                order.append(symbol)
            entry = merged[symbol]
            if source not in entry['sources']:
                entry['sources'].append(source)
            if raw not in entry['raw_symbols']:
                entry['raw_symbols'].append(raw)
            if not entry['section'] and section:
                entry['section'] = section

    rows = []
    for symbol in order:
        e = merged[symbol]
        rows.append({
            'symbol': symbol,
            'sources': ','.join(e['sources']),
            'raw_symbols': ','.join(e['raw_symbols']),
            'section': e['section'],
            'asset_class': e['asset_class'],
        })
    return rows, skipped


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------
def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn):
    """Create the watchlist table if the DB predates the schema change."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol        TEXT    PRIMARY KEY,
            sources       TEXT    NOT NULL DEFAULT '',
            raw_symbols   TEXT,
            section       TEXT,
            asset_class   TEXT,
            active        INTEGER NOT NULL DEFAULT 1,
            first_added_at TEXT,
            last_synced_at TEXT
        )
    """)


def sync(directory: str = WATCHLIST_DIR):
    """Parse exports, upsert the watchlist table, deactivate dropped symbols.

    Returns (added, updated, deactivated, total_active, skipped).
    """
    rows, skipped = merge_watchlists(directory)
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    conn = _get_connection()
    _ensure_table(conn)
    try:
        existing = {r['symbol']: r for r in conn.execute("SELECT * FROM watchlist").fetchall()}
        seen = set()
        added = updated = 0

        for r in rows:
            seen.add(r['symbol'])
            if r['symbol'] in existing:
                conn.execute(
                    """UPDATE watchlist
                          SET sources = ?, raw_symbols = ?, section = ?,
                              asset_class = ?, active = 1, last_synced_at = ?
                        WHERE symbol = ?""",
                    (r['sources'], r['raw_symbols'], r['section'],
                     r['asset_class'], now, r['symbol'])
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO watchlist
                           (symbol, sources, raw_symbols, section, asset_class,
                            active, first_added_at, last_synced_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (r['symbol'], r['sources'], r['raw_symbols'], r['section'],
                     r['asset_class'], now, now)
                )
                added += 1

        # Deactivate (never delete) symbols that fell out of every source.
        deactivated = 0
        for symbol, row in existing.items():
            if symbol not in seen and row['active']:
                conn.execute("UPDATE watchlist SET active = 0 WHERE symbol = ?", (symbol,))
                deactivated += 1

        conn.commit()
        total_active = conn.execute(
            "SELECT COUNT(*) FROM watchlist WHERE active = 1"
        ).fetchone()[0]
    finally:
        conn.close()

    return added, updated, deactivated, total_active, skipped


def get_active_symbols():
    """Return active watchlist symbols; fall back to files then DEFAULT_SYMBOLS.

    Importable entry point for the pipeline. Order: crypto/fx/index sink to the
    end so the equity-heavy trading analysis leads, matching the historical
    NU + BTC + FAANG ordering intent while staying deterministic.
    """
    try:
        conn = _get_connection()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE active = 1 ORDER BY rowid"
        ).fetchall()
        conn.close()
        if rows:
            return [r['symbol'] for r in rows]
    except sqlite3.Error:
        pass

    # DB empty / unavailable — parse files directly, else the safe default.
    rows, _ = merge_watchlists()
    if rows:
        return [r['symbol'] for r in rows]
    return list(DEFAULT_SYMBOLS)


# ---------------------------------------------------------------------------
# CLI output
# ---------------------------------------------------------------------------
def list_watchlist():
    conn = _get_connection()
    _ensure_table(conn)
    rows = conn.execute(
        """SELECT symbol, sources, raw_symbols, section, asset_class, active
             FROM watchlist ORDER BY active DESC, rowid"""
    ).fetchall()
    conn.close()

    if not rows:
        print("\nWatchlist is empty. Add exports to watchlists/ and run: python watchlist.py --sync\n")
        return

    print(f"\n{'Symbol':<12} {'Class':<8} {'Sources':<20} {'Active':<7} {'Raw'}")
    print("-" * 78)
    for r in rows:
        status = 'yes' if r['active'] else 'no'
        print(f"{r['symbol']:<12} {(r['asset_class'] or ''):<8} "
              f"{(r['sources'] or ''):<20} {status:<7} {r['raw_symbols'] or ''}")
    active = sum(1 for r in rows if r['active'])
    print(f"\n{active} active / {len(rows)} total symbol(s).\n")


def print_symbols():
    """One symbol per line — consumed by run.ps1 as a PowerShell array."""
    for sym in get_active_symbols():
        print(sym)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RedHood Watchlist Integration (TradingView + Yahoo Finance)')
    parser.add_argument('--sync',    action='store_true', help='Parse exports in watchlists/ and update the DB')
    parser.add_argument('--list',    action='store_true', help='Show the current watchlist table')
    parser.add_argument('--symbols', action='store_true', help='Print active symbols (one per line) for run.ps1')
    parser.add_argument('--dry-run', action='store_true', help='Show the merge result without writing to the DB')
    parser.add_argument('--dir',     metavar='PATH', default=WATCHLIST_DIR, help='Watchlists directory (default: ./watchlists)')
    args = parser.parse_args()

    if args.symbols:
        print_symbols()
    elif args.dry_run:
        rows, skipped = merge_watchlists(args.dir)
        print(f"\nMerged {len(rows)} symbol(s) from {args.dir} (dry run — DB untouched):\n")
        for r in rows:
            print(f"  {r['symbol']:<12} {(r['asset_class'] or ''):<8} [{r['sources']}]  <- {r['raw_symbols']}")
        if skipped:
            print(f"\nSkipped {len(skipped)} unrecognized token(s): "
                  + ', '.join(f'{s}:{t}' for s, t in skipped[:20]))
        print()
    elif args.list:
        list_watchlist()
    else:
        # Default and --sync both sync then show the result.
        added, updated, deactivated, total_active, skipped = sync(args.dir)
        print(f"\nWatchlist synced from {args.dir}")
        print(f"  added {added}, updated {updated}, deactivated {deactivated}, {total_active} active")
        if skipped:
            print(f"  skipped {len(skipped)} unrecognized token(s): "
                  + ', '.join(f'{s}:{t}' for s, t in skipped[:20]))
        list_watchlist()
