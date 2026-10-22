"""Tests for NitterScraper failure diagnostics, offline via a fake feedparser.

feedparser swallows HTTP and network errors into the parsed result (status,
bozo, bozo_exception), so these fixtures mimic those fields directly.
"""

import urllib.error

import pytest

import redhood_aggregator
from redhood_aggregator import NitterScraper


class _FakeFeed(dict):
    """Stands in for feedparser's FeedParserDict: dict keys + .entries."""

    def __init__(self, entries=(), **fields):
        super().__init__(fields)
        self.entries = list(entries)


class TestDescribeEmpty:
    def test_http_error_status(self):
        assert NitterScraper._describe_empty(_FakeFeed(status=410, bozo=1)) == 'HTTP 410'

    def test_dns_failure(self):
        feed = _FakeFeed(bozo=1, bozo_exception=urllib.error.URLError('getaddrinfo failed'))
        assert NitterScraper._describe_empty(feed) == 'unreachable (getaddrinfo failed)'

    def test_html_bot_check_page(self):
        feed = _FakeFeed(status=200, bozo=1, bozo_exception=ValueError('not xml'))
        assert NitterScraper._describe_empty(feed).startswith('not an RSS feed (HTTP 200')

    def test_valid_but_empty_feed(self):
        feed = _FakeFeed(status=200, bozo=0)
        assert NitterScraper._describe_empty(feed) == 'empty feed (possibly rate-limited)'


class TestFetchFailover:
    @pytest.fixture
    def serve_feeds(self, monkeypatch):
        """Map instance hostnames to fake parsed feeds."""
        feeds = {}

        def fake_parse(url):
            host = url.split('/')[2]
            return feeds[host]

        # raising=False: conftest may install a feedparser stub without parse()
        monkeypatch.setattr(redhood_aggregator.feedparser, 'parse', fake_parse,
                            raising=False)
        return feeds

    def test_reports_each_instance_reason(self, serve_feeds, capsys):
        serve_feeds['a.example'] = _FakeFeed(status=410, bozo=1)
        serve_feeds['b.example'] = _FakeFeed(
            bozo=1, bozo_exception=urllib.error.URLError('no such host'))

        items = NitterScraper(['a.example', 'b.example']).fetch(['someone'], hours_back=24)

        assert items == []
        out = capsys.readouterr().out
        assert 'Could not fetch @someone' in out
        assert 'a.example: HTTP 410' in out
        assert 'b.example: unreachable (no such host)' in out
