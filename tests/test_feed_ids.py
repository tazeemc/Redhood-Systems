"""FeedItem ids: unique per post, stable across runs.

feeds.id is the PRIMARY KEY and _persist_to_db inserts with INSERT OR IGNORE,
so two posts sharing an id silently lose one (run 53 collected 160 feeds and
stored 151: nine same-second @marketfeed pairs collapsed under the old
source_author_epoch id), while an id that changes between overlapping runs
would store the same post again every run.
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

import redhood_aggregator
from models import init_schema
from redhood_aggregator import (FeedItem, Narrative, NarrativeExtractor,
                                RedHoodAggregator)

NOW = datetime(2026, 10, 26, 5, 11, 20)
EPOCH = int(NOW.timestamp())


def _telegram(post, content='text', ts=NOW, channel='marketfeed'):
    return FeedItem('telegram', f'@{channel}', content, ts,
                    url=f'https://t.me/{channel}/{post}', metadata={'channel': channel})


class TestTelegramIds:
    def test_same_second_posts_get_distinct_ids(self):
        a = _telegram(1064096, 'SWITZERLAND DOMESTIC SIGHT DEPOSITS')
        b = _telegram(1064097, "JAPAN'S TOP AUTOMOBILE INDUSTRY UNION")
        assert a.timestamp == b.timestamp
        assert a.id == 'telegram_@marketfeed_1064096'
        assert b.id == 'telegram_@marketfeed_1064097'

    def test_same_post_fetched_again_keeps_its_id(self):
        first = _telegram(1064096)
        # Re-parsed by a later overlapping run, even if local-time handling drifts.
        again = _telegram(1064096, ts=NOW + timedelta(hours=1))
        assert again.id == first.id

    def test_channel_preview_url_has_no_post_id_and_falls_back(self):
        url = 'https://t.me/s/marketfeed'
        a = FeedItem('telegram', '@marketfeed', 'one', NOW, url=url)
        b = FeedItem('telegram', '@marketfeed', 'two', NOW, url=url)
        again = FeedItem('telegram', '@marketfeed', 'one', NOW, url=url)
        assert a.id != b.id
        assert again.id == a.id
        assert a.id.startswith(f'telegram_@marketfeed_{EPOCH}_')


class TestTwitterIds:
    def test_tweet_id_from_status_link(self):
        a = FeedItem('twitter', '@DeItaone', 'a', NOW,
                     url='https://x.com/DeItaone/status/1981#m',
                     metadata={'nitter_instance': 'nitter.net'})
        b = FeedItem('twitter', '@DeItaone', 'b', NOW,
                     url='https://x.com/DeItaone/status/1982#m',
                     metadata={'nitter_instance': 'nitter.net'})
        assert (a.id, b.id) == ('twitter_@DeItaone_1981', 'twitter_@DeItaone_1982')

    def test_same_tweet_via_another_instance_keeps_its_id(self):
        a = FeedItem('twitter', '@DeItaone', 'a', NOW,
                     url='https://x.com/DeItaone/status/1981#m',
                     metadata={'nitter_instance': 'nitter.net'})
        b = FeedItem('twitter', '@DeItaone', 'a', NOW,
                     url='https://x.com/DeItaone/status/1981#m',
                     metadata={'nitter_instance': 'nitter.poast.org'})
        assert b.id == a.id


class TestRssIds:
    def test_guid_preferred_and_survives_link_rewrite(self):
        a = FeedItem('rss', 'Unusual Whales', 'x', NOW,
                     url='https://unusualwhales.com/news/spacex/', metadata={'entry_id': 'guid-1'})
        b = FeedItem('rss', 'Unusual Whales', 'x', NOW + timedelta(minutes=1),
                     url='https://unusual-whales.ghost.io/unusual_blog/post/spacex/',
                     metadata={'entry_id': 'guid-1'})
        assert b.id == a.id
        assert a.id.startswith('rss_Unusual Whales_')
        assert a.id != f'rss_Unusual Whales_{EPOCH}'

    def test_link_used_without_guid(self):
        a = FeedItem('rss', 'Doomberg', 'x', NOW, url='https://doomberg.substack.com/p/a')
        b = FeedItem('rss', 'Doomberg', 'x', NOW, url='https://doomberg.substack.com/p/b')
        again = FeedItem('rss', 'Doomberg', 'x', NOW, url='https://doomberg.substack.com/p/a')
        assert a.id != b.id
        assert again.id == a.id


class TestFallbackIds:
    def test_no_url_keeps_epoch_form_plus_content_hash(self):
        a = FeedItem('rss', 'Unknown RSS', 'first', NOW)
        b = FeedItem('rss', 'Unknown RSS', 'second', NOW)
        again = FeedItem('rss', 'Unknown RSS', 'first', NOW)
        assert a.id != b.id
        assert again.id == a.id
        assert a.id.startswith(f'rss_Unknown RSS_{EPOCH}_')
        assert len(a.id.rsplit('_', 1)[-1]) == 8

    def test_id_is_in_to_dict(self):
        item = _telegram(7)
        assert item.to_dict()['id'] == item.id


def test_parse_claude_response_drops_repeated_feed_index():
    feeds = [_telegram(100 + i, f'headline {i}') for i in range(3)]
    extractor = NarrativeExtractor.__new__(NarrativeExtractor)
    reply = json.dumps({'narratives': [{
        'title': 'T', 'entropy_risk': 5, 'hypothesis': 'h', 'rationale': 'r',
        'catalysts': [], 'supporting_feed_indices': [2, 3, 2, 9]}]})
    [narr] = extractor._parse_claude_response(reply, feeds)
    assert narr.supporting_feeds == [feeds[1].id, feeds[2].id]


def test_report_cites_only_the_cited_same_second_post(tmp_path, monkeypatch):
    feeds = [_telegram(1064096, 'Swiss sight deposits'), _telegram(1064097, 'Japan auto union')]
    for i, f in enumerate(feeds, 1):
        f.metadata['prompt_index'] = i
    narr = Narrative('T', 5, 'h', 'r', [], [feeds[1].id])
    agg = RedHoodAggregator.__new__(RedHoodAggregator)
    monkeypatch.setattr(agg, '_fetch_ticker_prices', lambda: '', raising=False)
    out = tmp_path / 'report.html'
    agg._save_html_report({'feeds': [f.to_dict() for f in feeds], 'narratives': [narr.to_dict()]},
                          [narr], str(out), '20261026_051120', 48)
    html = out.read_text(encoding='utf-8')
    assert html.count('class="tw-card tw-card-cited"') == 1   # CSS names the class too
    assert 'id="feed-1" data-handle="marketfeed" data-cited="0"' in html
    assert 'id="feed-2" data-handle="marketfeed" data-cited="1"' in html


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / 'redhood.db')
    init_schema(path)
    monkeypatch.setattr(redhood_aggregator, 'DB_PATH', path)
    return path


def _persist(feeds, narratives=()):
    agg = RedHoodAggregator.__new__(RedHoodAggregator)
    return agg._persist_to_db(48, feeds, list(narratives), 'r.json', 'r.html')


def test_persist_stores_same_second_posts_and_skips_reseen_ones(db, capsys):
    a, b = _telegram(1064096, 'a'), _telegram(1064097, 'b')
    narr = Narrative('T', 5, 'h', 'r', [], [a.id, b.id])
    run1 = _persist([a, b], [narr])
    # Overlapping run: the same two posts re-parsed, plus one new one.
    run2 = _persist([_telegram(1064096, 'a'), _telegram(1064097, 'b'), _telegram(1064098, 'c')])

    conn = sqlite3.connect(db)
    assert conn.execute('SELECT id, run_id FROM feeds ORDER BY id').fetchall() == [
        ('telegram_@marketfeed_1064096', run1),
        ('telegram_@marketfeed_1064097', run1),
        ('telegram_@marketfeed_1064098', run2),
    ]
    assert conn.execute('SELECT COUNT(*) FROM narrative_feeds WHERE narrative_id = ?',
                        (narr.id,)).fetchone()[0] == 2
    conn.close()
    out = capsys.readouterr().out
    assert '2 feeds (2 new, 0 already stored)' in out
    assert '3 feeds (1 new, 2 already stored)' in out
