"""
RedHood Systems - X/Twitter archive
===================================
Files the closed X/Twitter record into ``twitter_archive``.

X was read through Nitter RSS (no API key). Nitter relied on X's guest access
tokens; once those were withdrawn every public instance shut down, so the
scraper was removed and no tweet has been collected since 2026-08-21.

This copies each ``feeds`` row with ``source='twitter'`` into a flat, standalone
snapshot that denormalises the run timestamp and the number of narratives that
cited the tweet. The source rows stay in ``feeds`` on purpose: a large share of
them are referenced by ``narrative_feeds`` (ON DELETE CASCADE), so removing them
would destroy the sourcing of past narratives.

Idempotent -- re-running refreshes the snapshot in place.

Usage:
    python archive_twitter.py            # archive, then print a summary
    python archive_twitter.py --summary  # print the summary only
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')


def archive(db_path: str = DB_PATH) -> int:
    """Copy every X/Twitter feed row into twitter_archive. Returns rows written."""
    conn = sqlite3.connect(db_path)
    try:
        archived_at = datetime.now(timezone.utc).isoformat()
        cur = conn.execute("""
            INSERT OR REPLACE INTO twitter_archive
                (feed_id, run_id, run_at, handle, content, published_at,
                 url, nitter_instance, narrative_count, archived_at)
            SELECT f.id,
                   f.run_id,
                   r.run_at,
                   f.author,
                   f.content,
                   f.published_at,
                   f.url,
                   f.nitter_instance,
                   (SELECT COUNT(*) FROM narrative_feeds nf WHERE nf.feed_id = f.id),
                   ?
              FROM feeds f
              LEFT JOIN runs r ON r.id = f.run_id
             WHERE f.source = 'twitter'
        """, (archived_at,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def summary(db_path: str = DB_PATH) -> None:
    """Print what the archive holds, and flag any X feed row it missed."""
    conn = sqlite3.connect(db_path)
    try:
        total, first, last, runs = conn.execute("""
            SELECT COUNT(*), MIN(published_at), MAX(published_at),
                   COUNT(DISTINCT run_id) FROM twitter_archive
        """).fetchone()
        if not total:
            print("twitter_archive is empty - run `python archive_twitter.py` to fill it.")
            return

        cited = conn.execute(
            "SELECT COUNT(*) FROM twitter_archive WHERE narrative_count > 0").fetchone()[0]
        missing = conn.execute("""
            SELECT COUNT(*) FROM feeds f
             WHERE f.source = 'twitter'
               AND f.id NOT IN (SELECT feed_id FROM twitter_archive)
        """).fetchone()[0]

        print(f"twitter_archive: {total} tweets across {runs} runs")
        print(f"  window        : {first} .. {last}")
        print(f"  cited by a narrative: {cited} ({cited / total:.0%})")
        print(f"  unarchived feeds rows: {missing}")
        print("  by handle:")
        for handle, n, newest in conn.execute("""
            SELECT handle, COUNT(*), MAX(published_at)
              FROM twitter_archive GROUP BY handle ORDER BY COUNT(*) DESC
        """):
            print(f"    {handle:<20} {n:>5}   last {newest}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--summary', action='store_true',
                    help='print the archive summary without writing')
    args = ap.parse_args()

    if not args.summary:
        written = archive()
        print(f"Archived {written} X/Twitter feed rows into twitter_archive.\n")
    summary()


if __name__ == '__main__':
    main()
