"""Tests for the history layer: timeline pagination, continuation flags, prompt context,
CSV price import, forward returns and portfolio heat — all on a synthetic database."""

import csv
import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from models import init_schema
import redhood_pnl as pnl
import redhood_timeline as tl
from score_narratives import score_all


def _trading_days(start: date, n: int):
    d = start
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def db(tmp_path):
    """A DB with 7 runs, 2 narratives each, repeated themes, synthetic prices for 3 tickers + SPY."""
    path = str(tmp_path / "hist.db")
    init_schema(path)
    conn = sqlite3.connect(path)
    base = datetime(2026, 3, 2, 14, 0)            # 14:00 UTC = before the US close
    titles = [("Defense Primes Procurement Surge", "Long LMT, RTX basket with 6-month horizon"),
              ("AI Capex Acceleration", "Long NVDA shares, 8% trailing stop")]
    for i in range(7):
        run_at = (base + timedelta(days=7 * i)).isoformat()
        cur = conn.execute("INSERT INTO runs (run_at, hours_back, feeds_collected, narratives_extracted) VALUES (?, 5, 40, 2)",
                           (run_at,))
        rid = cur.lastrowid
        for j, (title, hyp) in enumerate(titles):
            if i == 6 and j == 1:
                title, hyp = "Gold Reserve Diversification", "Long GLD on central-bank buying"
            conn.execute(
                "INSERT INTO narratives (id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at, "
                "conviction_adjustment, conviction_size, entropy_band) VALUES (?, ?, ?, ?, ?, 'because', '[\"CPI\"]', ?, ?, ?, ?)",
                (f"n{i}_{j}", rid, title, 5 + j, hyp, run_at, "Half Size — fine", 0.5, "mid"))
    # synthetic prices: 90 trading days from 2026-02-20; SPY flat, LMT falls 1%/day, NVDA rises 1%/day, RTX/GLD flat
    days = _trading_days(date(2026, 2, 20), 90)
    rows = []
    for k, d in enumerate(days):
        rows += [("SPY", d.isoformat(), 100.0), ("LMT", d.isoformat(), 100.0 * (0.99 ** k)),
                 ("NVDA", d.isoformat(), 100.0 * (1.01 ** k)), ("RTX", d.isoformat(), 50.0), ("GLD", d.isoformat(), 200.0)]
    conn.executemany("INSERT INTO prices (ticker, price_date, close) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


def test_score_all_keeps_star_schema_rows(db):
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO narrative_tickers (narrative_id, ticker, side, extracted_pattern) VALUES ('n0_0', 'LMT', 'Long', 'bare')")
    conn.commit()
    conn.close()
    score_all(db)
    conn = sqlite3.connect(db)
    star = conn.execute("SELECT COUNT(*) FROM narrative_tickers WHERE side = 'Long' AND extracted_at IS NULL").fetchone()[0]
    grader = conn.execute("SELECT COUNT(*) FROM narrative_tickers WHERE is_long_equity = 1").fetchone()[0]
    assert star == 1                      # v1 deleted this row; v2 must keep it
    assert grader > 0
    score_all(db)                         # idempotent
    assert conn.execute("SELECT COUNT(*) FROM narrative_tickers WHERE is_long_equity = 1").fetchone()[0] == grader
    conn.close()


def test_forward_returns_and_novelty(db):
    score_all(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    stats = pnl.compute_forward_returns(conn)
    assert stats["written"] > 0 and stats["missing_prices"] == 0
    row = conn.execute("SELECT h5, spy_h5, h20 FROM narrative_returns WHERE ticker = 'NVDA' ORDER BY entry_date LIMIT 1").fetchone()
    assert row["h5"] == pytest.approx(1.01 ** 5 - 1, rel=1e-6)
    assert row["spy_h5"] == pytest.approx(0.0)
    s = pnl.novelty_summary(conn)
    assert s["first"]["n"] == 4            # LMT, RTX, NVDA, GLD first mentions
    assert s["repeat"]["n"] > s["first"]["n"]
    # repeats = 6 x LMT (-1%/day), 6 x RTX (flat), 5 x NVDA (+1%/day; run 7 switched to gold)
    assert s["repeat"]["n"] == 17
    assert s["repeat"]["h20"] == pytest.approx((6 * (0.99 ** 20 - 1) + 5 * (1.01 ** 20 - 1)) / 17, abs=1e-6)
    conn.close()


def test_entry_date_rule():
    assert pnl.entry_date_for_run("2026-03-02T14:00:00") == "2026-03-02"
    assert pnl.entry_date_for_run("2026-03-02T20:05:00") == "2026-03-03"   # after the close -> next day
    assert pnl.entry_date_for_run("") == ""


def test_current_heat(db):
    score_all(db)
    conn = sqlite3.connect(db)
    h = pnl.current_heat(conn, equity=100_000, as_of="2026-04-15")
    # runs on 03-23, 03-30, 04-06, 04-13 fall inside the 20-session window -> 4 runs x 3 longs
    assert h["open_positions"] == 12
    assert h["heat"] == pytest.approx(12 * 2500 * 0.08 / 100_000)
    conn.close()


def test_import_prices_csv(db, tmp_path):
    p = tmp_path / "px.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "price_date", "close", "volume"])
        w.writerow(["XOM", "2026-03-02", "110.5", "1000"])
        w.writerow(["xom", "2026-03-03T00:00:00", "111", ""])
    conn = sqlite3.connect(db)
    stats = pnl.import_prices_csv(conn, str(p))
    assert stats == {"rows": 2, "tickers": 1}
    assert conn.execute("SELECT close FROM prices WHERE ticker='XOM' AND price_date='2026-03-03'").fetchone()[0] == 111.0
    conn.close()


def test_continuation_flags_and_pagination(db):
    conn = sqlite3.connect(db)
    n = tl.flag_continuations(conn)
    assert n == 14
    pm = dict(conn.execute("SELECT id, prior_mentions FROM narratives").fetchall())
    assert pm["n0_0"] == 0                 # first appearance
    assert pm["n3_0"] == 3                 # defense theme seen in runs 0,1,2 within 30 days
    assert pm["n6_1"] == 0                 # gold is new
    page = tl.get_page(conn, page=1, page_size=3)
    assert page["total_runs"] == 7 and page["total_pages"] == 3
    assert [r["run_at"][:10] for r in page["runs"]] == ["2026-04-13", "2026-04-06", "2026-03-30"]   # newest first
    last = tl.get_page(conn, page=99, page_size=3)
    assert last["page"] == 3 and len(last["runs"]) == 1
    conn.close()


def test_recent_context_mentions_redundancy_and_lessons(db):
    score_all(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    pnl.compute_forward_returns(conn)
    tl.flag_continuations(conn)
    ctx = tl.recent_context(conn, n_runs=4, max_chars=4000)
    assert ctx.startswith("HISTORICAL CONTEXT")
    assert "TICKER REDUNDANCY" in ctx and "LMT x" in ctx
    assert "seen" in ctx and "before" in ctx
    assert len(ctx) <= 4000
    empty = sqlite3.connect(":memory:")
    init_schema_mem(empty)
    assert tl.recent_context(empty) == ""
    conn.close()


def init_schema_mem(conn):
    conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, run_at TEXT)")


def test_write_html(db, tmp_path):
    conn = sqlite3.connect(db)
    tl.flag_continuations(conn)
    out = tl.write_html(conn, str(tmp_path / "timeline.html"))
    html = open(out, encoding="utf-8").read()
    assert "RedHood Timeline" in html and "application/json" in html
    data = json.loads(html.split('<script id="data" type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
    assert len(data) == 7 and data[0]["narratives"][0]["title"]
    conn.close()
