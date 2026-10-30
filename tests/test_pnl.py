"""Tests for the redhood_pnl price cache: yfinance frame parsing + top-up logic.

The DataFrame-shape tests need pandas and are skipped where it is not
installed (CI installs only the light test deps). The cache tests use an
in-memory sqlite DB and a stubbed downloader, so they always run and never
touch the network.
"""

import sqlite3

import pytest

import redhood_pnl
from redhood_pnl import (
    TOPUP_OVERLAP_DAYS,
    _ensure_prices_table,
    closes_from_frame,
    last_cached_date,
    update_cache,
    upsert_closes,
)


def _mem_db():
    conn = sqlite3.connect(':memory:')
    _ensure_prices_table(conn)
    return conn


def _seed(conn, ticker, dates, close=100.0):
    conn.executemany(
        "INSERT INTO prices (ticker, price_date, close, fetched_at, source) "
        "VALUES (?, ?, ?, 'seed', 'csv')",
        [(ticker, d, close) for d in dates])
    conn.commit()


def _dates(conn, ticker):
    return [r[0] for r in conn.execute(
        "SELECT price_date FROM prices WHERE ticker = ? ORDER BY price_date", (ticker,))]


class TestClosesFromFrame:
    def test_two_level_columns_single_ticker(self):
        # yfinance >= 0.2.51 shape: df['Close'] is a one-column DataFrame.
        pd = pytest.importorskip('pandas')
        idx = pd.to_datetime(['2026-10-22', '2026-10-23'])
        cols = pd.MultiIndex.from_tuples(
            [('Adj Close', 'SPY'), ('Close', 'SPY'), ('High', 'SPY')],
            names=['Price', 'Ticker'])
        df = pd.DataFrame([[1.0, 763.96, 770.0], [2.0, 759.97, 765.0]], index=idx, columns=cols)
        assert closes_from_frame(df, 'SPY') == [('2026-10-22', 763.96), ('2026-10-23', 759.97)]

    def test_two_level_columns_other_ticker_label(self):
        pd = pytest.importorskip('pandas')
        idx = pd.to_datetime(['2026-10-23'])
        cols = pd.MultiIndex.from_tuples([('Close', 'spy'), ('Open', 'spy')])
        df = pd.DataFrame([[759.97, 759.9]], index=idx, columns=cols)
        # Falls back to the first Close column when the ticker label differs.
        assert closes_from_frame(df, 'SPY') == [('2026-10-23', 759.97)]

    def test_flat_columns(self):
        pd = pytest.importorskip('pandas')
        idx = pd.to_datetime(['2026-10-22', '2026-10-23'])
        df = pd.DataFrame({'Open': [1.0, 2.0], 'Close': [763.96, float('nan')]}, index=idx)
        assert closes_from_frame(df, 'SPY') == [('2026-10-22', 763.96)]

    def test_tz_aware_index_keeps_wall_clock_date(self):
        pd = pytest.importorskip('pandas')
        idx = pd.to_datetime(['2026-10-23 00:00']).tz_localize('America/New_York')
        df = pd.DataFrame({'Close': [10.0]}, index=idx)
        assert closes_from_frame(df, 'SPY') == [('2026-10-23', 10.0)]

    def test_empty_or_missing_close(self):
        pd = pytest.importorskip('pandas')
        assert closes_from_frame(None, 'SPY') == []
        assert closes_from_frame(pd.DataFrame(), 'SPY') == []
        df = pd.DataFrame({'Open': [1.0]}, index=pd.to_datetime(['2026-10-23']))
        assert closes_from_frame(df, 'SPY') == []


class TestUpdateCache:
    def test_tops_up_from_last_cached_close(self, monkeypatch):
        conn = _mem_db()
        _seed(conn, 'SPY', ['2026-10-20', '2026-10-21', '2026-10-22'])
        asked = {}

        def fake(ticker, start, end=None):
            asked['start'] = start
            return [('2026-10-22', 763.96), ('2026-10-23', 759.97)], None

        monkeypatch.setattr(redhood_pnl, 'download_closes', fake)
        assert update_cache(conn, 'SPY', since='2026-01-01') == 2
        # Requested from the overlap window before the last cached close,
        # not from `since` and not from a fixed 7-day tail.
        assert asked['start'] == '2026-10-19'
        assert TOPUP_OVERLAP_DAYS == 3
        assert last_cached_date(conn, 'SPY') == '2026-10-23'
        assert _dates(conn, 'SPY') == ['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23']

    def test_fetches_from_since_when_cache_is_empty_stale_or_forced(self, monkeypatch):
        conn = _mem_db()
        asked = []

        def fake(ticker, start, end=None):
            asked.append(start)
            return [('2026-10-23', 1.0)], None

        monkeypatch.setattr(redhood_pnl, 'download_closes', fake)
        update_cache(conn, 'NEW', since='2026-01-01')              # nothing cached
        _seed(conn, 'OLD', ['2025-12-30'])
        update_cache(conn, 'OLD', since='2026-01-01')              # cache ends before since
        update_cache(conn, 'OLD', since='2026-01-01', force=True)  # forced refetch
        assert asked == ['2026-01-01', '2026-01-01', '2026-01-01']

    def test_zero_rows_is_loud(self, monkeypatch, capsys):
        conn = _mem_db()
        monkeypatch.setattr(
            redhood_pnl, 'download_closes',
            lambda ticker, start, end=None: ([], 'possibly delisted; no timezone found'))
        assert update_cache(conn, 'GPU', since='2026-01-01') == 0
        out = capsys.readouterr().out
        assert 'GPU' in out
        assert '0 rows' in out
        assert 'possibly delisted' in out
        assert _dates(conn, 'GPU') == []

    def test_zero_rows_warning_survives_ascii_console(self, monkeypatch):
        # A cp1252 / ascii console must not turn the warning into a crash
        # that aborts the whole top-up loop.
        import io
        import sys
        buf = io.BytesIO()
        monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(buf, encoding='ascii', errors='strict'))
        conn = _mem_db()
        monkeypatch.setattr(
            redhood_pnl, 'download_closes',
            lambda ticker, start, end=None: ([], 'download failed: boom'))
        assert update_cache(conn, 'SPY', since='2026-01-01') == 0
        sys.stdout.flush()
        out = buf.getvalue().decode('ascii')
        assert 'WARNING' in out and 'SPY' in out and 'boom' in out

    def test_upsert_keeps_ohlcv_columns_from_csv_import(self):
        # The live DB has the CSV importer's extra columns; a close-only
        # refresh must not null them out (INSERT OR REPLACE would).
        conn = sqlite3.connect(':memory:')
        conn.execute("""
            CREATE TABLE prices (
                ticker TEXT NOT NULL, price_date TEXT NOT NULL, close REAL NOT NULL,
                fetched_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'yfinance',
                open REAL, high REAL, low REAL, adj_close REAL, volume INTEGER,
                PRIMARY KEY (ticker, price_date))""")
        conn.execute(
            "INSERT INTO prices VALUES ('SPY', '2026-10-22', 763.96, 't0', 'csv:prices.csv', "
            "766.37, 767.71, 761.17, 763.96, 54035400)")
        assert upsert_closes(conn, 'SPY', [('2026-10-22', 764.0), ('2026-10-23', 759.97)]) == 2
        rows = conn.execute(
            "SELECT price_date, close, source, open, volume FROM prices ORDER BY price_date").fetchall()
        assert rows == [
            ('2026-10-22', 764.0, 'yfinance', 766.37, 54035400),
            ('2026-10-23', 759.97, 'yfinance', None, None),
        ]
