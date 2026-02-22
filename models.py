"""
RedHood Insights - Data Models
================================
SQLite schema definitions for all persistent entities.

Tables:
    twitter_accounts  - tracked X/Twitter handles
    runs              - aggregation pipeline run metadata
    feeds             - raw feed items collected per run
    narratives        - AI-extracted narratives per run
    narrative_feeds   - join table: narrative <-> supporting feeds
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')

SCHEMA = """
-- -----------------------------------------------------------------------
-- twitter_accounts
-- Tracked X/Twitter handles pulled via Nitter RSS each run.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS twitter_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    handle      TEXT    NOT NULL UNIQUE,       -- e.g. "FirstSquawk" (no @)
    added_at    TEXT    NOT NULL,              -- ISO-8601 UTC
    active      INTEGER NOT NULL DEFAULT 1,   -- 1 = active, 0 = paused
    category    TEXT,                         -- e.g. "news", "macro", "market"
    notes       TEXT                          -- free-text description
);

-- -----------------------------------------------------------------------
-- runs
-- One row per pipeline execution.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT    NOT NULL,          -- ISO-8601 UTC timestamp
    hours_back      REAL    NOT NULL,          -- time window requested
    feeds_collected INTEGER NOT NULL DEFAULT 0,
    narratives_extracted INTEGER NOT NULL DEFAULT 0,
    json_path       TEXT,                      -- path to output JSON file
    html_path       TEXT                       -- path to output HTML file
);

-- -----------------------------------------------------------------------
-- feeds
-- Raw feed items collected during a run.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feeds (
    id              TEXT    PRIMARY KEY,       -- e.g. "twitter_@FirstSquawk_1234"
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source          TEXT    NOT NULL,          -- "twitter" | "rss"
    author          TEXT    NOT NULL,          -- "@FirstSquawk" or RSS feed title
    content         TEXT,                      -- raw HTML/text of post
    published_at    TEXT    NOT NULL,          -- ISO-8601 timestamp from feed
    url             TEXT,                      -- canonical x.com or article URL
    nitter_instance TEXT                       -- which Nitter node served it
);

-- -----------------------------------------------------------------------
-- narratives
-- AI-extracted market narratives per run.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narratives (
    id              TEXT    PRIMARY KEY,       -- e.g. "narrative_1234567890"
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title           TEXT    NOT NULL,
    entropy_risk    INTEGER NOT NULL,          -- 1-10
    hypothesis      TEXT    NOT NULL,          -- trade idea
    rationale       TEXT    NOT NULL,          -- AI reasoning
    catalysts       TEXT    NOT NULL,          -- JSON array of strings
    created_at      TEXT    NOT NULL           -- ISO-8601 UTC
);

-- -----------------------------------------------------------------------
-- narrative_feeds  (join table)
-- Links a narrative to the feed items that support it.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_feeds (
    narrative_id    TEXT    NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    feed_id         TEXT    NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    PRIMARY KEY (narrative_id, feed_id)
);

-- -----------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_feeds_run        ON feeds(run_id);
CREATE INDEX IF NOT EXISTS idx_feeds_source     ON feeds(source);
CREATE INDEX IF NOT EXISTS idx_feeds_published  ON feeds(published_at);
CREATE INDEX IF NOT EXISTS idx_narratives_run   ON narratives(run_id);
CREATE INDEX IF NOT EXISTS idx_narratives_risk  ON narratives(entropy_risk);
"""


def init_schema(db_path: str = DB_PATH):
    """Apply the full schema to the database (idempotent)."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Schema applied: {db_path}")


def describe(db_path: str = DB_PATH):
    """Print column info for all tables."""
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    for (table,) in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        print(f"\n[{table}]")
        for col in cols:
            pk  = " PK" if col[5] else ""
            nn  = " NOT NULL" if col[3] else ""
            dflt = f" DEFAULT {col[4]}" if col[4] is not None else ""
            print(f"  {col[1]:<28} {col[2]:<12}{pk}{nn}{dflt}")
    conn.close()


if __name__ == '__main__':
    init_schema()
    describe()
