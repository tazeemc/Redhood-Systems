"""Tests for redhood_grader: long-ticker extraction + 0-20 grading rubric."""

from redhood_grader import grade, extract_long_tickers, _letter


def _tickers(hypothesis):
    return [(t.ticker, t.side) for t in extract_long_tickers(hypothesis)]


class TestExtractLongTickers:
    def test_basket_with_sizing_and_stops(self):
        got = _tickers(
            "Long LMT, RTX, and NOC equal-weight basket with 12% position "
            "size, 3-month time horizon, 15% stop loss on portfolio basis")
        assert [t for t, _ in got] == ['LMT', 'RTX', 'NOC']
        assert all(side == 'long' for _, side in got)

    def test_derivative_position_excluded_shares_kept(self):
        # META calls is options — excluded; GOOGL shares is equity — kept
        got = _tickers("Long META calls (ATM, 45 DTE) and long GOOGL shares")
        assert got == [('GOOGL', 'long')]

    def test_ratio_denominator_rejected(self):
        # Long GLD/TLT ratio: long the numerator only
        got = _tickers("Long GLD/TLT ratio, overweight gold miners (GDX)")
        tickers = [t for t, _ in got]
        assert 'GLD' in tickers and 'GDX' in tickers
        assert 'TLT' not in tickers

    def test_short_side_excluded(self):
        got = _tickers("Short ORCL on cloud share loss, long MSFT")
        assert got == [('MSFT', 'long')]

    def test_non_investable_tokens_excluded(self):
        got = _tickers("Long CNY volatility and USD strength, long VIX")
        assert got == []

    def test_bond_positions_excluded(self):
        got = _tickers("Long hyperscaler debt (MSFT/GOOGL bonds)")
        assert got == []


class TestGrade:
    def test_full_featured_hypothesis(self):
        g = grade(
            "Long LMT, RTX, and NOC equal-weight basket with 12% position "
            "size, 3-month time horizon, 15% stop loss on portfolio basis",
            catalysts_json='["earnings"]')
        assert g.letter == 'B'
        assert g.total == 15
        assert g.long_tickers == ['LMT', 'RTX', 'NOC']
        assert g.total == g.specificity + g.catalyst + g.risk + g.cohesion

    def test_empty_hypothesis_grades_f(self):
        g = grade("")
        assert g.letter == 'F'
        assert g.long_tickers == []

    def test_axis_scores_bounded_0_to_5(self):
        g = grade(
            "Long NVDA, AMD, MSFT, GOOGL, META (5 names) 6-month horizon "
            "with 10% stop, hedge with SPY puts, size to regime; "
            "catalysts: earnings, fed, election",
            catalysts_json='["earnings","fed","election","war","supply"]')
        for axis in (g.specificity, g.catalyst, g.risk, g.cohesion):
            assert 0 <= axis <= 5
        assert 0 <= g.total <= 20

    def test_letter_boundaries(self):
        assert _letter(20) == 'A'
        assert _letter(18) == 'A'
        assert _letter(17) == 'A-'
        assert _letter(16) == 'A-'
        assert _letter(13) == 'B'
        assert _letter(10) == 'C'
        assert _letter(7) == 'D'
        assert _letter(6) == 'F'
        assert _letter(0) == 'F'
