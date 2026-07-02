"""Tests for redhood_pnl price fetching: stdlib chart-API fallback."""

import io
import json
import urllib.request

import redhood_pnl
from redhood_pnl import _fetch_prices_chart_api, fetch_prices


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _chart_payload(stamps, closes):
    return json.dumps({
        'chart': {'result': [{
            'timestamp': stamps,
            'indicators': {'quote': [{'close': closes}]},
        }]}
    }).encode()


def test_chart_api_parses_closes(monkeypatch):
    # 2026-06-29 and 2026-06-30 (UTC market-day stamps)
    stamps = [1782745200, 1782831600]
    monkeypatch.setattr(
        urllib.request, 'urlopen',
        lambda req, timeout=None: _FakeResponse(
            _chart_payload(stamps, [25.10, 25.23])))
    rows = _fetch_prices_chart_api('BLSH', '2026-06-28', '2026-07-01')
    assert len(rows) == 2
    assert rows[-1][1] == 25.23
    assert all(len(d) == 10 and d.startswith('2026-') for d, _ in rows)


def test_chart_api_skips_null_closes(monkeypatch):
    monkeypatch.setattr(
        urllib.request, 'urlopen',
        lambda req, timeout=None: _FakeResponse(
            _chart_payload([1782745200, 1782831600], [None, 25.23])))
    rows = _fetch_prices_chart_api('BLSH', '2026-06-28', '2026-07-01')
    assert len(rows) == 1


def test_chart_api_network_error_returns_empty(monkeypatch):
    def boom(req, timeout=None):
        raise OSError('unreachable')
    monkeypatch.setattr(urllib.request, 'urlopen', boom)
    assert _fetch_prices_chart_api('BLSH', '2026-06-28', '2026-07-01') == []


def test_fetch_prices_falls_back_without_yfinance(monkeypatch):
    monkeypatch.setattr(redhood_pnl, '_yfinance_available', lambda: False)
    monkeypatch.setattr(
        urllib.request, 'urlopen',
        lambda req, timeout=None: _FakeResponse(
            _chart_payload([1782831600], [25.23])))
    rows, source = fetch_prices('BLSH', '2026-06-28')
    assert source == 'yahoo-chart'
    assert rows == [('2026-06-30', 25.23)]
