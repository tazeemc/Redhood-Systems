"""Tests for score_narratives: grading persistence must not clobber the
star-schema ticker rows written by ticker_extraction (shared bridge table).
"""

import sqlite3

import pytest

from models import init_schema
from score_narratives import score_all


@pytest.fixture
def seeded_db(tmp_path):
    """A DB with one narrative plus extractor-written ticker rows."""
    path = str(tmp_path / 'scored.db')
    init_schema(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO runs (run_at, hours_back) VALUES ('2026-07-01T00:00:00', 24)")
    conn.execute(
        "INSERT INTO narratives "
        "(id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at) "
        "VALUES ('n1', 1, 'Defense bid', 4, "
        "'Long defense primes (LMT, RTX) with 15% stop, short ORCL', "
        "'Defense budgets rising', '[\"earnings\"]', '2026-07-01T00:00:00')")
    # Extractor-owned rows: capitalized sides, is_long_equity = 0
    for ticker, side in (('LMT', 'Long'), ('RTX', 'Long'), ('ORCL', 'Short')):
        conn.execute(
            "INSERT INTO narrative_tickers "
            "(narrative_id, ticker, side, extracted_pattern, is_long_equity) "
            "VALUES ('n1', ?, ?, 'left_keyword@0', 0)", (ticker, side))
    conn.commit()
    conn.close()
    return path


def _rows(path, where=''):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM narrative_tickers {where}").fetchall()
    conn.close()
    return rows


def test_scoring_writes_grades(seeded_db):
    stats = score_all(db_path=seeded_db)
    assert stats['narratives'] == 1
    assert stats['grades'] == 1
    conn = sqlite3.connect(seeded_db)
    grade_row = conn.execute(
        "SELECT total_score, letter_grade FROM narrative_grades "
        "WHERE narrative_id = 'n1'").fetchone()
    conn.close()
    assert grade_row is not None
    assert 0 <= grade_row[0] <= 20


def test_scoring_preserves_extractor_ticker_rows(seeded_db):
    before = {(r['ticker'], r['side']) for r in _rows(seeded_db, 'WHERE is_long_equity = 0')}
    score_all(db_path=seeded_db)
    after = {(r['ticker'], r['side']) for r in _rows(seeded_db, 'WHERE is_long_equity = 0')}
    # Short/Hedge/Long star-schema rows must survive scoring untouched
    assert after == before
    assert ('ORCL', 'Short') in after


def test_scoring_adds_grader_long_rows(seeded_db):
    score_all(db_path=seeded_db)
    grader_rows = {(r['ticker'], r['side'])
                   for r in _rows(seeded_db, 'WHERE is_long_equity = 1')}
    assert grader_rows == {('LMT', 'long'), ('RTX', 'long')}


def test_rescoring_is_idempotent(seeded_db):
    score_all(db_path=seeded_db)
    score_all(db_path=seeded_db)
    assert len(_rows(seeded_db, 'WHERE is_long_equity = 1')) == 2
    assert len(_rows(seeded_db, 'WHERE is_long_equity = 0')) == 3
    conn = sqlite3.connect(seeded_db)
    n_grades = conn.execute(
        "SELECT COUNT(*) FROM narrative_grades").fetchone()[0]
    conn.close()
    assert n_grades == 1
