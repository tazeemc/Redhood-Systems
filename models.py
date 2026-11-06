"""
RedHood Systems - Data Models
================================
SQLite schema definitions for all persistent entities.

Base ingestion tables (one row per pipeline event):
    twitter_accounts  - tracked X/Twitter handles
    runs              - aggregation pipeline run metadata
    feeds             - raw feed items collected per run
    narratives        - AI-extracted narratives per run
    narrative_feeds   - join: narrative <-> supporting feeds

Star-schema additions (driven by the 2026-05-06 model audit):
    narrative_tickers - bridge: one row per (narrative, ticker, side)
    tickers           - dimension: per-symbol metadata (sector, industry, ...)
    prices            - fact: daily OHLCV per ticker
    earnings          - fact: per-ticker earnings prints
    date_dim          - calendar dimension for joining run_date / created_date / report_date

History additions (paper v3, October 2026 — closing the loop):
    regime_history    - fact: one row per run with the thermodynamic regime state
                        (temperature, occupation entropy, KL departure, heat, label)
    narrative_returns - fact: realised forward returns of each long-side
                        (narrative, ticker) pair vs SPY (5 / 20 / 60 days, to date)
    narratives.prior_mentions / continuation_of - how often the narrative's theme
                        had already appeared, and which earlier narrative it continues
    analyst_notes     - fact: human/AI TL;DR summaries and alpha verdicts attached to a
                        run (and optionally to the narrative / regime row they discuss)

Power BI compatibility views (consumed directly by the .pbix):
    dim_runs, fact_narratives, fact_narratives_ticker,
    dim_ticker, dim_date, fact_prices, fact_earnings

The views are what the audit's recommended star schema expects; the underlying
SQLite tables keep their idiomatic Python names.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')


# ---------------------------------------------------------------------------
# Base tables (ingestion side)
# ---------------------------------------------------------------------------
SCHEMA_BASE = """
-- -----------------------------------------------------------------------
-- twitter_accounts
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS twitter_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    handle      TEXT    NOT NULL UNIQUE,
    added_at    TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    category    TEXT,
    notes       TEXT
);

-- -----------------------------------------------------------------------
-- runs
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT    NOT NULL,
    hours_back      REAL    NOT NULL,
    feeds_collected INTEGER NOT NULL DEFAULT 0,
    narratives_extracted INTEGER NOT NULL DEFAULT 0,
    json_path       TEXT,
    html_path       TEXT
);

-- -----------------------------------------------------------------------
-- feeds
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feeds (
    id              TEXT    PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source          TEXT    NOT NULL,
    author          TEXT    NOT NULL,
    content         TEXT,
    published_at    TEXT    NOT NULL,
    url             TEXT,
    nitter_instance TEXT
);

-- -----------------------------------------------------------------------
-- narratives
--   entropy_band, conviction_size, catalyst_count are derived columns
--   populated at insert time so Power BI can aggregate without DAX gymnastics.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narratives (
    id              TEXT    PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title           TEXT    NOT NULL,
    entropy_risk    INTEGER NOT NULL,
    hypothesis      TEXT    NOT NULL,
    rationale       TEXT    NOT NULL,
    catalysts       TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    bear_case                TEXT    NOT NULL DEFAULT '',
    disconfirming_signals    TEXT    NOT NULL DEFAULT '[]',
    conviction_adjustment    TEXT    NOT NULL DEFAULT '',
    catalyst_count           INTEGER NOT NULL DEFAULT 0,
    conviction_size          REAL,
    entropy_band             TEXT
);

-- -----------------------------------------------------------------------
-- narrative_feeds  (join table)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_feeds (
    narrative_id    TEXT    NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    feed_id         TEXT    NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    PRIMARY KEY (narrative_id, feed_id)
);
"""


# ---------------------------------------------------------------------------
# Star-schema additions (audit gaps G1–G4)
# ---------------------------------------------------------------------------
SCHEMA_STAR = """
-- -----------------------------------------------------------------------
-- narrative_tickers  (bridge — closes audit gap G1 + G2)
--   One row per (narrative, ticker, side). Two producers write here:
--     * ticker_extraction.py (via the aggregator / backfill) populates
--       weight_in_hypothesis + extracted_pattern for the full star schema.
--     * score_narratives.py (via redhood_grader) populates is_long_equity
--       + extracted_at for the long-only P&L ledger.
--   Columns from the producer that did not write a given row stay NULL.
--   is_long_equity defaults to 0 so star-schema rows from ticker_extraction
--   (which include Short/Hedge/Pair sides) are excluded from the long-only
--   P&L ledger; only score_narratives.py sets it to 1 for grader-vetted
--   long equities. Both paths share one bridge table.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_tickers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id          TEXT    NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    ticker                TEXT    NOT NULL,
    side                  TEXT    NOT NULL,   -- Long | Short | Hedge | Pair | long | pair_long
    weight_in_hypothesis  REAL,               -- set by ticker_extraction.py
    extracted_pattern     TEXT,               -- set by ticker_extraction.py
    is_long_equity        INTEGER NOT NULL DEFAULT 0,  -- set to 1 by score_narratives.py: passes the $2,500 long-only filter
    extracted_at          TEXT,               -- set by score_narratives.py (ISO-8601 UTC)
    UNIQUE (narrative_id, ticker, side)
);

-- -----------------------------------------------------------------------
-- narrative_grades  (fact)
--   0–20 quality grades produced by redhood_grader.grade(), one row per
--   narrative. Written by score_narratives.py.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_grades (
    narrative_id    TEXT    PRIMARY KEY REFERENCES narratives(id) ON DELETE CASCADE,
    specificity     INTEGER NOT NULL,                 -- 0-5
    catalyst_score  INTEGER NOT NULL,                 -- 0-5 (named so PBI doesn't collide with catalysts text)
    risk_score      INTEGER NOT NULL,                 -- 0-5
    cohesion        INTEGER NOT NULL,                 -- 0-5
    total_score     INTEGER NOT NULL,                 -- 0-20
    letter_grade    TEXT    NOT NULL,                 -- A / A- / B / C / D / F
    graded_at       TEXT    NOT NULL                  -- ISO-8601 UTC
);

-- -----------------------------------------------------------------------
-- tickers  (dimension)
--   Auto-seeded from extracted symbols; sector/industry filled manually
--   or from a vendor enrichment step.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickers (
    ticker            TEXT    PRIMARY KEY,
    company_name      TEXT,
    asset_class       TEXT,   -- equity | etf | index | future | crypto | fx
    sector            TEXT,
    industry          TEXT,
    market_cap_bucket TEXT,   -- mega | large | mid | small | n/a
    exchange          TEXT,
    first_seen_at     TEXT
);

-- -----------------------------------------------------------------------
-- prices  (fact — closes audit gap G3)
--   Daily close-price cache. Keyed on (ticker, price_date) — the column
--   name every reader/writer already uses (redhood_pnl.py,
--   powerbi/export_to_powerbi.py). OHLC/volume are populated by the star
--   schema path; fetched_at/source are set by redhood_pnl.py's yfinance
--   cache. No FK on ticker so the P&L cache can fetch prices before a
--   symbol is seeded into the tickers dimension.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prices (
    ticker     TEXT    NOT NULL,
    price_date TEXT    NOT NULL,        -- ISO date (YYYY-MM-DD), trading day
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    adj_close  REAL,
    volume     INTEGER,
    fetched_at TEXT,                    -- ISO-8601 UTC (set by redhood_pnl.py)
    source     TEXT    DEFAULT 'yfinance',
    PRIMARY KEY (ticker, price_date)
);

-- -----------------------------------------------------------------------
-- earnings  (fact — closes audit gap G4)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS earnings (
    ticker             TEXT    NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    fiscal_period_end  TEXT    NOT NULL,
    report_date        TEXT    NOT NULL,
    eps_actual         REAL,
    eps_estimate       REAL,
    revenue_actual     REAL,
    revenue_estimate   REAL,
    surprise_pct       REAL,
    time_of_day        TEXT,             -- bmo | amc | dmh
    PRIMARY KEY (ticker, fiscal_period_end)
);

-- -----------------------------------------------------------------------
-- date_dim
--   Real calendar dimension. Power BI's auto Date/Time hierarchy is
--   replaced by joining run_date / created_date / report_date here.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS date_dim (
    date         TEXT PRIMARY KEY,        -- YYYY-MM-DD
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    month_name   TEXT    NOT NULL,
    day          INTEGER NOT NULL,
    day_of_week  INTEGER NOT NULL,        -- 0=Mon .. 6=Sun
    day_name     TEXT    NOT NULL,
    iso_week     INTEGER NOT NULL,
    is_weekend   INTEGER NOT NULL,
    is_month_end INTEGER NOT NULL
);

-- -----------------------------------------------------------------------
-- watchlist  (dimension)
--   The merged, normalized symbol universe the pipeline trades/analyzes,
--   sourced from the user's external watchlists (TradingView, Yahoo
--   Finance) via watchlist.py. One row per normalized (yfinance-format)
--   symbol; provenance is kept so a symbol dropped from every source can
--   be deactivated rather than deleted.
--     * symbol       - normalized yfinance ticker (AAPL, BTC-USD, EURUSD=X)
--     * sources       - comma-joined origin list (e.g. "tradingview,yahoo")
--     * raw_symbols   - comma-joined originals as exported (e.g. "NASDAQ:AAPL")
--     * section       - TradingView section header the symbol sat under
--     * asset_class   - best-effort guess (equity | etf | crypto | fx | index)
--     * active        - 1 while present in some source; 0 once it drops out
--   watchlist.py --sync upserts this table from the export files; run.ps1
--   reads active symbols from it via watchlist.py --symbols.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    symbol        TEXT    PRIMARY KEY,   -- normalized yfinance ticker
    sources       TEXT    NOT NULL DEFAULT '',   -- comma-joined: tradingview | yahoo
    raw_symbols   TEXT,                  -- comma-joined originals as exported
    section       TEXT,                  -- TradingView section header, if any
    asset_class   TEXT,                  -- equity | etf | crypto | fx | index | n/a
    active        INTEGER NOT NULL DEFAULT 1,
    first_added_at TEXT,                 -- ISO-8601 UTC, first sync that saw it
    last_synced_at TEXT                  -- ISO-8601 UTC, most recent sync that saw it
);

-- -----------------------------------------------------------------------
-- regime_history  (fact)
--   One row per aggregator run (and optionally per ad-hoc computation) with
--   the thermodynamic regime state produced by redhood_regime_detector v2.
--   This is the "crisis status and history" the report and the timeline
--   refer back to. label is TRENDING | CHOPPY | CRISIS | TRANSITION.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regime_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    computed_at       TEXT    NOT NULL,          -- ISO-8601 UTC
    symbol            TEXT    NOT NULL DEFAULT 'SPY',
    as_of_date        TEXT,                      -- last price date used
    label             TEXT    NOT NULL,
    temperature       REAL    NOT NULL,          -- annualised, decimal
    entropy           REAL,                      -- occupation entropy S (nats)
    eta               REAL,                      -- S / ln k
    entropy_eq        REAL,                      -- equilibrium S at current T
    eta_eq            REAL,
    entropy_hi        REAL,                      -- calibrated S threshold
    kl_divergence     REAL,                      -- D: KL(observed || Boltzmann at T)
    kl_threshold      REAL,                      -- calibrated D threshold
    heat              REAL,                      -- portfolio heat (fraction of equity at risk)
    heat_budget       REAL,                      -- 1 - heat / heat_max
    signal_multiplier REAL,
    warning           INTEGER NOT NULL DEFAULT 0, -- 1 when D > kl_threshold (drift)
    detector_version  TEXT    NOT NULL DEFAULT 'v2'
);

-- -----------------------------------------------------------------------
-- narrative_returns  (fact)
--   Realised forward returns of each grader-vetted long-side (narrative,
--   ticker) pair, entered at the first close on/after the run date, against
--   SPY over identical windows. Written by redhood_pnl.compute_forward_returns.
--   This closes the P&L loop: the timeline and the extraction prompt read it.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_returns (
    narrative_id    TEXT    NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    ticker          TEXT    NOT NULL,
    entry_date      TEXT,
    entry_close     REAL,
    h5              REAL,                        -- simple return over 5 trading days
    h20             REAL,
    h60             REAL,
    todate          REAL,                        -- to the last cached close
    spy_h5          REAL,
    spy_h20         REAL,
    spy_h60         REAL,
    spy_todate      REAL,
    last_date       TEXT,
    computed_at     TEXT    NOT NULL,
    PRIMARY KEY (narrative_id, ticker)
);

-- -----------------------------------------------------------------------
-- analyst_notes  (fact)
--   TL;DR summaries and alpha verdicts baked into the ledger after a run:
--   the "what did we conclude" record that sits next to the regime state and
--   the narratives it discusses. One row per note; `tldr` is the short form
--   (2-4 sentences), `body` the full Markdown. alpha_verdict is a controlled
--   label (positive | near_zero | negative | hedge_only); alpha_score a
--   subjective -1..+1 scalar for sorting. Written by models.insert_analyst_note.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyst_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    narrative_id    TEXT    REFERENCES narratives(id) ON DELETE SET NULL,
    regime_id       INTEGER REFERENCES regime_history(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL,                 -- ISO-8601 UTC
    author          TEXT    NOT NULL,                 -- e.g. "claude-fable-5-1" | "ctazeem"
    kind            TEXT    NOT NULL DEFAULT 'tldr',  -- tldr | postmortem | memo
    title           TEXT    NOT NULL,
    tldr            TEXT    NOT NULL,                 -- short form
    body            TEXT    NOT NULL,                 -- full Markdown
    alpha_verdict   TEXT,                             -- positive | near_zero | negative | hedge_only
    alpha_score     REAL,                             -- -1..+1
    tags            TEXT    NOT NULL DEFAULT '[]'     -- JSON array of strings
);
"""


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_feeds_run                ON feeds(run_id);
CREATE INDEX IF NOT EXISTS idx_feeds_source             ON feeds(source);
CREATE INDEX IF NOT EXISTS idx_feeds_published          ON feeds(published_at);
CREATE INDEX IF NOT EXISTS idx_narratives_run           ON narratives(run_id);
CREATE INDEX IF NOT EXISTS idx_narratives_risk          ON narratives(entropy_risk);
CREATE INDEX IF NOT EXISTS idx_narratives_band          ON narratives(entropy_band);
CREATE INDEX IF NOT EXISTS idx_narrative_tickers_nid    ON narrative_tickers(narrative_id);
CREATE INDEX IF NOT EXISTS idx_narrative_tickers_ticker ON narrative_tickers(ticker);
CREATE INDEX IF NOT EXISTS idx_narrative_tickers_side   ON narrative_tickers(side);
CREATE INDEX IF NOT EXISTS idx_narrative_grades_letter  ON narrative_grades(letter_grade);
CREATE INDEX IF NOT EXISTS idx_prices_date              ON prices(price_date);
CREATE INDEX IF NOT EXISTS idx_earnings_report_date     ON earnings(report_date);
CREATE INDEX IF NOT EXISTS idx_regime_history_run       ON regime_history(run_id);
CREATE INDEX IF NOT EXISTS idx_regime_history_time      ON regime_history(computed_at);
CREATE INDEX IF NOT EXISTS idx_narrative_returns_ticker ON narrative_returns(ticker);
CREATE INDEX IF NOT EXISTS idx_analyst_notes_run       ON analyst_notes(run_id);
CREATE INDEX IF NOT EXISTS idx_analyst_notes_time      ON analyst_notes(created_at);
"""


# ---------------------------------------------------------------------------
# Power BI compatibility views
#   The .pbix expects dim_runs / fact_narratives names; rather than rename
#   columns inside Power Query, expose views that match the audit's star
#   schema exactly. The .pbix can then drop its rename steps and import
#   these directly.
# ---------------------------------------------------------------------------
SCHEMA_VIEWS = """
DROP VIEW IF EXISTS dim_runs;
CREATE VIEW dim_runs AS
SELECT
    id                                          AS run_id,
    run_at,
    DATE(run_at)                                AS run_date,
    CAST(STRFTIME('%H', run_at) AS INTEGER)     AS run_hour,
    CAST(STRFTIME('%w', run_at) AS INTEGER)     AS run_day_of_week_idx,
    CASE CAST(STRFTIME('%w', run_at) AS INTEGER)
        WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
        WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
        WHEN 6 THEN 'Sat'
    END                                         AS run_day_of_week,
    hours_back,
    feeds_collected,
    narratives_extracted,
    html_path,
    json_path
FROM runs;

DROP VIEW IF EXISTS fact_narratives;
CREATE VIEW fact_narratives AS
SELECT
    n.id                                              AS narrative_id,
    n.run_id,
    n.title,
    n.hypothesis,
    n.rationale,
    n.catalysts,
    n.catalyst_count,
    n.entropy_risk,
    n.entropy_band,
    n.conviction_adjustment,
    n.conviction_size,
    n.bear_case,
    n.disconfirming_signals,
    n.created_at,
    DATE(n.created_at)                                AS created_date,
    CAST(STRFTIME('%H', n.created_at) AS INTEGER)     AS created_hour,
    CAST(STRFTIME('%w', n.created_at) AS INTEGER)     AS created_dow_idx,
    CASE CAST(STRFTIME('%w', n.created_at) AS INTEGER)
        WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
        WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
        WHEN 6 THEN 'Sat'
    END                                               AS created_dow
FROM narratives n;

DROP VIEW IF EXISTS fact_narratives_ticker;
CREATE VIEW fact_narratives_ticker AS
SELECT
    nt.id                  AS row_id,
    nt.narrative_id,
    nt.ticker,
    nt.side,
    nt.weight_in_hypothesis,
    nt.extracted_pattern,
    nt.is_long_equity,
    nt.extracted_at,
    n.run_id,
    DATE(n.created_at)     AS created_date,
    n.entropy_band,
    n.conviction_size
FROM narrative_tickers nt
JOIN narratives n ON n.id = nt.narrative_id;

DROP VIEW IF EXISTS dim_ticker;
CREATE VIEW dim_ticker AS
SELECT
    ticker,
    company_name,
    asset_class,
    sector,
    industry,
    market_cap_bucket,
    exchange,
    first_seen_at
FROM tickers;

DROP VIEW IF EXISTS dim_date;
CREATE VIEW dim_date AS
SELECT
    date,
    year,
    quarter,
    month,
    month_name,
    day,
    day_of_week,
    day_name,
    iso_week,
    is_weekend,
    is_month_end
FROM date_dim;

DROP VIEW IF EXISTS fact_prices;
CREATE VIEW fact_prices AS
SELECT ticker, price_date AS date, open, high, low, close, adj_close, volume
FROM prices;

DROP VIEW IF EXISTS fact_narrative_grades;
CREATE VIEW fact_narrative_grades AS
SELECT
    g.narrative_id,
    g.specificity,
    g.catalyst_score,
    g.risk_score,
    g.cohesion,
    g.total_score,
    g.letter_grade,
    g.graded_at,
    n.run_id,
    DATE(n.created_at)     AS created_date,
    n.entropy_band
FROM narrative_grades g
JOIN narratives n ON n.id = g.narrative_id;

DROP VIEW IF EXISTS fact_earnings;
CREATE VIEW fact_earnings AS
SELECT
    ticker, fiscal_period_end, report_date,
    eps_actual, eps_estimate, revenue_actual, revenue_estimate,
    surprise_pct, time_of_day
FROM earnings;

DROP VIEW IF EXISTS fact_regime_history;
CREATE VIEW fact_regime_history AS
SELECT
    h.id              AS regime_row_id,
    h.run_id,
    h.computed_at,
    DATE(h.computed_at) AS computed_date,
    h.symbol,
    h.as_of_date,
    h.label,
    h.temperature,
    h.entropy,
    h.eta,
    h.entropy_eq,
    h.kl_divergence,
    h.kl_threshold,
    h.heat,
    h.heat_budget,
    h.signal_multiplier,
    h.warning,
    h.detector_version
FROM regime_history h;

DROP VIEW IF EXISTS fact_narrative_returns;
CREATE VIEW fact_narrative_returns AS
SELECT
    r.narrative_id,
    r.ticker,
    r.entry_date,
    r.entry_close,
    r.h5, r.h20, r.h60, r.todate,
    r.spy_h5, r.spy_h20, r.spy_h60, r.spy_todate,
    r.h5  - r.spy_h5      AS excess_h5,
    r.h20 - r.spy_h20     AS excess_h20,
    r.h60 - r.spy_h60     AS excess_h60,
    r.todate - r.spy_todate AS excess_todate,
    r.last_date,
    n.run_id,
    DATE(n.created_at)    AS created_date,
    n.entropy_band,
    n.conviction_size,
    n.prior_mentions
FROM narrative_returns r
JOIN narratives n ON n.id = r.narrative_id;

DROP VIEW IF EXISTS fact_analyst_notes;
CREATE VIEW fact_analyst_notes AS
SELECT
    a.id,
    a.run_id,
    DATE(a.created_at)    AS created_date,
    a.created_at,
    a.author,
    a.kind,
    a.title,
    a.tldr,
    a.alpha_verdict,
    a.alpha_score,
    a.tags,
    a.narrative_id,
    n.title               AS narrative_title,
    a.regime_id,
    g.label               AS regime_label,
    g.signal_multiplier
FROM analyst_notes a
LEFT JOIN narratives      n ON n.id = a.narrative_id
LEFT JOIN regime_history  g ON g.id = a.regime_id;

DROP VIEW IF EXISTS dim_watchlist;
CREATE VIEW dim_watchlist AS
SELECT
    symbol,
    sources,
    raw_symbols,
    section,
    asset_class,
    active,
    first_added_at,
    last_synced_at
FROM watchlist;
"""


# ---------------------------------------------------------------------------
# Migration helpers — additive ALTERs for existing databases.
# Each is wrapped in try/except OperationalError so re-runs are no-ops.
# ---------------------------------------------------------------------------
NARRATIVES_MIGRATIONS = [
    ('bear_case',             "TEXT NOT NULL DEFAULT ''"),
    ('disconfirming_signals', "TEXT NOT NULL DEFAULT '[]'"),
    ('conviction_adjustment', "TEXT NOT NULL DEFAULT ''"),
    ('catalyst_count',        "INTEGER NOT NULL DEFAULT 0"),
    ('conviction_size',       "REAL"),
    ('entropy_band',          "TEXT"),
    ('prior_mentions',        "INTEGER NOT NULL DEFAULT 0"),  # redhood_timeline: theme seen N times before
    ('continuation_of',       "TEXT"),                        # redhood_timeline: id of the narrative it continues
]

# Bring older databases up to the reconciled superset schema. CREATE TABLE
# IF NOT EXISTS never alters an existing table, so DBs built before the star
# schema keep their old columns — these additive ALTERs close the gap. The
# `id` PRIMARY KEY column can't be added via ALTER, but inserts name their
# columns explicitly so its absence is harmless.
NARRATIVE_TICKERS_MIGRATIONS = [
    ('weight_in_hypothesis', "REAL"),                       # ticker_extraction.py
    ('extracted_pattern',    "TEXT"),                       # ticker_extraction.py
    ('is_long_equity',       "INTEGER NOT NULL DEFAULT 0"), # score_narratives.py
    ('extracted_at',         "TEXT"),                       # score_narratives.py
]

PRICES_MIGRATIONS = [
    ('open',       "REAL"),
    ('high',       "REAL"),
    ('low',        "REAL"),
    ('adj_close',  "REAL"),
    ('volume',     "INTEGER"),
    ('fetched_at', "TEXT"),
    ('source',     "TEXT DEFAULT 'yfinance'"),
]

# (table, migrations) pairs applied in order before indexes/views are built.
COLUMN_MIGRATIONS = [
    ('narratives',        NARRATIVES_MIGRATIONS),
    ('narrative_tickers', NARRATIVE_TICKERS_MIGRATIONS),
    ('prices',            PRICES_MIGRATIONS),
]


def init_schema(db_path: str = DB_PATH):
    """Apply the full schema to the database (idempotent)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_BASE)
        conn.executescript(SCHEMA_STAR)

        # Run column migrations BEFORE creating indexes/views that reference them.
        for table, migrations in COLUMN_MIGRATIONS:
            for col, definition in migrations:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                except sqlite3.OperationalError:
                    pass

        conn.executescript(SCHEMA_INDEXES)
        conn.executescript(SCHEMA_VIEWS)
        conn.commit()
    finally:
        conn.close()
    print(f"Schema applied: {db_path}")


def insert_analyst_note(run_id, title, tldr, body, *, author, kind='tldr',
                        narrative_id=None, regime_id=None, alpha_verdict=None,
                        alpha_score=None, tags=(), created_at=None,
                        db_path: str = DB_PATH) -> int:
    """Append one row to analyst_notes and return its id.

    regime_id defaults to the latest regime_history row for run_id, so a note
    is pinned to the regime state the report was generated under.
    """
    import json
    from datetime import datetime, timezone
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        if regime_id is None and run_id is not None:
            row = conn.execute(
                "SELECT id FROM regime_history WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,)).fetchone()
            regime_id = row[0] if row else None
        cur = conn.execute(
            """INSERT INTO analyst_notes
               (run_id, narrative_id, regime_id, created_at, author, kind, title,
                tldr, body, alpha_verdict, alpha_score, tags)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, narrative_id, regime_id, created_at, author, kind, title,
             tldr, body, alpha_verdict, alpha_score, json.dumps(list(tags))))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def describe(db_path: str = DB_PATH):
    """Print column info for all tables and views."""
    conn = sqlite3.connect(db_path)
    objs = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name"
    ).fetchall()
    for name, kind in objs:
        cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
        print(f"\n[{kind}] {name}")
        for col in cols:
            pk   = " PK"        if col[5] else ""
            nn   = " NOT NULL"  if col[3] else ""
            dflt = f" DEFAULT {col[4]}" if col[4] is not None else ""
            print(f"  {col[1]:<28} {col[2]:<12}{pk}{nn}{dflt}")
    conn.close()


if __name__ == '__main__':
    init_schema()
    describe()
