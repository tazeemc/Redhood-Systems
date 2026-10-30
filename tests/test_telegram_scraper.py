"""Tests for TelegramScraper: t.me/s/ web-preview parsing, offline via mocks.

Fixture HTML mirrors the structure of the real t.me/s/<channel> page:
message blocks split on 'tgme_widget_message_wrap', each with a
tgme_widget_message_text div, a data-post permalink, and a <time datetime=...>.
"""

import io
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from redhood_aggregator import Config, TelegramScraper


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
    monkeypatch.setattr(time, 'sleep', lambda s: None)   # no between-page pause
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

    def test_same_second_posts_get_distinct_stable_ids(self, serve_page):
        # Run 53 lost nine @marketfeed posts this way: two posts in one second
        # shared the old source_author_epoch id and INSERT OR IGNORE kept one.
        ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        serve_page['page'] = _page(
            _message_block('SWITZERLAND SIGHT DEPOSITS', 'marketfeed/1064096', ts),
            _message_block('JAPAN AUTO UNION', 'marketfeed/1064097', ts),
        )
        first, second = TelegramScraper().fetch(['marketfeed'], hours_back=24)
        assert first.timestamp == second.timestamp
        assert first.id == 'telegram_@marketfeed_1064096'
        assert second.id == 'telegram_@marketfeed_1064097'
        # The same page re-fetched by an overlapping run yields the same ids.
        again = TelegramScraper().fetch(['marketfeed'], hours_back=24)
        assert [i.id for i in again] == [first.id, second.id]

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


class TestPagination:
    @pytest.fixture
    def serve_pages(self, monkeypatch):
        """Serve a different fixture page per URL (newest page + ?before=<id>).

        The between-page politeness pause is stubbed out: each requested sleep
        is recorded in ``state['sleeps']`` instead of actually waiting.
        """
        state = {'pages': {}, 'requested': [], 'sleeps': []}

        def fake_urlopen(req, timeout=None):
            state['requested'].append(req.full_url)
            return _FakeResponse(state['pages'].get(req.full_url, _page()).encode('utf-8'))

        monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
        monkeypatch.setattr(time, 'sleep', lambda s: state['sleeps'].append(s))
        return state

    def test_pages_back_with_before_param(self, serve_pages):
        now = datetime.now(timezone.utc)
        base = 'https://t.me/s/marketfeed'
        serve_pages['pages'] = {
            base: _page(_message_block('newer', 'marketfeed/20', now - timedelta(hours=1))),
            f'{base}?before=20': _page(_message_block('older', 'marketfeed/10', now - timedelta(hours=2))),
        }
        items = TelegramScraper().fetch(['marketfeed'], hours_back=24, max_pages=3)
        assert [i.content for i in items] == ['newer', 'older']
        # Third page (?before=10) is empty, so paging stops there.
        assert serve_pages['requested'] == [base, f'{base}?before=20', f'{base}?before=10']

    def test_stops_once_cutoff_reached(self, serve_pages):
        now = datetime.now(timezone.utc)
        base = 'https://t.me/s/marketfeed'
        serve_pages['pages'] = {
            base: _page(
                _message_block('stale', 'marketfeed/19', now - timedelta(hours=30)),
                _message_block('fresh', 'marketfeed/20', now - timedelta(hours=1)),
            ),
        }
        items = TelegramScraper().fetch(['marketfeed'], hours_back=24, max_pages=5)
        assert [i.content for i in items] == ['fresh']
        assert serve_pages['requested'] == [base]

    def test_stops_when_page_repeats(self, serve_page):
        now = datetime.now(timezone.utc)
        serve_page['page'] = _page(
            _message_block('msg', 'marketfeed/5', now - timedelta(hours=1)))
        items = TelegramScraper().fetch(['marketfeed'], hours_back=24, max_pages=5)
        # Same page returned for ?before=5 makes no progress -> stop, without dupes.
        assert len(serve_page['requested']) == 2
        assert [i.content for i in items] == ['msg']

    def test_pages_past_five_until_cutoff_reached(self, serve_pages, capsys):
        """Paging is driven by the cutoff, not a small page budget: eight
        in-window pages are walked (the old cap was 5) and paging stops on the
        page that crosses the cutoff, pausing once between page requests."""
        now = datetime.now(timezone.utc)
        base = 'https://t.me/s/marketfeed'
        pages, prev_id = {}, None
        for k in range(1, 9):                 # 8 pages, one in-window post each
            post_id = 100 - k
            key = base if prev_id is None else f'{base}?before={prev_id}'
            pages[key] = _page(_message_block(
                f'post {k}', f'marketfeed/{post_id}', now - timedelta(hours=k)))
            prev_id = post_id
        # Page 9 crosses the 24 h cutoff -> paging stops there.
        pages[f'{base}?before={prev_id}'] = _page(
            _message_block('too old', 'marketfeed/50', now - timedelta(hours=30)))
        serve_pages['pages'] = pages

        items = TelegramScraper().fetch(['marketfeed'], hours_back=24,
                                        max_pages=Config.TELEGRAM_MAX_PAGES)

        assert [i.content for i in items] == [f'post {k}' for k in range(1, 9)]
        assert len(serve_pages['requested']) == 9
        assert serve_pages['requested'][-1] == f'{base}?before=92'
        assert serve_pages['sleeps'] == [TelegramScraper.PAGE_DELAY] * 8
        out = capsys.readouterr().out
        assert '@marketfeed: 8 posts across 9 page(s)' in out
        assert 'shorter than the window' not in out

    def test_warns_when_page_cap_hit_before_cutoff(self, serve_pages, capsys):
        now = datetime.now(timezone.utc)
        base = 'https://t.me/s/marketfeed'
        oldest = now - timedelta(hours=3)
        serve_pages['pages'] = {
            base: _page(_message_block('p1', 'marketfeed/30', now - timedelta(hours=1))),
            f'{base}?before=30': _page(_message_block('p2', 'marketfeed/20', now - timedelta(hours=2))),
            f'{base}?before=20': _page(_message_block('p3', 'marketfeed/10', oldest)),
            # Still inside the window, but the cap of 3 stops paging first.
            f'{base}?before=10': _page(_message_block('p4', 'marketfeed/5', now - timedelta(hours=4))),
        }

        items = TelegramScraper().fetch(['marketfeed'], hours_back=24, max_pages=3)

        assert [i.content for i in items] == ['p1', 'p2', 'p3']
        assert len(serve_pages['requested']) == 3
        out = capsys.readouterr().out
        oldest_local = oldest.astimezone().replace(tzinfo=None).strftime('%Y-%m-%d %H:%M')
        assert '⚠️' in out
        assert 'Telegram @marketfeed: stopped before the 24h cutoff (page cap of 3 hit)' in out
        assert f'3 posts across 3 page(s), oldest {oldest_local}' in out
        assert 'Coverage is shorter than the window' in out

    def test_warns_when_channel_runs_out_before_cutoff(self, serve_pages, capsys):
        now = datetime.now(timezone.utc)
        base = 'https://t.me/s/newchannel'
        serve_pages['pages'] = {
            base: _page(_message_block('only post', 'newchannel/3', now - timedelta(hours=2))),
            # ?before=3 falls back to the fixture's empty page: channel exhausted.
        }
        items = TelegramScraper().fetch(['newchannel'], hours_back=48, max_pages=10)
        assert [i.content for i in items] == ['only post']
        assert len(serve_pages['requested']) == 2
        out = capsys.readouterr().out
        assert 'Telegram @newchannel: stopped before the 48h cutoff (channel has no older posts)' in out
        assert '1 posts across 2 page(s)' in out


class TestConfig:
    def test_both_telegram_channels_configured(self):
        assert Config.TELEGRAM_CHANNELS == ["marketfeed", "tradehaven"]

    def test_page_ceiling_covers_a_busy_48h_window(self):
        # 5 pages (100 posts) covered ~5 h of @marketfeed; the ceiling must be
        # a safety net, not the thing that ends paging on a 48 h run.
        assert Config.TELEGRAM_MAX_PAGES >= 60
