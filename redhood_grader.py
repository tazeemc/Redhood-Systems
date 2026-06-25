"""
RedHood Insights — Hypothesis Grader & Ticker Extractor
========================================================
Parses free-text trade hypotheses produced by the aggregator and emits:

    - Long-side equity / ETF tickers (with reason for inclusion / exclusion)
    - A 0-20 quality grade across four axes (Specificity / Catalyst /
      Risk Management / Cohesion) and a letter grade A-F.

Pure stdlib - no external dependencies. Mirrors the rubric used in the
Excel trade ledger (Redhood_Trade_Ledger.xlsx) so grades stay consistent
across the SQLite store, Power BI, and the spreadsheet artefacts.

Usage:
    from redhood_grader import grade, extract_long_tickers

    g = grade("Long defense primes (LMT, RTX, NOC) 6-month horizon")
    print(g.letter, g.total, g.long_tickers)

    # Or as a CLI smoke-test:
    python redhood_grader.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, asdict


# ----------------------------------------------------------------------------
# Ticker extraction
# ----------------------------------------------------------------------------

# Tokens that look like tickers but are NOT investable equity / ETF names.
NON_INVESTABLE = frozenset({
    # Forex / currency codes
    "CNY", "USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "HKD",
    "INR", "KRW", "BRL", "MXN", "RUB", "TRY", "ZAR", "SGD", "TWD",
    # Index / vol products / commodity benchmarks
    "SPX", "NDX", "DJX", "RUT", "VIX", "OVX", "MOVE", "WTI", "BRENT",
    "MSCI", "FTSE", "STOXX", "NIKKEI", "DAX", "CAC",
    # Generic finance / instrument acronyms
    "ATM", "OTM", "ITM", "DTE", "ETF", "REIT", "API", "ADR", "ADRS",
    "LME", "WFH", "ESG", "AI", "CPI", "PPI", "GDP", "FED", "FOMC",
    # Position-sizing / structure words sometimes capitalised
    "LONG", "SHORT", "PAIR", "STOP", "OTC", "DTC",
    # Geographic / org tokens
    "US", "EU", "UK", "EM", "DM", "ASEAN", "OPEC", "NATO",
    # Asset-class buckets (not direct tickers in narratives)
    "IPOS", "SPACS", "IPO", "SPAC",
})

# Words near a ticker that mean the position is options / futures, not shares.
DERIVATIVE_MARKERS = (
    "call", "calls", "put", "puts", "futures", "future",
    "atm ", " otm", "dte", "strike",
)

# Words near a ticker that mean the position is bonds / debt, not equity.
DEBT_MARKERS = ("bond", "bonds", "debt", "credit", "yield")

# Words in a clause that mean a "long X/Y ratio/spread" — long the numerator,
# NOT the denominator. We reject the denominator.
RATIO_MARKERS = ("ratio", "spread")

# Long / short marker words (lowercased, scanned in same clause).
LONG_WORDS  = ("long", "buy", "overweight", "accumulate", "add to", "bullish on")
SHORT_WORDS = ("short", "sell", "underweight", "reduce", "fade", "bearish on")

# Pattern for a candidate ticker: 1-5 uppercase letters.
TICKER_RE = re.compile(r'\b([A-Z]{1,5})\b')

# Explicit equity / ETF allow-list — names we know are investable as shares.
# Used to short-circuit the heuristic for canonical tickers.
KNOWN_EQUITIES = frozenset({
    "LMT","RTX","NOC","GD","DFEN","TSM","USO","BNO","NVDA","AMD",
    "MSFT","GOOGL","META","SNAP","XLE","ARKX","ASML","KLAC","GLD",
    "GDX","PLTR","HACK","CRWD","PANW","FTNT","CRM","ADBE","DLR",
    "EQIX","TLT","ORCL","VNO","SPY","QQQ","KWEB","LHX","CIBR","DJI",
    "AAPL","AMZN","TSLA","MU","INTC","AVGO","BABA","DIS","BAC",
    "JPM","WMT","XOM","CVX","COIN","HOOD",
})


@dataclass
class TickerMention:
    ticker: str
    side: str               # 'long' | 'short' | 'pair_long' | 'pair_short' | 'unknown'
    is_long_equity: bool    # True if eligible for the $2,500 long-only ledger
    reason: str             # human-readable inclusion / exclusion reason


def _split_clauses(text: str) -> list[str]:
    """Split a hypothesis into trade-clauses.

    We deliberately do NOT split on commas or "and" because basket
    enumerations like "(LMT, RTX, NOC, GD)" or "Long LMT, RTX, and NOC"
    are single trades — splitting them strips the verb "Long" from later
    items in the list. We also skip "then" because it's rare in prose.

    Splitters: semicolon, plus the connector words "with", "hedge",
    "pair", "while", "but" (each at a word boundary).
    """
    if not text:
        return []
    norm = re.sub(r'\b(with|hedge|pair|while|but)\b|;', '|', text, flags=re.I)
    return [c.strip() for c in norm.split('|') if c.strip()]


def _is_options_or_futures_context(clause: str, ticker: str) -> bool:
    """True if this ticker mention is a derivative or bonds position.

    Only checks the AFTER-window of the ticker. Markers like "calls", "puts",
    "DTE", "strike", "bonds" bind to the immediately preceding ticker
    ("META calls", "MSFT/GOOGL bonds"), not to a later ticker in the same
    clause. Looking before the ticker would falsely taint shares mentions
    that follow a different ticker's derivative position.
    """
    m = re.search(rf'\b{re.escape(ticker)}\b', clause)
    if not m:
        return False
    low = clause.lower()
    # 35-char window AFTER the ticker — long enough to catch "MSFT/GOOGL bonds"
    # or "TLT calls (1-month)" but not so long it pulls in unrelated tail words.
    after = low[m.end(): m.end() + 35]
    if any(mk in after for mk in DERIVATIVE_MARKERS):
        if re.search(rf'\b{re.escape(ticker)}\s+shares\b', clause, re.I):
            return False
        return True
    if any(mk in after for mk in DEBT_MARKERS):
        return True
    return False


def _is_ratio_denominator(clause: str, ticker: str) -> bool:
    """Pattern: "Long GLD/TLT ratio" — GLD is long, TLT is short. Reject TLT.

    Use word-boundary matching for the ratio/spread keywords so that
    "acceleration" doesn't trigger on the "ratio" substring.
    """
    if not any(re.search(rf'\b{mk}\b', clause, re.I) for mk in RATIO_MARKERS):
        return False
    pat = re.compile(r'\b([A-Z]{1,5})/([A-Z]{1,5})\b')
    for m in pat.finditer(clause):
        _, den = m.group(1), m.group(2)
        if ticker == den:
            return True
    return False


def _classify_side(clause: str, ticker: str) -> str:
    """Classify long / short for a given ticker inside a clause."""
    low = clause.lower()
    m = re.search(rf'\b{re.escape(ticker)}\b', clause)
    if not m:
        return "unknown"

    before = low[: m.start()]
    near = before[-80:]

    # Word-boundary matching so "shorting" doesn't satisfy SHORT and
    # "longstanding" doesn't satisfy LONG.
    long_hit  = any(re.search(rf'\b{re.escape(w)}\b', near) for w in LONG_WORDS)
    short_hit = any(re.search(rf'\b{re.escape(w)}\b', near) for w in SHORT_WORDS)

    # Pair-trade pattern: "long X vs short Y".
    if " vs " in low or " versus " in low:
        parts = re.split(r' vs | versus ', clause, maxsplit=1, flags=re.I)
        left, right = (parts + ['', ''])[:2]
        if ticker in left and not short_hit:
            return "pair_long"
        if ticker in right and not long_hit:
            return "pair_short"

    if long_hit and not short_hit:
        return "long"
    if short_hit and not long_hit:
        return "short"
    if long_hit and short_hit:
        # Use word-boundary positions so "shorting" doesn't beat a closer "long"
        long_pos  = [m.start() for w in LONG_WORDS  for m in re.finditer(rf'\b{re.escape(w)}\b', near)]
        short_pos = [m.start() for w in SHORT_WORDS for m in re.finditer(rf'\b{re.escape(w)}\b', near)]
        long_idx  = max(long_pos)  if long_pos  else -1
        short_idx = max(short_pos) if short_pos else -1
        return "long" if long_idx > short_idx else "short"
    return "unknown"


def extract_long_tickers(hypothesis: str) -> list[TickerMention]:
    """
    Walk each clause in the hypothesis, find ticker tokens, classify side,
    and return only the long-side equity / ETF mentions.
    """
    out: list[TickerMention] = []
    seen: set = set()

    for clause in _split_clauses(hypothesis):
        for m in TICKER_RE.finditer(clause):
            t = m.group(1)
            if len(t) < 2:
                continue
            if t in NON_INVESTABLE:
                continue
            # Heuristic gate: keep if known equity OR the clause unambiguously
            # treats it as a stock/ETF (no derivative/bond markers in window).
            if t not in KNOWN_EQUITIES and t in NON_INVESTABLE:
                continue

            if _is_options_or_futures_context(clause, t):
                continue
            if _is_ratio_denominator(clause, t):
                continue

            side = _classify_side(clause, t)
            if side not in ("long", "pair_long"):
                continue

            key = (t, side)
            if key in seen:
                continue
            seen.add(key)
            out.append(TickerMention(
                ticker=t,
                side=side,
                is_long_equity=True,
                reason="long-side equity/ETF mention",
            ))
    return out


# ----------------------------------------------------------------------------
# Grading rubric
# ----------------------------------------------------------------------------

@dataclass
class Grade:
    specificity: int          # 0-5
    catalyst: int             # 0-5
    risk: int                 # 0-5
    cohesion: int             # 0-5
    total: int                # 0-20
    letter: str               # A / A- / B / C / D / F
    long_tickers: list[str] = field(default_factory=list)


def _letter(total: int) -> str:
    if total >= 18: return "A"
    if total >= 16: return "A-"
    if total >= 13: return "B"
    if total >= 10: return "C"
    if total >= 7:  return "D"
    return "F"


def _score_specificity(text: str, n_tickers: int) -> int:
    score = 0
    if n_tickers >= 1:                                  score += 2
    if n_tickers >= 3:                                  score += 1
    if re.search(r'\b\d+\s*-?\s*month', text, re.I):    score += 1
    if re.search(r'\b\d+\s*%', text):                   score += 1
    if re.search(r'\b\d+\s*DTE\b', text):               score += 1
    return min(score, 5)


def _score_catalyst(text: str, catalysts_json: str | None) -> int:
    score = 0
    cats = []
    if catalysts_json:
        try:
            parsed = json.loads(catalysts_json)
            if isinstance(parsed, list):
                cats = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    score += min(len(cats), 3)
    low = text.lower()
    if any(w in low for w in
           ("regime", "earnings", "fed", "fomc", "election", "war", "supply", "demand")):
        score += 1
    if "given" in low and "regime" in low:
        score += 1
    return min(score, 5)


def _score_risk(text: str) -> int:
    low = text.lower()
    score = 0
    if "stop" in low:                                                     score += 2
    if "hedge" in low or "vs short" in low or "pair" in low:              score += 1
    if re.search(r'\b\d+%\s*(stop|allocation|portfolio|position|risk)', low): score += 1
    if "size" in low or "sizing" in low or "horizon" in low:              score += 1
    return min(score, 5)


def _score_cohesion(text: str) -> int:
    """Heuristic: fewer but well-related clauses = higher cohesion."""
    clauses = _split_clauses(text)
    n = len(clauses)
    if n == 0: return 1
    if n <= 2: return 5
    if n == 3: return 4
    if n == 4: return 3
    if n == 5: return 2
    return 1


def grade(hypothesis: str,
          catalysts_json: str | None = None,
          conviction_adjustment: str | None = None) -> Grade:
    """Apply the 0-20 rubric to a single hypothesis."""
    longs = extract_long_tickers(hypothesis)
    long_tickers = [t.ticker for t in longs]

    sp = _score_specificity(hypothesis, len(long_tickers))
    ca = _score_catalyst(hypothesis, catalysts_json)
    ri = _score_risk(hypothesis)
    co = _score_cohesion(hypothesis)

    total = sp + ca + ri + co
    return Grade(
        specificity=sp, catalyst=ca, risk=ri, cohesion=co,
        total=total, letter=_letter(total),
        long_tickers=long_tickers,
    )


# ----------------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------------

SELF_TEST_HYPOTHESES = [
    "Long CNY volatility, tactical short China tech (KWEB), hedge with long Taiwan semis (TSM), small position size given regime",
    "Long crude oil volatility (OVX calls), tactical long USO/BNO with tight stops, hedge with short SPY puts",
    "Long defense primes basket (LMT, RTX, NOC, GD), overweight European defense (DFEN ETF), duration 6-12 months",
    "Short GOOGL/MSFT pair trade, long semiconductor picks-and-shovels (NVDA, AMD), reduce exposure to closed-model pure-plays",
    "Long AI infrastructure plays (NVDA, MSFT), long Anthropic-related stocks if available, pair trade long AI software vs traditional financial services",
    "Long Chinese satellite/aerospace ETF (ARKX exposure to Chinese ADRs), short legacy US defense primes (LMT, NOC) on relative basis, long semiconductor capital equipment (ASML, KLAC)",
    "Long crude oil (WTI/Brent futures), long XLE energy sector ETF, hedge with OTM SPY puts. Scale position size to 0.7x normal given high volatility regime.",
    "Long dated Brent crude calls ($85-90 strike, 60-90 DTE), long USO shares with 8% trailing stop, short XLE covered calls to finance premium",
    "Long defense prime basket (LMT, RTX, NOC, LHX) with 6-month horizon, overweight munitions exposure",
    "Long GLD/TLT ratio, tactical short 10Y Treasury futures, overweight gold miners (GDX)",
    "Long GOOGL vs short META pairs trade, long PLTR on defense AI contracts, avoid pure-play AI infrastructure",
    "Long HACK ETF or basket of CRWD/PANW/FTNT 7% position; pair with short CIBR to isolate alpha from beta",
    "Long high-switching-cost enterprise software (CRM, ADBE, MSFT) via 2x leveraged position, funded by shorting recent AI IPOs/SPACs. 12% portfolio allocation with sector rotation within tech.",
    "Long hyperscaler debt (MSFT/GOOGL bonds), short legacy enterprise software (ORCL equity), long datacenter REITs (DLR, EQIX)",
    "Long LMT, RTX, and NOC equal-weight basket with 12% position size, 3-month time horizon, 15% stop loss on portfolio basis",
    "Long META calls (ATM, 45 DTE) and long GOOGL shares, avoid or short AI pure-plays without defense contracts. 5% portfolio allocation with tight 10% stops.",
    "Long MSFT/GOOGL (AI infrastructure winners), short ORCL, short commercial real estate (VNO) on WFH acceleration. 0.6x size in CHOPPY regime.",
]


def _self_test():
    print("=" * 72)
    print("RedHood Grader - self-test on 17 representative hypotheses")
    print("=" * 72)
    for i, h in enumerate(SELF_TEST_HYPOTHESES, 1):
        g = grade(h)
        print(f"\n[{i:2}] {g.letter}  (spec={g.specificity} cat={g.catalyst} "
              f"risk={g.risk} coh={g.cohesion}  tot={g.total}/20)")
        print(f"     long: {g.long_tickers if g.long_tickers else '(none equity)'}")
        print(f"     hyp:  {h[:88]}{'...' if len(h) > 88 else ''}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RedHood hypothesis grader & ticker extractor")
    parser.add_argument("--self-test", action="store_true", help="Run grader against bundled hypotheses")
    parser.add_argument("--hypothesis", help="Grade a single hypothesis string")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
    elif args.hypothesis:
        g = grade(args.hypothesis)
        print(json.dumps(asdict(g), indent=2))
    else:
        parser.print_help()
