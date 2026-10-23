"""Tests for RSSFeedScraper, offline via a fake feedparser."""

import time
from datetime import datetime, timedelta

import redhood_aggregator
from redhood_aggregator import RSSFeedScraper

GHOST_FEED = 'https://unusual-whales.ghost.io/rss/'


class _FakeFeed:
    def __init__(self, title, entries):
        self.feed = {'title': title}
        self.entries = entries


class _FakeEntry(dict):
    """Like feedparser's FeedParserDict: keys readable as attributes too."""
    __getattr__ = dict.__getitem__


def _entry(title, summary, link, age_hours=1):
    published = datetime.now() - timedelta(hours=age_hours)
    return _FakeEntry({
        'title': title,
        'summary': summary,
        'link': link,
        'published_parsed': time.struct_time(published.timetuple()),
    })


def _patch_parse(monkeypatch, feeds):
    monkeypatch.setattr(redhood_aggregator.feedparser, 'parse', lambda url: feeds[url])


def test_unusual_whales_is_configured():
    assert GHOST_FEED in redhood_aggregator.Config.SUBSTACK_FEEDS


def test_ghost_links_rewritten_to_public_news_url(monkeypatch):
    _patch_parse(monkeypatch, {GHOST_FEED: _FakeFeed('Unusual Whales', [
        _entry('SpaceX Seeks Cell Sites', 'SpaceX is in talks...',
               'https://unusual-whales.ghost.io/unusual_blog/post/spacex-cell-sites/'),
    ])})
    [item] = RSSFeedScraper.fetch([GHOST_FEED])
    assert item.url == 'https://unusualwhales.com/news/spacex-cell-sites/'
    assert item.author == 'Unusual Whales'
    assert item.content == 'SpaceX Seeks Cell Sites\nSpaceX is in talks...'


def test_other_links_untouched_and_old_items_dropped(monkeypatch):
    url = 'https://doomberg.substack.com/feed'
    _patch_parse(monkeypatch, {url: _FakeFeed('Doomberg', [
        _entry('Fresh', 'New post', 'https://doomberg.substack.com/p/fresh'),
        _entry('Stale', 'Old post', 'https://doomberg.substack.com/p/stale', age_hours=48),
    ])})
    [item] = RSSFeedScraper.fetch([url], hours_back=24)
    assert item.url == 'https://doomberg.substack.com/p/fresh'


def test_content_falls_back_when_summary_missing_or_repeats_title():
    assert RSSFeedScraper._content({'title': 'Headline'}) == 'Headline'
    assert RSSFeedScraper._content({'title': 'Head', 'summary': 'Head and more'}) == 'Head and more'
