"""Synopsis "feed N" references must resolve to report anchors.

Claude cites feeds by their [N] position in the (author-balanced) prompt, so the
report has to number its feed cards/rows the same way, for every source, not
just X/Twitter.
"""

import json
from datetime import datetime, timedelta

from redhood_aggregator import (FeedItem, Narrative, NarrativeExtractor,
                                RedHoodAggregator)


class _FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)

    def create(self, **kwargs):
        text = self._replies.pop(0)
        return type('R', (), {'content': [type('C', (), {'text': text})()]})()


def _feeds():
    now = datetime.now()
    return [
        FeedItem('telegram', '@marketfeed', f'headline {i}', now - timedelta(minutes=i),
                 url=f'https://t.me/marketfeed/{100 - i}')
        for i in range(3)
    ]


def test_extract_records_prompt_index_and_cites_by_it():
    feeds = _feeds()
    extractor = NarrativeExtractor.__new__(NarrativeExtractor)
    extractor.model = 'test'
    extractor.client = type('Client', (), {})()
    extractor.client.messages = _FakeMessages([
        json.dumps({'narratives': [{
            'title': 'T', 'entropy_risk': 5, 'hypothesis': 'h', 'rationale': 'see feed 2',
            'catalysts': [], 'supporting_feed_indices': [2]}]}),
        json.dumps({'stress_tests': []}),
    ])
    narratives = extractor.extract_narratives(feeds, max_feeds=50)
    assert [f.metadata['prompt_index'] for f in feeds] == [1, 2, 3]
    assert narratives[0].supporting_feeds == [feeds[1].id]


def test_report_anchors_match_prompt_index_for_telegram(tmp_path, monkeypatch):
    feeds = _feeds()
    for i, f in enumerate(feeds, 1):
        f.metadata['prompt_index'] = i
    narr = Narrative('Oil', 7, 'Long crude', 'Driven by feed 2 and feeds 1-3',
                     ['EIA'], [feeds[1].id])
    results = {'feeds': [f.to_dict() for f in feeds], 'narratives': [narr.to_dict()]}

    agg = RedHoodAggregator.__new__(RedHoodAggregator)
    monkeypatch.setattr(agg, '_fetch_ticker_prices', lambda: '', raising=False)
    out = tmp_path / 'report.html'
    agg._save_html_report(results, [narr], str(out), '20261023_131553', 3)
    html = out.read_text(encoding='utf-8')

    for n in (1, 2, 3):
        assert f'id="feed-{n}"' in html
    assert 'href="#feed-2"' in html
    assert 'View on Telegram' in html


def test_zero_feeds_hides_count(tmp_path, monkeypatch):
    narr = Narrative('Oil', 7, 'Long crude', 'Driven by supply risk', ['EIA'], [])
    agg = RedHoodAggregator.__new__(RedHoodAggregator)
    monkeypatch.setattr(agg, '_fetch_ticker_prices', lambda: '', raising=False)
    out = tmp_path / 'report.html'
    agg._save_html_report({'feeds': [], 'narratives': [narr.to_dict()]}, [narr],
                          str(out), '20261023_131553', 3)
    html = out.read_text(encoding='utf-8')
    assert 'Compiled from 0' not in html
    assert 'Feeds Collected' not in html
    assert 'AI-assisted analysis' in html
