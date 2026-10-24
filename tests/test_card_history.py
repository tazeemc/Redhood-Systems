"""Signal cards from every report accumulate into one deduped history."""

import json
from datetime import datetime, timedelta

import card_history
from redhood_aggregator import FeedItem, GitHubPagesPublisher, Narrative, RedHoodAggregator


def _report(tmp_path, monkeypatch, start=100, cite=None):
    now = datetime.now()
    feeds = [FeedItem('telegram', '@marketfeed', f'headline {start + i} <b>&amp;</b>',
                      now - timedelta(minutes=i), url=f'https://t.me/marketfeed/{start + i}')
             for i in range(3)]
    for i, f in enumerate(feeds, 1):
        f.metadata['prompt_index'] = i
    narr = Narrative('Oil', 7, 'Long crude', 'feed 1', ['EIA'],
                     [feeds[cite].id] if cite is not None else [])
    agg = RedHoodAggregator.__new__(RedHoodAggregator)
    monkeypatch.setattr(agg, '_fetch_ticker_prices', lambda: '', raising=False)
    out = tmp_path / f'redhood_reads_20261023_13{start % 60:02d}00.html'
    agg._save_html_report({'feeds': [f.to_dict() for f in feeds], 'narratives': [narr.to_dict()]},
                          [narr], str(out), '20261023_131553', 3)
    return out


def test_extracts_cards_from_generated_report(tmp_path, monkeypatch):
    html = _report(tmp_path, monkeypatch, cite=1).read_text(encoding='utf-8')
    cards = card_history.extract_cards(html)
    assert [c['url'] for c in cards] == [f'https://t.me/marketfeed/{n}' for n in (100, 101, 102)]
    assert cards[0]['author'] == '@marketfeed'
    assert cards[0]['text'] == 'headline 100 &'
    assert cards[0]['source'] == 'telegram'
    assert [c['cited'] for c in cards] == [False, True, False]


def test_extracts_link_only_rows_from_old_reports():
    html = ('<tr id="feed-1"><td class="feed-num">1</td><td class="ts">2026-05-14 15:59</td>'
            '<td class="author">@financialjuice</td><td><a href="https://x.com/financialjuice/status/1#m" '
            'target="_blank">x</a></td></tr>'
            '<tr><td class="ts">2026-02-22 12:42</td><td class="author">@FirstSquawk</td>'
            '<td><a href="https://x.com/FirstSquawk/status/2#m">x</a></td></tr>')
    cards = card_history.extract_cards(html)
    assert [(c['author'], c['ts'], c['text']) for c in cards] == [
        ('@financialjuice', '2026-05-14T15:59', ''), ('@FirstSquawk', '2026-02-22T12:42', '')]


def test_merge_dedupes_across_reports():
    a = {'url': 'https://x.com/a/status/1#m', 'author': '@a', 'handle': 'a', 'ts': '2026-10-23T10:00',
         'text': '', 'cited': False, 'source': 'twitter'}
    full = {**a, 'url': 'https://x.com/a/status/1', 'text': 'full text', 'cited': True}
    history = {'cards': {}}
    assert card_history.merge(history, [a], 'r1.html', '2026-10-23T10:05:00') == 1
    assert card_history.merge(history, [full], 'r2.html', '2026-10-23T11:05:00') == 0
    (entry,) = history['cards'].values()
    assert entry['text'] == 'full text' and entry['cited']
    assert entry['reports'] == ['r1.html', 'r2.html']
    assert (entry['first_seen'], entry['last_seen']) == ('2026-10-23T10:05:00', '2026-10-23T11:05:00')
    assert history['updated'] == '2026-10-23T11:05:00'


def test_render_page_embeds_cards_safely():
    history = {'cards': {}}
    card_history.merge(history, [{'url': 'https://x.com/a/status/1', 'author': '@a', 'handle': 'a',
                                  'ts': '2026-10-23T10:00', 'text': '</script><b>x', 'cited': False,
                                  'source': 'twitter'}], 'r.html', '2026-10-23T10:05:00')
    page = card_history.render_page(history)
    assert '</script><b>' not in page
    assert '1 cards' in page


def test_publish_merges_into_existing_history(tmp_path, monkeypatch):
    first = _report(tmp_path, monkeypatch, start=100).read_text(encoding='utf-8')
    second = _report(tmp_path, monkeypatch, start=102, cite=0).read_text(encoding='utf-8')

    store = {}
    pub = GitHubPagesPublisher('token')
    monkeypatch.setattr(pub, '_get_sha', lambda path: 'sha' if path in store else None)
    monkeypatch.setattr(pub, '_get_text', lambda path: store.get(path))
    monkeypatch.setattr(pub, '_put_file', lambda path, content, msg, sha=None: store.__setitem__(path, content))

    pub._publish_card_history(first, 'redhood_reads_20261023_130000.html', 'ts')
    pub._publish_card_history(second, 'redhood_reads_20261023_140000.html', 'ts')

    history = json.loads(store['docs/cards_history.json'])
    assert len(history['cards']) == 5  # 100-102 then 102-104, 102 shared
    shared = history['cards']['https://t.me/marketfeed/102']
    assert shared['cited'] and len(shared['reports']) == 2
    assert '5 cards' in store['docs/cards.html']
