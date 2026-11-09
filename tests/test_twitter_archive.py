"""twitter_archive: the closed X/Twitter record survives the scraper's removal.

Nitter shut down with X's guest access tokens, so the scraper was deleted and
no new tweet can ever arrive. The archive is the standalone record of what was
collected. The feeds rows it copies from must stay put: narrative_feeds
references them ON DELETE CASCADE, so dropping them would silently destroy the
sourcing of every past narrative that cited a tweet.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from models import init_schema
import archive_twitter


def _seed(db):
    """Two runs: three tweets (one cited twice, one once) plus a telegram post."""
    conn = sqlite3.connect(db)
    now = datetime(2026, 8, 21, 3, 0, 0)
    conn.execute("INSERT INTO runs (id, run_at, hours_back) VALUES (1, ?, 5)",
                 (now.isoformat(),))
    rows = [
        ('t1', 1, 'twitter',  '@DeItaone',   'headline one', 'nitter.net'),
        ('t2', 1, 'twitter',  '@FirstSquawk', 'headline two', 'nitter.net'),
        ('t3', 1, 'twitter',  '@DeItaone',   'headline three', None),
        ('g1', 1, 'telegram', '@marketfeed', 'tg post', None),
    ]
    for i, (fid, rid, source, author, content, inst) in enumerate(rows):
        conn.execute(
            "INSERT INTO feeds (id, run_id, source, author, content, published_at, url, nitter_instance)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, rid, source, author, content,
             (now - timedelta(minutes=i)).isoformat(), f'https://x.com/a/{fid}', inst))
    conn.execute("INSERT INTO narratives (id, run_id, title, entropy_risk, hypothesis,"
                 " rationale, catalysts, created_at) VALUES ('n1', 1, 'T', 5, 'h', 'r', '[]', ?)",
                 (now.isoformat(),))
    conn.execute("INSERT INTO narratives (id, run_id, title, entropy_risk, hypothesis,"
                 " rationale, catalysts, created_at) VALUES ('n2', 1, 'U', 5, 'h', 'r', '[]', ?)",
                 (now.isoformat(),))
    # t1 is cited by both narratives, t2 by one, t3 by none.
    for nid, fid in [('n1', 't1'), ('n2', 't1'), ('n1', 't2')]:
        conn.execute("INSERT INTO narrative_feeds (narrative_id, feed_id) VALUES (?, ?)", (nid, fid))
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / 'a.db')
    init_schema(path)
    _seed(path)
    return path


def test_archives_only_twitter_rows(db):
    assert archive_twitter.archive(db) == 3
    conn = sqlite3.connect(db)
    handles = [r[0] for r in conn.execute(
        "SELECT handle FROM twitter_archive ORDER BY feed_id")]
    assert handles == ['@DeItaone', '@FirstSquawk', '@DeItaone']
    conn.close()


def test_denormalises_run_at_and_citation_count(db):
    archive_twitter.archive(db)
    conn = sqlite3.connect(db)
    counts = dict(conn.execute("SELECT feed_id, narrative_count FROM twitter_archive"))
    assert counts == {'t1': 2, 't2': 1, 't3': 0}
    # run_at is copied in so the archive reads standalone.
    assert conn.execute("SELECT run_at FROM twitter_archive WHERE feed_id='t1'").fetchone()[0] \
        == conn.execute("SELECT run_at FROM runs WHERE id=1").fetchone()[0]
    # the serving instance is preserved, including where it was never recorded
    assert conn.execute("SELECT nitter_instance FROM twitter_archive WHERE feed_id='t1'").fetchone()[0] \
        == 'nitter.net'
    assert conn.execute("SELECT nitter_instance FROM twitter_archive WHERE feed_id='t3'").fetchone()[0] is None
    conn.close()


def test_is_idempotent(db):
    archive_twitter.archive(db)
    archive_twitter.archive(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM twitter_archive").fetchone()[0] == 3
    conn.close()


def test_leaves_feeds_and_their_narrative_links_intact(db):
    """The whole point: archiving must not cascade narrative sourcing away."""
    archive_twitter.archive(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM feeds WHERE source='twitter'").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM narrative_feeds").fetchone()[0] == 3
    conn.close()
