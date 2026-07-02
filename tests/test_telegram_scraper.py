"""Tests for TelegramScraper: t.me/s/ web-preview parsing, offline via mocks.

Fixture HTML mirrors the structure of the real t.me/s/<channel> page:
message blocks split on 'tgme_widget_message_wrap', each with a
tgme_widget_message_text div, a data-post permalink, and a <time datetime=...>.
"""

import io
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from redhood_aggregator import TelegramScraper


def _iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _message_block(text_html, post, dt):
    return f'''tgme_widget_message_wrap js-widget_message_wrap">
      <div class="tgme_widget_message" data-post="{post}">
        <div class="tgme_widget_message_text js-message_text" dir="auto">{text_html}</div>
        <a class="tgme_widget_message_date" href="https://t.me/{post}">
          <time datetime="{_iso_utc(dt)}" class="time">01:41</time>
        </a>
      </div>'''


def _page(*blocks):
    return '<html><body><section class="tgme_channel_history">' \
        + ''.join(blocks) + '</section></body></html>'


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def serve_page(monkeypatch):
    """Patch urllib so TelegramScraper.fetch() reads our fixture page."""
    state = {'page': '', 'requested': []}

    def fake_urlopen(req, timeout=None):
        state['requested'].append(req.full_url)
        return _FakeResponse(state['page'].encode('utf-8'))

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    return state


class TestClean:
    def test_strips_tags_preserves_breaks(self):
        raw = 'JUST IN: Bitcoin reclaims $61,000<br/><br/><a href="x">@WatcherGuru</a>'
        assert TelegramScraper._clean(raw) == \
            'JUST IN: Bitcoin reclaims $61,000\n\n@WatcherGuru'

    def test_unescapes_entities(self):
        assert TelegramScraper._clean('Cloudflare&#39;s x402 &amp; more') == \
            "Cloudflare's x402 & more"

    def test_collapses_excess_blank_lines(self):
        raw = 'a<br><br><br><br>b'
        assert TelegramScraper._clean(raw) == 'a\n\nb'


class TestFetch:
    def test_parses_recent_messages(self, serve_page):
        now = datetime.now(timezone.utc)
        serve_page['page'] = _page(
            _message_block('First message', 'redhoodtrades/100',
                           now - timedelta(hours=1)),
            _message_block('Second &amp; final', 'redhoodtrades/101',
                           now - timedelta(minutes=5)),
        )
        items = TelegramScraper().fetch(['redhoodtrades'], hours_back=24)
        assert len(items) == 2
        assert serve_page['requested'] == ['https://t.me/s/redhoodtrades']
        first, second = items
        assert first.source == 'telegram'
        assert first.author == '@redhoodtrades'
        assert first.content == 'First message'
        assert first.url == 'https://t.me/redhoodtrades/100'
        assert second.content == 'Second & final'

    def test_cutoff_filters_old_messages(self, serve_page):
        now = datetime.now(timezone.utc)
        serve_page['page'] = _page(
            _message_block('old', 'redhoodtrades/1', now - timedelta(hours=30)),
            _message_block('new', 'redhoodtrades/2', now - timedelta(hours=1)),
        )
        items = TelegramScraper().fetch(['redhoodtrades'], hours_back=24)
        assert [i.content for i in items] == ['new']

    def test_timestamps_are_naive_local(self, serve_page):
        now = datetime.now(timezone.utc)
        serve_page['page'] = _page(
            _message_block('msg', 'redhoodtrades/1', now - timedelta(hours=1)))
        items = TelegramScraper().fetch(['redhoodtrades'], hours_back=24)
        ts = items[0].timestamp
        assert ts.tzinfo is None
        # Comparable against datetime.now() without raising (naive vs naive)
        assert abs((datetime.now() - ts).total_seconds()) < 2 * 3600 + 60

    def test_media_only_messages_skipped(self, serve_page):
        now = datetime.now(timezone.utc)
        serve_page['page'] = _page(
            # No message_text div at all (pure media post)
            f'''tgme_widget_message_wrap">
              <div data-post="redhoodtrades/7">
                <time datetime="{_iso_utc(now)}"></time>
              </div>''',
            _message_block('has text', 'redhoodtrades/8', now),
        )
        items = TelegramScraper().fetch(['redhoodtrades'], hours_back=24)
        assert [i.content for i in items] == ['has text']

    def test_at_prefix_stripped_from_channel(self, serve_page):
        serve_page['page'] = _page()
        TelegramScraper().fetch(['@redhoodtrades'], hours_back=24)
        assert serve_page['requested'] == ['https://t.me/s/redhoodtrades']

    def test_network_error_returns_empty_not_raise(self, monkeypatch):
        def boom(req, timeout=None):
            raise OSError('connection refused')
        monkeypatch.setattr(urllib.request, 'urlopen', boom)
        items = TelegramScraper().fetch(['redhoodtrades'], hours_back=24)
        assert items == []
