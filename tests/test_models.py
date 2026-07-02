"""Tests for models.init_schema: star-schema tables exist on a fresh DB."""

import sqlite3

from models import init_schema

EXPECTED_TABLES = {
    'twitter_accounts', 'runs', 'feeds', 'narratives', 'narrative_feeds',
    'narrative_tickers', 'narrative_grades', 'tickers', 'prices',
    'earnings', 'date_dim',
}


def _names(db_path, kind):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (kind,)).fetchall()
    conn.close()
    return {r[0] for r in rows}


def test_init_schema_creates_all_tables(tmp_path):
    path = str(tmp_path / 'schema.db')
    init_schema(path)
    assert EXPECTED_TABLES <= _names(path, 'table')


def test_init_schema_creates_powerbi_views(tmp_path):
    path = str(tmp_path / 'schema.db')
    init_schema(path)
    views = _names(path, 'view')
    assert any(v.startswith(('dim_', 'fact_')) for v in views)


def test_init_schema_is_idempotent(tmp_path):
    path = str(tmp_path / 'schema.db')
    init_schema(path)
    init_schema(path)  # must not raise on existing objects
    assert EXPECTED_TABLES <= _names(path, 'table')
