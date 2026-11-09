"""
RedHood Systems - Ticker Extraction
=====================================
Extracts ticker symbols (and Long/Short/Hedge/Pair side) from a narrative's
free-text hypothesis. Closes audit gaps G1 (no ticker dimension) and G2 (no
long/short side attribute).

Approach
--------
Walk the hypothesis left-to-right, maintaining a "current side" state that
updates whenever a side keyword appears (long/short/hedge/calls/puts/pair).
When we hit a ticker token (bare uppercase, parenthesised group, or
slash-pair), assign it the current side. Strong boundaries (semicolons,
sentence ends) reset state to None; commas do NOT reset, so
"long X (A, B, C)" propagates Long across all of A/B/C.

Right-side overrides:
    "X puts"  -> Short  (forces a flip even if Long was current)
    "X calls" -> Long   (rarely flips, but explicit)

Output: list of {ticker, side, pattern} dicts, deduped by (ticker, side).
"""

from __future__ import annotations

import re
from typing import List, Dict, Set, Tuple


# ---------------------------------------------------------------------------
# Token rules
# ---------------------------------------------------------------------------

# 1–5 char uppercase symbols. A dotted tail of 1–2 chars is kept when it
# is a real exchange or share-class suffix (CPX.TO, BRK.B) - see
# _normalize_token, which validates it against _VALID_SUFFIXES.
_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")

# Paren groups: capture body so we can split it.
_PAREN_RE = re.compile(r"\(([^()]*)\)")

# Side keywords (longer phrases first; matched as whole words / phrases).
_SIDE_RULES: List[Tuple[str, str]] = [
    # (regex pattern, side label)
    (r"\bpair[- ]trade\b",         "Pair"),
    (r"\bhedge with\b",            "Hedge"),
    (r"\bhedge via\b",             "Hedge"),
    (r"\btail[- ]risk hedge\b",    "Hedge"),
    (r"\bunderweight\b",           "Short"),
    (r"\boverweight\b",            "Long"),
    (r"\brotation into\b",         "Long"),
    (r"\brotation out of\b",       "Short"),
    (r"\btactical long\b",         "Long"),
    (r"\btactical short\b",        "Short"),
    (r"\bbullish\b",               "Long"),
    (r"\bbearish\b",               "Short"),
    (r"\bshort\b",                 "Short"),
    (r"\blong\b",                  "Long"),
    (r"\bbuy\b",                   "Long"),
    (r"\bsell\b",                  "Short"),
]

# Right-side overrides (regex matched at position immediately after ticker).
_RIGHT_PUT  = re.compile(r"\s*puts?\b", re.I)
_RIGHT_CALL = re.compile(r"\s*calls?\b", re.I)

# Boundary characters that reset side state.
_RESET_RE = re.compile(r"[;.!?]|\bvs\.?\b", re.I)

# Stopword set — uppercase tokens that look like tickers but aren't.
_STOPWORDS: Set[str] = {
    # Currencies / fiat
    "US", "USD", "EUR", "GBP", "JPY", "CNY", "CAD", "AUD", "NZD", "CHF",
    "BRL", "MXN", "INR", "RUB", "ZAR", "TRY", "KRW", "SEK", "NOK", "DKK",
    "PLN", "HKD", "SGD", "TWD", "THB",
    # Common acronyms / verbs / connectives
    "ETF", "ETFS", "ETFs", "AI", "AM", "PM", "API", "CEO", "CFO",
    "FOMC", "FED", "ECB", "BOJ", "BOE", "PBOC",
    "GDP", "CPI", "PCE", "PMI", "PPI", "ISM", "NFP", "JOLTS",
    "EPS", "PE", "QE", "QT", "OTM", "ITM",
    "DOJ", "DOD", "DHS", "FBI", "CIA", "EU", "UK", "UN", "OPEC", "NATO",
    "IPO", "MM", "BB", "AAA", "BBB", "TIPS",
    "OK", "ON", "IT", "IS", "BE", "OR", "AS", "AT", "AN",
    "BY", "DO", "GO", "HE", "IF", "IN", "ME", "MY", "OF", "SO",
    "TO", "UP", "WE", "I", "A", "ALL", "NEW", "OLD", "TOP",
    "VS", "VIA", "PER", "OUT", "OFF", "ETC",
    "Q", "QTR", "FY",
    "THE", "AND", "FOR", "WITH", "THAT", "THIS", "FROM", "INTO",
    "EACH", "OVER", "UNDER", "TARGET", "SIZE", "SIZED", "BAND",
    "TREND", "RISK", "BEAR", "BULL", "CALL", "PUT", "OPEX",
    # Roman numerals
    "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
    # Misc false-positives in our corpus
    "DOT", "DOTS", "ML", "DM", "EM", "EMS", "G", "G7", "G20",
    "DC", "LA", "NY", "NYC", "USA", "OEM", "OEMS",
    "POTUS", "FLOTUS", "SCOTUS", "RFK", "JFK", "FDR", "MAGA",
    "AC", "WW", "WWI", "WWII", "WWIII",
    "CAPEX",
    "NO",
}
# Real symbols that pattern-match a stopword regex; never drop these.
_FORCE_KEEP = {"DXY", "GLD", "SLV", "VIX", "SPY", "DIA", "IWM", "QQQ",
               "TLT", "TLTS", "EEM", "XLE", "XLF", "XLK", "XLI", "XLY",
               "XLP", "XLV", "XLU", "XLB", "XLRE", "XLC", "DBC"}

# Tokens that are never a listed symbol in any market context: macro releases
# and surveys, sovereign-bond shorthands, hardware / AI acronyms, central
# banks and agencies, rates jargon, regions, reporting shorthand. Shared with
# redhood_grader (NON_INVESTABLE) so the star schema and the $2,500 long-only
# ledger reject the same tokens. Run 53 (2026-10-26) stored GPU, IFO and OAT
# as tickers, and GPU as a long equity, from "SpaceX GPU buys", "IFO
# expectations beat" and "French OAT exposure".
# Keep real symbols OUT of this set: ADP, RBA, HBM, IOT, AGI, LNG, CAT, TAN,
# GCC, UAE and GULF read like acronyms but are listed names.
NON_TICKER_TOKENS: frozenset = frozenset({
    # Macro releases / surveys
    "IFO", "ZEW", "HICP", "NAHB", "NFIB", "PMIS",
    # Sovereign bonds / rates jargon (OAT = French government bond)
    "OAT", "OATS", "BUND", "BUNDS", "BTP", "BTPS", "GILT", "GILTS", "JGB", "JGBS",
    "UST", "USTS", "SOFR", "LIBOR", "OIS", "CDS", "FX", "YCC", "BPS",
    # Hardware / AI acronyms
    "GPU", "GPUS", "CPU", "CPUS", "TPU", "TPUS", "NPU", "ASIC", "ASICS",
    "LLM", "LLMS", "GPT", "DRAM", "NAND", "HPC", "EV",
    # Central banks / agencies / bodies
    "ECB", "BOJ", "BOE", "PBOC", "RBNZ", "SNB", "BOC", "BOK", "RBI",
    "IMF", "WTO", "BIS", "SEC", "FTC", "FDA", "EPA", "DOE", "IEA", "EIA",
    "DNI", "CBO", "OMB", "BLS", "BEA", "DOJ", "DOD", "DHS",
    # Regions / blocs
    "APAC", "EMEA", "LATAM", "MENA", "DACH",
    # Valuation / reporting shorthand
    "EPS", "DCF", "ROE", "ROIC", "AUM", "NAV", "YOY", "QOQ", "YTD", "CAPEX",
})
_STOPWORDS |= NON_TICKER_TOKENS

# Symbols that no longer trade under that name. A hypothesis may still use
# them, but the ledger cannot price them, so redhood_grader treats them as
# non-investable. The star schema keeps the historical mention, so they are
# deliberately NOT stopwords here.
RETIRED_SYMBOLS: frozenset = frozenset({
    "RTN",   # Raytheon -> RTX (Apr 2020)
    "FB",    # Facebook -> META (Jun 2022)
    "TWTR",  # Twitter, taken private (Oct 2022)
    "RSX",   # VanEck Russia ETF, liquidated (2023)
    "TELL",  # Tellurian, acquired by Woodside (Oct 2024)
    "SQ",    # Block -> XYZ (Jan 2025)
})


# Exchange suffixes Yahoo Finance uses for non-US listings. A hypothesis that
# says "CPX.TO" means Capital Power on the TSX, and the bare base ("CPX") does
# not price on Yahoo - run 58 (2026-11-09) warned on CPX for exactly this
# reason, because the old 1-char suffix rule truncated ".TO" to nothing.
_EXCHANGE_SUFFIXES: frozenset = frozenset({
    # Canada
    "TO", "V", "NE", "CN",
    # UK / Europe
    "L", "DE", "F", "PA", "AS", "BR", "MC", "MI", "LS", "VI", "SW",
    "ST", "OL", "CO", "HE", "IR", "WA", "PR", "AT", "IS",
    # Asia-Pacific
    "HK", "SS", "SZ", "TW", "KS", "KQ", "T", "SI", "JK", "BK",
    "NS", "BO", "AX", "NZ",
    # Americas / EMEA ex-US
    "SA", "MX", "TA", "JO", "BD",
})

# Share-class and unit suffixes on US listings (BRK.B, and warrant/unit tails).
_CLASS_SUFFIXES: frozenset = frozenset({"A", "B", "C", "U", "WS", "RT", "WT"})

_VALID_SUFFIXES: frozenset = _EXCHANGE_SUFFIXES | _CLASS_SUFFIXES


LONG, SHORT, HEDGE, PAIR = "Long", "Short", "Hedge", "Pair"


# ---------------------------------------------------------------------------
# Side keyword tagger
# ---------------------------------------------------------------------------

def _find_side_events(text: str) -> List[Tuple[int, str]]:
    """Return [(position, side)] for every side keyword in text."""
    events: List[Tuple[int, str]] = []
    for pattern, side in _SIDE_RULES:
        for m in re.finditer(pattern, text, re.I):
            events.append((m.start(), side))
    events.sort(key=lambda e: e[0])
    return events


def _find_reset_positions(text: str) -> List[int]:
    """Return positions where current-side state should reset.

    A dot wedged between two alphanumerics belongs to a token - an exchange
    suffix ("CPX.TO", "9988.HK") or an abbreviation ("U.S") - not to a
    sentence boundary, so it does not reset. Without this, the dot in
    "Short CPX.TO or AQN" stranded AQN on default_long.
    """
    out: List[int] = []
    for m in _RESET_RE.finditer(text):
        pos = m.start()
        if text[pos] == "." and 0 < pos < len(text) - 1:
            if text[pos - 1].isalnum() and text[pos + 1].isalnum():
                continue
        out.append(pos)
    return out


def _side_at(pos: int,
             events: List[Tuple[int, str]],
             resets: List[int]) -> Tuple[str, str]:
    """Resolve the active side at character position `pos`.

    Most recent side keyword before pos wins, unless a reset boundary
    (semicolon, period, ' vs ') sits between the keyword and pos.
    Returns (side, pattern_label).
    """
    candidate: Tuple[int, str] | None = None
    for ev_pos, side in events:
        if ev_pos >= pos:
            break
        # Check for reset between ev_pos and pos
        crossed = any(ev_pos < r < pos for r in resets)
        if crossed:
            continue
        candidate = (ev_pos, side)
    if candidate is None:
        return LONG, "default_long"
    return candidate[1], f"left_keyword@{candidate[0]}"


# ---------------------------------------------------------------------------
# Ticker token scanner
# ---------------------------------------------------------------------------

def _normalize_token(tok: str) -> str | None:
    """Canonical ticker for a raw token, or None when it is not a ticker.

    Keeps a valid exchange/class suffix attached ("CPX.TO", "BRK.B") so the
    symbol stays priceable, and strips punctuation the scanners may capture
    ("AQN." -> "AQN"). Returns None for stopwords and for dotted tokens whose
    suffix is not a real exchange or share class ("U.S", "P.E").
    """
    if not tok:
        return None
    upper = tok.upper().strip().strip(".")
    if not upper or not upper[0].isalpha():
        return None

    if "." in upper:
        base, _, suffix = upper.partition(".")
        if "." in suffix:
            return None
        if not (2 <= len(base) <= 5) or not base.isalpha():
            return None
        if suffix not in _VALID_SUFFIXES:
            return None
        if base in _STOPWORDS and base not in _FORCE_KEEP:
            return None
        return f"{base}.{suffix}"

    if upper in _FORCE_KEEP:
        return upper
    if upper in _STOPWORDS:
        return None
    # Single letters are almost always false-positive (sentence "I", etc.)
    if len(upper) == 1:
        return None
    return upper


def _is_ticker_token(tok: str) -> bool:
    return _normalize_token(tok) is not None


def _scan_paren_tickers(text: str) -> List[Tuple[str, int, int]]:
    """Yield (ticker, abs_start, abs_end) for tokens inside () groups."""
    out: List[Tuple[str, int, int]] = []
    for m in _PAREN_RE.finditer(text):
        body = m.group(1)
        body_start = m.start(1)
        # Split on comma/slash/space
        for piece_match in re.finditer(r"[A-Z][A-Z0-9.]*", body):
            tok = piece_match.group(0)
            norm = _normalize_token(tok)
            if norm is not None:
                out.append((
                    norm,
                    body_start + piece_match.start(),
                    body_start + piece_match.end(),
                ))
    return out


def _scan_bare_tickers(text: str) -> List[Tuple[str, int, int]]:
    """Yield (ticker, start, end) for bare uppercase tokens NOT inside parens."""
    # Mask paren contents so we don't double-count.
    mask = list(text)
    for m in _PAREN_RE.finditer(text):
        for i in range(m.start(), m.end()):
            mask[i] = " "
    masked = "".join(mask)

    out: List[Tuple[str, int, int]] = []
    for m in _TICKER_RE.finditer(masked):
        tok = m.group(1)
        norm = _normalize_token(tok)
        if norm is not None:
            out.append((norm, m.start(1), m.end(1)))
    return out


# ---------------------------------------------------------------------------
# Right-side override
# ---------------------------------------------------------------------------

def _right_override(text: str, end: int) -> Tuple[str, str] | None:
    snippet = text[end:end + 30]
    if _RIGHT_PUT.match(snippet):
        return SHORT, "right_puts"
    if _RIGHT_CALL.match(snippet):
        return LONG, "right_calls"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_tickers(text: str) -> List[Dict[str, str]]:
    """Return deduplicated [{ticker, side, pattern}] for `text`."""
    if not text:
        return []

    events = _find_side_events(text)
    resets = _find_reset_positions(text)

    candidates: List[Tuple[str, int, int]] = []
    candidates.extend(_scan_paren_tickers(text))
    candidates.extend(_scan_bare_tickers(text))

    seen: Dict[Tuple[str, str], Dict[str, str]] = {}
    for ticker, start, end in candidates:
        side, pattern = _side_at(start, events, resets)
        override = _right_override(text, end)
        if override is not None:
            side, pattern = override
        key = (ticker, side)
        if key not in seen:
            seen[key] = {"ticker": ticker, "side": side, "pattern": pattern}

    return list(seen.values())


# ---------------------------------------------------------------------------
# Derived-column helpers — single source of truth for catalyst_count,
# conviction_size, entropy_band so aggregator + backfill stay in sync.
# ---------------------------------------------------------------------------

def entropy_band(entropy_risk: int | None) -> str | None:
    """1–3 -> low, 4–7 -> mid, 8–10 -> high. None -> None."""
    if entropy_risk is None:
        return None
    if entropy_risk <= 3:
        return "low"
    if entropy_risk <= 7:
        return "mid"
    return "high"


_CONVICTION_MAP = {
    "full size":    1.00,
    "full":         1.00,
    "half size":    0.50,
    "half":         0.50,
    "quarter size": 0.25,
    "quarter":      0.25,
    "pass":         0.00,
}


def conviction_size(conviction_adjustment: str | None) -> float | None:
    if not conviction_adjustment:
        return None
    head = conviction_adjustment.strip().lower()
    for label, size in _CONVICTION_MAP.items():
        if head.startswith(label):
            return size
    return None


def catalyst_count(catalysts_json: str | None) -> int:
    if not catalysts_json:
        return 0
    import json
    try:
        parsed = json.loads(catalysts_json)
        return len(parsed) if isinstance(parsed, list) else 0
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Long VIX calls (30-day), long defense contractors (LMT, RTX, NOC), short crude oil via UCO puts on spike above $85",
        "Long NVDA/AMD, pair trade long XLK/short XLF (tech vs financials)",
        "Long PYPL calls (60-day expiry, 5-10% OTM), pair trade long PYPL vs short SQ (Block)",
        "Short EUR/USD via 3-month put options, long US defense contractors (LMT, RTX), hedge with long gold (GLD)",
        "Long Dell (beneficiary of efficiency pivot per +22% move), short hyperscaler capex plays (GOOGL, MSFT)",
        "Long gold (GLD), long Bitcoin (GBTC/IBIT), long non-USD currencies basket (UUP inverse)",
        "Short AI infrastructure (NVDA, AMD, SMCI) via put spreads; long legacy defense contractors (LMT, RTX)",
    ]
    for s in samples:
        print("\n>>", s)
        for row in extract_tickers(s):
            print(f"   {row['ticker']:<6} {row['side']:<6} ({row['pattern']})")
