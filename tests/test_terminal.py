"""The terminal bundle is the contract between redhood.db and the page.

These cover the parts the browser can't tell you about: the compressed wire
format round-trips, the alpha maths means what the labels claim, and the page
really is self-contained.
"""

import json
import re
import sqlite3

import pytest

import backfill_ohlcv
import redhood_terminal as T


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """A miniature redhood.db with just enough of the star schema."""
    path = tmp_path / 'test.db'
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE prices (ticker TEXT, price_date TEXT, close REAL,
            fetched_at TEXT, source TEXT, open REAL, high REAL, low REAL,
            adj_close REAL, volume INTEGER, PRIMARY KEY (ticker, price_date));
        CREATE TABLE tickers (ticker TEXT PRIMARY KEY, company_name TEXT,
            asset_class TEXT, sector TEXT, industry TEXT, market_cap_bucket TEXT,
            exchange TEXT, first_seen_at TEXT);
        CREATE TABLE watchlist (symbol TEXT PRIMARY KEY, sources TEXT, raw_symbols TEXT,
            section TEXT, asset_class TEXT, active INTEGER DEFAULT 1,
            first_added_at TEXT, last_synced_at TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY, run_at TEXT, hours_back REAL,
            feeds_collected INTEGER, narratives_extracted INTEGER,
            json_path TEXT, html_path TEXT);
        CREATE TABLE narratives (id TEXT PRIMARY KEY, run_id INTEGER, title TEXT,
            entropy_risk INTEGER, hypothesis TEXT, rationale TEXT, catalysts TEXT,
            created_at TEXT, bear_case TEXT DEFAULT '', disconfirming_signals TEXT DEFAULT '[]',
            conviction_adjustment TEXT DEFAULT '', catalyst_count INTEGER DEFAULT 0,
            conviction_size REAL, entropy_band TEXT, prior_mentions INTEGER DEFAULT 0,
            continuation_of TEXT);
        CREATE TABLE narrative_grades (narrative_id TEXT PRIMARY KEY, specificity INTEGER,
            catalyst_score INTEGER, risk_score INTEGER, cohesion INTEGER,
            total_score INTEGER, letter_grade TEXT, graded_at TEXT);
        CREATE TABLE narrative_tickers (id INTEGER PRIMARY KEY, narrative_id TEXT,
            ticker TEXT, side TEXT, weight_in_hypothesis REAL, extracted_pattern TEXT,
            is_long_equity INTEGER DEFAULT 0, extracted_at TEXT);
        CREATE TABLE narrative_returns (narrative_id TEXT, ticker TEXT, entry_date TEXT,
            entry_close REAL, h5 REAL, h20 REAL, h60 REAL, todate REAL,
            spy_h5 REAL, spy_h20 REAL, spy_h60 REAL, spy_todate REAL,
            last_date TEXT, computed_at TEXT, PRIMARY KEY (narrative_id, ticker));
        CREATE TABLE narrative_feeds (narrative_id TEXT, feed_id TEXT,
            PRIMARY KEY (narrative_id, feed_id));
        CREATE TABLE feeds (id TEXT PRIMARY KEY, run_id INTEGER, source TEXT,
            author TEXT, content TEXT, published_at TEXT, url TEXT, nitter_instance TEXT);
        CREATE TABLE regime_history (id INTEGER PRIMARY KEY, run_id INTEGER,
            computed_at TEXT, symbol TEXT, as_of_date TEXT, label TEXT,
            temperature REAL, entropy REAL, eta REAL, entropy_eq REAL, eta_eq REAL,
            entropy_hi REAL, kl_divergence REAL, kl_threshold REAL, heat REAL,
            heat_budget REAL, signal_multiplier REAL, warning INTEGER DEFAULT 0,
            detector_version TEXT DEFAULT 'v2');
    """)

    # ACME: full OHLCV, with a weekend gap so the delta encoding is exercised.
    bars = [
        ('2026-01-01', 100.0, 101.0, 99.0, 100.5, 1_000_000),
        ('2026-01-02', 100.5, 103.0, 100.0, 102.0, 1_500_000),
        ('2026-01-05', 102.0, 104.0, 101.5, 103.5, 2_000_000),   # +3 days
        ('2026-01-06', 103.5, 105.0, 103.0, 110.0, 2_500_000),
    ]
    for d, o, h, lo, c, v in bars:
        conn.execute("INSERT INTO prices VALUES ('ACME',?,?,'now','test',?,?,?,?,?)",
                     (d, c, o, h, lo, c, v))
    # CLOSEONLY: no OHLC at all -> must land as ohlc=0
    for d, c in [('2026-01-01', 50.0), ('2026-01-02', 51.0), ('2026-01-05', 49.0)]:
        conn.execute("INSERT INTO prices (ticker, price_date, close, fetched_at, source) "
                     "VALUES ('CLOSEONLY',?,?,'now','test')", (d, c))

    conn.execute("INSERT INTO watchlist (symbol, sources, section, asset_class, active) "
                 "VALUES ('ACME','tradingview','RedHood','equity',1)")
    conn.execute("INSERT INTO tickers (ticker, company_name) VALUES ('ACME','Acme Corp')")
    conn.execute("INSERT INTO runs VALUES (1,'2026-01-06T12:00:00',5,10,1,NULL,NULL)")
    conn.execute("""INSERT INTO narratives VALUES
        ('n1',1,'Acme squeeze',6,'Long ACME','because','["earnings"]',
         '2026-01-02T09:00:00','could fade','["margin miss"]','half size',1,0.5,'mid',0,NULL)""")
    conn.execute("INSERT INTO narrative_grades VALUES ('n1',4,3,2,4,13,'B','2026-01-02T10:00:00')")
    conn.execute("INSERT INTO narrative_tickers VALUES (1,'n1','ACME','Long',0.8,'$ACME',1,'now')")
    # +10% raw against SPY's +2% -> +8% excess
    conn.execute("""INSERT INTO narrative_returns VALUES
        ('n1','ACME','2026-01-02',102.0, 0.10,0.10,0.10,0.10, 0.02,0.02,0.02,0.02,
         '2026-01-06','2026-01-06T12:00:00')""")
    conn.execute("""INSERT INTO regime_history VALUES
        (1,1,'2026-01-06T12:00:00','SPY','2026-01-06','TRENDING',
         0.12,1.7,0.73,1.68,0.72,1.9,0.08,0.11,0.03,0.9,1.1,0,'v2')""")
    conn.execute("""INSERT INTO feeds VALUES
        ('f1',1,'rss','Reuters','Acme beats','2026-01-02T08:00:00','http://x/1',NULL)""")
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# wire format
# ---------------------------------------------------------------------------

def test_series_delta_encoding_round_trips(db):
    s = T.build_series(db)['ACME']
    assert s['d0'] == T._day('2026-01-01')
    assert s['d'] == [1, 3, 1]                       # the weekend gap survives
    assert T._days(s) == [T._day(d) for d in
                          ('2026-01-01', '2026-01-02', '2026-01-05', '2026-01-06')]
    assert len(s['d']) == len(s['c']) - 1            # gaps, not timestamps


def test_close_only_symbol_is_marked_and_carries_no_ohlc(db):
    series = T.build_series(db)
    assert series['CLOSEONLY']['ohlc'] == 0
    assert 'o' not in series['CLOSEONLY']
    assert 'v' not in series['CLOSEONLY']
    assert series['ACME']['ohlc'] == 1
    assert series['ACME']['o'][0] == 100.0


def test_volume_is_stored_in_thousands(db):
    assert T.build_series(db)['ACME']['v'] == [1000, 1500, 2000, 2500]


def test_price_rounding_keeps_precision_for_small_numbers():
    assert T._rp(1234.5678) == 1234.57
    assert T._rp(0.123456789) == 0.1235
    assert T._rp(0.000123456) == 0.000123
    assert T._rp(None) is None
    assert T._rp(float('nan')) is None


# ---------------------------------------------------------------------------
# symbol rows
# ---------------------------------------------------------------------------

def test_symbol_row_changes_and_provenance(db):
    series = T.build_series(db)
    rows = {r['t']: r for r in T.build_symbols(db, series)}
    acme = rows['ACME']
    assert acme['last'] == 110.0
    # returns ship rounded to 6dp, so compare at that resolution
    assert acme['d1'] == pytest.approx((110.0 / 103.5) - 1, abs=5e-7)
    assert acme['wl'] == 1 and acme['nar'] == 1
    assert acme['ohlc'] == 1
    assert (acme['from'], acme['to']) == ('2026-01-01', '2026-01-06')
    assert acme['hi'] == 110.0 and acme['lo'] == 100.5
    assert rows['CLOSEONLY']['wl'] == 0


def test_watchlist_symbols_sort_first(db):
    rows = T.build_symbols(db, T.build_series(db))
    assert rows[0]['t'] == 'ACME'


# ---------------------------------------------------------------------------
# narratives & alpha
# ---------------------------------------------------------------------------

def test_narrative_carries_grade_tickers_and_returns(db):
    n = T.build_narratives(db)[0]
    assert n['id'] == 'n1'
    assert n['g']['ltr'] == 'B' and n['g']['tot'] == 13
    assert n['cat'] == ['earnings'] and n['dis'] == ['margin miss']
    assert n['tk'] == [{'t': 'ACME', 'side': 'Long', 'w': 0.8, 'lng': 1}]
    assert n['ret'][0]['h20'] == 0.10 and n['ret'][0]['sh20'] == 0.02


def test_alpha_excess_is_return_minus_spy_over_the_same_window(db):
    alpha = T.build_alpha(T.build_narratives(db))
    h20 = alpha['by_horizon']['20d']
    assert h20['n'] == 1
    assert h20['raw_mean'] == pytest.approx(0.10)
    assert h20['exc_mean'] == pytest.approx(0.08)      # 10% - 2%
    assert h20['win'] == 1.0 and h20['beat'] == 1.0
    assert alpha['by_grade']['B']['20d']['n'] == 1
    assert alpha['by_band']['mid']['20d']['n'] == 1


def test_alpha_is_empty_rather_than_wrong_without_returns(db):
    db.execute("DELETE FROM narrative_returns")
    alpha = T.build_alpha(T.build_narratives(db))
    assert all(v is None for v in alpha['by_horizon'].values())
    assert alpha['scatter'] == [] and alpha['leaders'] == []


def test_malformed_json_columns_do_not_break_the_build(db):
    db.execute("UPDATE narratives SET catalysts='{not json', disconfirming_signals='null'")
    n = T.build_narratives(db)[0]
    assert n['cat'] == [] and n['dis'] == []


# ---------------------------------------------------------------------------
# bundle & page
# ---------------------------------------------------------------------------

def test_bundle_counts_and_regime_snapshot(db):
    b = T.build_bundle(db)
    assert b['meta']['counts'] == {'symbols': 2, 'with_ohlc': 1, 'bars': 7,
                                   'narratives': 1, 'runs': 1, 'regime': 1}
    assert b['meta']['as_of'] == '2026-01-06'
    assert b['meta']['regime_now']['label'] == 'TRENDING'
    assert b['tape'][0]['who'] == 'Reuters'
    assert json.dumps(b)          # the whole bundle must be JSON-serialisable


def test_rendered_page_is_self_contained(db, tmp_path):
    out = tmp_path / 'terminal.html'
    T.write_html(db, str(out))
    html = out.read_text(encoding='utf-8')

    assert '/*%%CSS%%*/' not in html and '/*%%JS%%*/' not in html
    assert '/*%%DATA%%*/' not in html and '/*%%CONFIG%%*/' not in html
    assert 'window.RH_BUNDLE={' in html
    # no network dependencies: every script and style must be inline
    assert not re.search(r'<script[^>]+\ssrc=', html)
    assert not re.search(r'<link[^>]+stylesheet', html)
    assert 'Acme squeeze' in html


def test_data_block_cannot_close_the_script_tag(db, tmp_path):
    db.execute("UPDATE narratives SET title='</script><img src=x>'")
    out = tmp_path / 'terminal.html'
    T.write_html(db, str(out))
    html = out.read_text(encoding='utf-8')
    assert '</script><img' not in html
    assert '<\\/script>' in html


def test_bars_limit_keeps_the_most_recent_bars(db):
    s = T.build_series(db, max_bars=2)['ACME']
    assert s['c'] == [103.5, 110.0]
    assert s['d0'] == T._day('2026-01-05')


# ---------------------------------------------------------------------------
# OHLCV backfill
# ---------------------------------------------------------------------------

def test_backfill_targets_priced_watchlisted_and_narrative_symbols(db):
    syms = backfill_ohlcv.target_symbols(db)
    assert syms == ['ACME', 'CLOSEONLY']


def test_backfill_missing_only_skips_symbols_that_already_have_bars(db):
    for i in range(25):                      # needs > 20 bars to count as covered
        db.execute("INSERT INTO prices VALUES ('ACME',?,1,'now','test',1,1,1,1,1)",
                   (f'2025-02-{i + 1:02d}',))
    assert backfill_ohlcv.target_symbols(db, missing_only=True) == ['CLOSEONLY']


def test_backfill_upsert_upgrades_a_close_only_row_in_place(db):
    rows = [('2026-01-05', 1.0, 2.0, 0.5, 1.5, 1.4, 999)]
    backfill_ohlcv.upsert_ohlcv(db, 'CLOSEONLY', rows)
    r = db.execute("SELECT * FROM prices WHERE ticker='CLOSEONLY' AND price_date='2026-01-05'").fetchone()
    assert (r['open'], r['high'], r['low'], r['close'], r['volume']) == (1.0, 2.0, 0.5, 1.5, 999)


def test_backfill_clean_rejects_nan_and_inf():
    assert backfill_ohlcv._clean(float('nan')) is None
    assert backfill_ohlcv._clean(float('inf')) is None
    assert backfill_ohlcv._clean('x') is None
    assert backfill_ohlcv._clean(3) == 3.0


# ---------------------------------------------------------------------------
# embeddable preview (the block the RedHood Reads report carries)
# ---------------------------------------------------------------------------

def test_preview_is_small_and_carries_the_headline_numbers(db):
    p = T.build_preview(db)
    assert p['counts'] == {'symbols': 2, 'narratives': 1, 'runs': 1, 'bars': 7}
    assert p['regime']['label'] == 'TRENDING'
    assert p['as_of'] == '2026-01-06'
    assert [t['t'] for t in p['tiles']] == ['ACME', 'CLOSEONLY']   # watchlist first
    assert p['tiles'][0]['spark'][-1] == 110.0
    assert p['top'][0]['title'] == 'Acme squeeze' and p['top'][0]['g'] == 'B'
    assert p['alpha']['n'] == 1 and p['alpha']['exc_mean'] == pytest.approx(0.08)
    # small enough to embed in every report
    assert len(json.dumps(p)) < 20000


def test_snippet_renders_tiles_sparklines_and_a_launch_link(db):
    s = T.render_snippet(T.build_preview(db), href='terminal.html')
    assert s.count('class="rh-tile"') == 2
    assert s.count('<svg') == 2                       # one sparkline per tile
    assert 'LAUNCH TERMINAL' in s and 'href="terminal.html"' in s
    assert 'TRENDING' in s and 'Acme squeeze' in s
    assert 'last 60 sessions' in s                    # says what the sparkline is
    assert '.rh-term' in s                            # styles are namespaced
    assert 'data-rh-embed' not in s                   # no iframe unless asked for


def test_snippet_inline_embed_is_opt_in(db):
    s = T.render_snippet(T.build_preview(db), embed_src='terminal.html')
    assert 'data-rh-embed="terminal.html"' in s
    assert '<iframe' not in s          # only created on click, never on load


def test_snippet_escapes_narrative_titles(db):
    db.execute("UPDATE narratives SET title='<img src=x onerror=alert(1)>'")
    s = T.render_snippet(T.build_preview(db))
    assert '<img src=x' not in s
    assert '&lt;img src=x' in s


def test_snippet_survives_an_empty_database(db):
    for t in ('narrative_returns', 'narrative_tickers', 'narrative_grades',
              'narratives', 'regime_history', 'prices', 'watchlist'):
        db.execute(f"DELETE FROM {t}")
    s = T.render_snippet(T.build_preview(db))
    assert 'NO REGIME' in s and 'LAUNCH TERMINAL' in s
