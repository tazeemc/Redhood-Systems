"""Tests for ticker_extraction: side-state scanning + derived-column helpers."""

from ticker_extraction import (
    extract_tickers,
    entropy_band,
    conviction_size,
    catalyst_count,
)


def _as_map(rows):
    """{ticker: side} for easy assertions (dedup already applied upstream)."""
    return {r['ticker']: r['side'] for r in rows}


class TestExtractTickers:
    def test_empty_and_none(self):
        assert extract_tickers("") == []
        assert extract_tickers(None) == []

    def test_long_keyword_propagates_across_slash_pair(self):
        got = _as_map(extract_tickers("Long NVDA/AMD into earnings"))
        assert got == {'NVDA': 'Long', 'AMD': 'Long'}

    def test_pair_trade_long_short_split(self):
        got = _as_map(extract_tickers(
            "Long NVDA/AMD, pair trade long XLK/short XLF"))
        assert got['XLK'] == 'Long'
        assert got['XLF'] == 'Short'

    def test_paren_basket_inherits_side(self):
        got = _as_map(extract_tickers(
            "long defense contractors (LMT, RTX, NOC)"))
        assert got == {'LMT': 'Long', 'RTX': 'Long', 'NOC': 'Long'}

    def test_right_puts_overrides_to_short(self):
        got = _as_map(extract_tickers("long crude exposure via USO puts"))
        assert got['USO'] == 'Short'

    def test_right_calls_overrides_to_long(self):
        # $BLSH — Bullish; also exercises 4-letter symbol handling
        got = _as_map(extract_tickers("BLSH calls into earnings"))
        assert got == {'BLSH': 'Long'}

    def test_semicolon_resets_side_state(self):
        got = _as_map(extract_tickers("Short SQ; NVDA breakout setup"))
        assert got['SQ'] == 'Short'
        # After the reset, NVDA falls back to the default (Long)
        assert got['NVDA'] == 'Long'

    def test_stopwords_are_not_tickers(self):
        rows = extract_tickers("THE FED AND FOMC CPI TARGET FOR EU GDP")
        assert rows == []

    def test_force_keep_symbols_survive(self):
        got = _as_map(extract_tickers("long VIX and short SPY"))
        assert 'VIX' in got and got['SPY'] == 'Short'

    def test_dedup_by_ticker_and_side(self):
        rows = extract_tickers("long NVDA, buy NVDA on dips")
        assert len([r for r in rows if r['ticker'] == 'NVDA']) == 1


class TestEntropyBand:
    def test_bands(self):
        assert entropy_band(1) == 'low'
        assert entropy_band(3) == 'low'
        assert entropy_band(4) == 'mid'
        assert entropy_band(7) == 'mid'
        assert entropy_band(8) == 'high'
        assert entropy_band(10) == 'high'

    def test_none_passthrough(self):
        assert entropy_band(None) is None


class TestConvictionSize:
    def test_known_labels(self):
        assert conviction_size("Full size") == 1.0
        assert conviction_size("Half size given regime") == 0.5
        assert conviction_size("quarter size") == 0.25
        assert conviction_size("PASS") == 0.0

    def test_unknown_and_empty(self):
        assert conviction_size("moon it") is None
        assert conviction_size("") is None
        assert conviction_size(None) is None


class TestCatalystCount:
    def test_json_list(self):
        assert catalyst_count('["CPI", "FOMC"]') == 2
        assert catalyst_count('[]') == 0

    def test_non_list_and_bad_json(self):
        assert catalyst_count('{"a": 1}') == 0
        assert catalyst_count('not json') == 0
        assert catalyst_count(None) == 0
