"""
RedHood Systems - Terminal
===========================
Builds the RedHood Terminal: a dense, keyboard-driven, multi-panel market
terminal over everything in redhood.db.

Two shapes, one data layer:

  1. STATIC  - `--html` bakes the bundle into a single self-contained
               docs/terminal.html (no server, no CDN, offline-capable,
               publishes to GitHub Pages like timeline.html / cards.html).
  2. LIVE    - `--serve` runs a local HTTP server exposing the same bundle at
               /api/bundle plus /api/quotes for polled quotes, and serves the
               page with the bundle fetched instead of baked. The front end
               uses one adapter for both, so the page is identical either way.

Usage:
    python redhood_terminal.py --html                 # write docs/terminal.html
    python redhood_terminal.py --html --open          # ...and open it
    python redhood_terminal.py --serve                # live mode on :8787
    python redhood_terminal.py --json out.json        # just the data bundle
    python redhood_terminal.py --stats                # what's in the bundle
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'redhood.db')
DOCS_DIR = os.path.join(HERE, 'docs')
SRC_DIR = os.path.join(HERE, 'assets', 'terminal')

# Files concatenated into the single-file page, in order.
CSS_FILES = ['terminal.css']
JS_FILES = ['util.js', 'chart.js', 'panels.js', 'app.js']

EPOCH = date(1970, 1, 1)
DEFAULT_BARS = 520          # ~2y of trading days per symbol
TAPE_LIMIT = 500
VERSION = '1.0'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _day(iso: str) -> int | None:
    """'YYYY-MM-DD' -> integer days since 1970-01-01 (compact x-axis)."""
    try:
        y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10])
        return (date(y, m, d) - EPOCH).days
    except (ValueError, TypeError, IndexError):
        return None


def _r(v, nd: int = 4):
    """Round for transport; keep None as None so the UI can gap a series."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:                                      # NaN
        return None
    return round(f, nd)


def _jloads(raw, fallback):
    if not raw:
        return fallback
    try:
        v = json.loads(raw)
        return v if isinstance(v, type(fallback)) else fallback
    except (json.JSONDecodeError, TypeError):
        return fallback


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# price series
# ---------------------------------------------------------------------------

def _rp(v):
    """Adaptive price rounding: 2dp above a dollar, 4-6dp below.

    Writing 123.45 instead of 123.4500 over 93k bars x 4 fields is most of the
    difference between a 4.5 MB page and a 2 MB one.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    a = abs(f)
    if a >= 1:
        return round(f, 2)
    if a >= 0.01:
        return round(f, 4)
    return round(f, 6)


def build_series(conn: sqlite3.Connection, max_bars: int = DEFAULT_BARS) -> dict:
    """{TICKER: {d0, d, o, h, l, c, v, ohlc}} - arrays aligned by index.

    Wire format, decoded by getSeries() in util.js:
      * `d0` is the first bar's day (days since epoch) and `d` holds the gaps
        to each following bar, so a weekday series is a run of 1s and 3s.
      * `o/h/l` are omitted for close-only symbols (ohlc=0); the chart draws
        those as a line instead of candles.
      * `v` is volume in thousands.
    """
    out: dict[str, dict] = {}
    rows = conn.execute("""
        SELECT ticker, price_date, open, high, low, close, volume
        FROM prices
        WHERE close IS NOT NULL
        ORDER BY ticker, price_date
    """).fetchall()

    by_ticker: dict[str, list] = {}
    for r in rows:
        by_ticker.setdefault(r['ticker'], []).append(r)

    for ticker, bars in by_ticker.items():
        bars = bars[-max_bars:]
        has_ohlc = sum(1 for b in bars if b['open'] is not None) > len(bars) * 0.5
        has_vol = any(b['volume'] for b in bars)

        days, o, h, lo, c, v = [], [], [], [], [], []
        for b in bars:
            day = _day(b['price_date'])
            if day is None:
                continue
            days.append(day)
            c.append(_rp(b['close']))
            if has_ohlc:
                o.append(_rp(b['open']))
                h.append(_rp(b['high']))
                lo.append(_rp(b['low']))
            if has_vol:
                v.append(round((b['volume'] or 0) / 1000))

        if not days:
            continue
        s: dict = {
            'd0': days[0],
            'd': [days[i] - days[i - 1] for i in range(1, len(days))],
            'c': c,
            'ohlc': 1 if has_ohlc else 0,
        }
        if has_ohlc:
            s.update(o=o, h=h, l=lo)
        if has_vol:
            s['v'] = v
        out[ticker] = s
    return out


def _days(series: dict) -> list[int]:
    """Rebuild absolute day numbers from the delta-encoded wire format."""
    days = [series['d0']]
    for gap in series.get('d', []):
        days.append(days[-1] + gap)
    return days


def _chg(series: dict, back: int) -> float | None:
    """Simple return over `back` bars, as a decimal."""
    c = series.get('c') or []
    if len(c) <= back or c[-1] is None:
        return None
    prev = c[-1 - back]
    if not prev:
        return None
    return (c[-1] / prev) - 1.0


def _stdev_ann(series: dict, window: int = 20) -> float | None:
    c = [x for x in (series.get('c') or [])[-(window + 1):] if x]
    if len(c) < 5:
        return None
    rets = [(c[i] / c[i - 1]) - 1 for i in range(1, len(c)) if c[i - 1]]
    if len(rets) < 4:
        return None
    try:
        return statistics.stdev(rets) * (252 ** 0.5)
    except statistics.StatisticsError:
        return None


def build_symbols(conn: sqlite3.Connection, series: dict) -> list[dict]:
    """One row per symbol for the monitor: last, changes, vol, provenance."""
    meta = {r['ticker']: dict(r) for r in conn.execute("SELECT * FROM tickers")}
    watch = {r['symbol']: dict(r) for r in conn.execute(
        "SELECT * FROM watchlist WHERE active = 1")}
    nar_count: dict[str, int] = {}
    for r in conn.execute("""
        SELECT ticker, COUNT(DISTINCT narrative_id) n FROM narrative_tickers GROUP BY ticker
    """):
        nar_count[r['ticker']] = r['n']

    out = []
    for ticker, s in series.items():
        c = s['c']
        days = _days(s)
        w = watch.get(ticker)
        m = meta.get(ticker, {})
        out.append({
            't': ticker,
            'name': m.get('company_name') or '',
            'cls': (w or {}).get('asset_class') or m.get('asset_class') or '',
            'sector': m.get('sector') or '',
            'section': (w or {}).get('section') or '',
            'wl': 1 if w else 0,
            'last': c[-1],
            'd1': _r(_chg(s, 1), 6),
            'd5': _r(_chg(s, 5), 6),
            'd20': _r(_chg(s, 20), 6),
            'd60': _r(_chg(s, 60), 6),
            'ytd': _r(_ytd(s, days), 6),
            'vol20': _r(_stdev_ann(s), 4),
            'hi': _rp(max((x for x in c if x), default=None)),
            'lo': _rp(min((x for x in c if x), default=None)),
            'n': len(c),
            'ohlc': s['ohlc'],
            'nar': nar_count.get(ticker, 0),
            'from': (EPOCH.fromordinal(EPOCH.toordinal() + days[0])).isoformat(),
            'to': (EPOCH.fromordinal(EPOCH.toordinal() + days[-1])).isoformat(),
        })
    out.sort(key=lambda r: (-r['wl'], -r['nar'], r['t']))
    return out


def _ytd(series: dict, days: list[int] | None = None) -> float | None:
    d = days if days is not None else _days(series)
    c = series.get('c') or []
    if not d:
        return None
    jan1 = (date(EPOCH.fromordinal(EPOCH.toordinal() + d[-1]).year, 1, 1) - EPOCH).days
    base = None
    for i, day in enumerate(d):
        if day >= jan1:
            base = c[i - 1] if i > 0 else c[i]
            break
    if not base or not c[-1]:
        return None
    return (c[-1] / base) - 1.0


# ---------------------------------------------------------------------------
# narratives
# ---------------------------------------------------------------------------

def build_narratives(conn: sqlite3.Connection) -> list[dict]:
    grades = {r['narrative_id']: dict(r) for r in conn.execute(
        "SELECT * FROM narrative_grades")}

    tickers: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM narrative_tickers ORDER BY narrative_id, ticker"):
        tickers.setdefault(r['narrative_id'], []).append({
            't': r['ticker'], 'side': r['side'],
            'w': _r(r['weight_in_hypothesis'], 3),
            'lng': r['is_long_equity'],
        })

    returns: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM narrative_returns"):
        returns.setdefault(r['narrative_id'], []).append({
            't': r['ticker'], 'entry': r['entry_date'], 'px': _r(r['entry_close']),
            'h5': _r(r['h5'], 6), 'h20': _r(r['h20'], 6), 'h60': _r(r['h60'], 6),
            'td': _r(r['todate'], 6),
            'sh5': _r(r['spy_h5'], 6), 'sh20': _r(r['spy_h20'], 6),
            'sh60': _r(r['spy_h60'], 6), 'std': _r(r['spy_todate'], 6),
            'last': r['last_date'],
        })

    feed_counts: dict[str, int] = {}
    for r in conn.execute("""
        SELECT narrative_id, COUNT(*) n FROM narrative_feeds GROUP BY narrative_id
    """):
        feed_counts[r['narrative_id']] = r['n']

    out = []
    for r in conn.execute("SELECT * FROM narratives ORDER BY created_at DESC"):
        g = grades.get(r['id'])
        out.append({
            'id': r['id'],
            'run': r['run_id'],
            'title': r['title'],
            'at': r['created_at'],
            'ent': r['entropy_risk'],
            'band': r['entropy_band'] or '',
            'conv': _r(r['conviction_size'], 4),
            'adj': r['conviction_adjustment'] or '',
            'hyp': r['hypothesis'],
            'why': r['rationale'],
            'bear': r['bear_case'] or '',
            'cat': _jloads(r['catalysts'], []),
            'dis': _jloads(r['disconfirming_signals'], []),
            'prior': r['prior_mentions'],
            'cont': r['continuation_of'],
            'feeds': feed_counts.get(r['id'], 0),
            'g': ({'ltr': g['letter_grade'], 'tot': g['total_score'],
                   'spec': g['specificity'], 'cat': g['catalyst_score'],
                   'risk': g['risk_score'], 'coh': g['cohesion']} if g else None),
            'tk': tickers.get(r['id'], []),
            'ret': returns.get(r['id'], []),
        })
    return out


# ---------------------------------------------------------------------------
# regime / runs / tape / notes
# ---------------------------------------------------------------------------

def build_regime(conn: sqlite3.Connection) -> list[dict]:
    return [{
        'id': r['id'], 'run': r['run_id'], 'at': r['computed_at'],
        'sym': r['symbol'], 'asof': r['as_of_date'], 'label': r['label'],
        'temp': _r(r['temperature'], 5), 'S': _r(r['entropy'], 5),
        'eta': _r(r['eta'], 5), 'Seq': _r(r['entropy_eq'], 5),
        'etaeq': _r(r['eta_eq'], 5), 'Shi': _r(r['entropy_hi'], 5),
        'kl': _r(r['kl_divergence'], 5), 'klt': _r(r['kl_threshold'], 5),
        'heat': _r(r['heat'], 5), 'budget': _r(r['heat_budget'], 5),
        'mult': _r(r['signal_multiplier'], 4), 'warn': r['warning'],
        'ver': r['detector_version'],
    } for r in conn.execute("SELECT * FROM regime_history ORDER BY computed_at")]


def build_runs(conn: sqlite3.Connection) -> list[dict]:
    return [{
        'id': r['id'], 'at': r['run_at'], 'hours': _r(r['hours_back'], 2),
        'feeds': r['feeds_collected'], 'nar': r['narratives_extracted'],
    } for r in conn.execute("SELECT * FROM runs ORDER BY id DESC")]


def _trim(text: str | None, n: int = 420) -> str:
    t = (text or '').strip().replace('\r', ' ')
    return t if len(t) <= n else t[:n - 1].rstrip() + '…'


def build_tape(conn: sqlite3.Connection, limit: int = TAPE_LIMIT) -> list[dict]:
    """Newest feed items across every source, newest first.

    That is Substack RSS and Telegram live, plus the closed X record from
    `twitter_archive` for anything the feeds table no longer carries. X itself
    was retired on 2026-11-01, so nothing new arrives on that source.
    """
    out = [{
        'id': r['id'], 'src': r['source'], 'who': r['author'],
        'txt': _trim(r['content']), 'at': r['published_at'], 'url': r['url'],
        'run': r['run_id'],
    } for r in conn.execute(
        "SELECT * FROM feeds ORDER BY published_at DESC LIMIT ?", (limit,))]

    if _table_exists(conn, 'twitter_archive'):
        have = {o['id'] for o in out}
        for r in conn.execute("""
            SELECT * FROM twitter_archive ORDER BY published_at DESC LIMIT ?
        """, (limit,)):
            if r['feed_id'] in have:
                continue
            out.append({
                'id': r['feed_id'], 'src': 'twitter', 'who': r['handle'],
                'txt': _trim(r['content']), 'at': r['published_at'],
                'url': r['url'], 'run': r['run_id'], 'arch': 1,
                'nar': r['narrative_count'],
            })
    out.sort(key=lambda x: x['at'] or '', reverse=True)
    return out[:limit]


def build_notes(conn: sqlite3.Connection) -> list[dict]:
    if not _table_exists(conn, 'analyst_notes'):
        return []
    return [{
        'id': r['id'], 'run': r['run_id'], 'nar': r['narrative_id'],
        'regime': r['regime_id'], 'at': r['created_at'], 'who': r['author'],
        'kind': r['kind'], 'title': r['title'], 'tldr': r['tldr'],
        'body': r['body'], 'verdict': r['alpha_verdict'],
        'score': _r(r['alpha_score'], 3), 'tags': _jloads(r['tags'], []),
    } for r in conn.execute("SELECT * FROM analyst_notes ORDER BY created_at DESC")]


# ---------------------------------------------------------------------------
# alpha analytics (computed here so the page stays dumb and fast)
# ---------------------------------------------------------------------------

def build_alpha(narratives: list[dict]) -> dict:
    """Hit rates and excess returns by horizon, grade and entropy band."""
    horizons = [('h5', 'sh5', '5d'), ('h20', 'sh20', '20d'),
                ('h60', 'sh60', '60d'), ('td', 'std', 'to date')]
    rows = []
    for n in narratives:
        for r in n['ret']:
            for key, skey, label in horizons:
                raw, spy = r.get(key), r.get(skey)
                if raw is None:
                    continue
                rows.append({
                    'h': label, 'nar': n['id'], 'ticker': r['t'],
                    'raw': raw, 'spy': spy,
                    'exc': (raw - spy) if spy is not None else None,
                    'grade': (n['g'] or {}).get('ltr') or 'n/a',
                    'band': n['band'] or 'n/a',
                    'ent': n['ent'],
                    'conv': n['conv'],
                })

    def agg(sel) -> dict | None:
        subset = [r for r in rows if sel(r)]
        if not subset:
            return None
        raw = [r['raw'] for r in subset]
        exc = [r['exc'] for r in subset if r['exc'] is not None]
        return {
            'n': len(subset),
            'raw_mean': _r(sum(raw) / len(raw), 6),
            'raw_med': _r(statistics.median(raw), 6),
            'win': _r(sum(1 for x in raw if x > 0) / len(raw), 4),
            'exc_mean': _r(sum(exc) / len(exc), 6) if exc else None,
            'exc_med': _r(statistics.median(exc), 6) if exc else None,
            'beat': _r(sum(1 for x in exc if x > 0) / len(exc), 4) if exc else None,
            'best': _r(max(raw), 6), 'worst': _r(min(raw), 6),
        }

    labels = [h[2] for h in horizons]
    by_h = {lb: agg(lambda r, lb=lb: r['h'] == lb) for lb in labels}
    by_grade = {}
    for g in sorted({r['grade'] for r in rows}):
        by_grade[g] = {lb: agg(lambda r, g=g, lb=lb: r['grade'] == g and r['h'] == lb)
                       for lb in labels}
    by_band = {}
    for b in sorted({r['band'] for r in rows}):
        by_band[b] = {lb: agg(lambda r, b=b, lb=lb: r['band'] == b and r['h'] == lb)
                      for lb in labels}

    scatter = [{'x': r['ent'], 'y': r['exc'], 'g': r['grade'], 't': r['ticker'],
                'nar': r['nar']}
               for r in rows if r['h'] == '20d' and r['exc'] is not None]

    best = sorted([r for r in rows if r['h'] == 'to date' and r['exc'] is not None],
                  key=lambda r: r['exc'], reverse=True)
    # Split the list rather than taking two 12-long slices off either end:
    # under 24 rows those overlap, and the same narrative would be reported as
    # both the best and the worst performer.
    cut = min(12, (len(best) + 1) // 2)

    def _row(r: dict) -> dict:
        return {'t': r['ticker'], 'nar': r['nar'], 'exc': _r(r['exc'], 6),
                'raw': _r(r['raw'], 6), 'g': r['grade']}

    return {
        'horizons': labels,
        'by_horizon': by_h,
        'by_grade': by_grade,
        'by_band': by_band,
        'scatter': scatter,
        'leaders': [_row(r) for r in best[:cut]],
        'laggards': [_row(r) for r in best[cut:][::-1][:12]],
    }


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------

def build_bundle(conn: sqlite3.Connection, max_bars: int = DEFAULT_BARS,
                 tape_limit: int = TAPE_LIMIT) -> dict:
    series = build_series(conn, max_bars)
    narratives = build_narratives(conn)
    symbols = build_symbols(conn, series)
    regime = build_regime(conn)
    runs = build_runs(conn)

    ohlc_n = sum(1 for s in symbols if s['ohlc'])
    meta = {
        'version': VERSION,
        'built_at': _now_iso(),
        'epoch': EPOCH.isoformat(),
        'mode': 'static',
        'counts': {
            'symbols': len(symbols), 'with_ohlc': ohlc_n,
            'bars': sum(len(s['c']) for s in series.values()),
            'narratives': len(narratives), 'runs': len(runs),
            'regime': len(regime),
        },
        'latest_run': runs[0] if runs else None,
        'regime_now': regime[-1] if regime else None,
        'as_of': max((s['to'] for s in symbols), default=None),
    }
    return {
        'meta': meta,
        'symbols': symbols,
        'series': series,
        'narratives': narratives,
        'regime': regime,
        'runs': runs,
        'tape': build_tape(conn, tape_limit),
        'notes': build_notes(conn),
        'alpha': build_alpha(narratives),
    }


# ---------------------------------------------------------------------------
# embeddable preview
# ---------------------------------------------------------------------------

def build_preview(conn: sqlite3.Connection, n_symbols: int = 6,
                  spark_bars: int = 60) -> dict:
    """A small snapshot for embedding in another page (the RedHood Reads report).

    Deliberately tiny — a few KB — so the report stays fast. The full terminal
    is a link away; this is the window into it.
    """
    series = build_series(conn, max_bars=spark_bars + 5)
    symbols = build_symbols(conn, series)
    regime = build_regime(conn)
    narratives = build_narratives(conn)
    alpha = build_alpha(narratives)

    picks = [s for s in symbols if s['wl']][:n_symbols]
    if len(picks) < n_symbols:
        seen = {s['t'] for s in picks}
        picks += [s for s in symbols if s['t'] not in seen][:n_symbols - len(picks)]

    tiles = []
    for s in picks:
        spark = [c for c in (series.get(s['t'], {}).get('c') or [])[-spark_bars:] if c is not None]
        tiles.append({'t': s['t'], 'last': s['last'], 'd1': s['d1'],
                      'd20': s['d20'], 'spark': spark})

    top = []
    for n in narratives[:3]:
        top.append({'title': n['title'], 'g': (n['g'] or {}).get('ltr'),
                    'ent': n['ent'], 'at': (n['at'] or '')[:10],
                    'tk': [t['t'] for t in n['tk'][:3]]})

    td = alpha['by_horizon'].get('to date') or {}
    return {
        'built_at': _now_iso(),
        'as_of': max((s['to'] for s in symbols), default=None),
        'counts': {
            'symbols': len(symbols),
            'narratives': len(narratives),
            'runs': conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            # straight from SQL: rebuilding every series just to count them
            # would double the work of the whole preview
            'bars': conn.execute(
                "SELECT COUNT(*) FROM prices WHERE close IS NOT NULL").fetchone()[0],
        },
        'regime': regime[-1] if regime else None,
        'tiles': tiles,
        'top': top,
        'alpha': {'n': td.get('n'), 'win': td.get('win'),
                  'beat': td.get('beat'), 'exc_mean': td.get('exc_mean')},
    }


def _pct_txt(v, nd: int = 2) -> str:
    if v is None:
        return '—'
    return f"{'+' if v > 0 else ''}{v * 100:.{nd}f}%"


def _px_txt(v) -> str:
    if v is None:
        return '—'
    a = abs(v)
    if a >= 10000:
        return f'{v:,.0f}'
    return f'{v:,.2f}' if a >= 1 else f'{v:.4f}'


def render_snippet(preview: dict, href: str = 'terminal.html',
                   embed_src: str | None = None) -> str:
    """An embeddable block: live numbers, sparklines, and a launch link.

    Self-contained and namespaced under .rh-term so it cannot collide with the
    host page's styles. Draws sparklines with inline SVG (no canvas, no JS
    needed to render) and only loads the full terminal if the reader asks.
    """
    import html as H

    r = preview.get('regime') or {}
    label = r.get('label') or 'NO REGIME'
    rcolor = {'TRENDING': '#2AA198', 'CHOPPY': '#D9B870',
              'TRANSITION': '#D05228', 'CRISIS': '#C1121F'}.get(label, '#6E6A64')

    def spark_svg(vals, w=108, h=26):
        pts = [v for v in vals if v is not None]
        if len(pts) < 2:
            return ''
        lo, hi = min(pts), max(pts)
        span = (hi - lo) or 1
        up = pts[-1] >= pts[0]
        col = '#2AA198' if up else '#D83A3A'
        step = w / (len(pts) - 1)
        d = ' '.join(
            f'{"M" if i == 0 else "L"}{i * step:.1f},{h - 2 - ((v - lo) / span) * (h - 4):.1f}'
            for i, v in enumerate(pts))
        fill = (f'{d} L{w:.1f},{h:.1f} L0,{h:.1f} Z')
        return (f'<svg class="rh-spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
                f'preserveAspectRatio="none" aria-hidden="true">'
                f'<path d="{fill}" fill="{col}" opacity="0.13"/>'
                f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.5" '
                f'stroke-linejoin="round"/></svg>')

    tiles = []
    for t in preview.get('tiles', []):
        cls = 'up' if (t['d1'] or 0) > 0 else 'dn' if (t['d1'] or 0) < 0 else 'flat'
        mark = '&#9650;' if (t['d1'] or 0) > 0 else '&#9660;' if (t['d1'] or 0) < 0 else '&middot;'
        tiles.append(
            f'<a class="rh-tile" href="{H.escape(href)}" '
            f'title="Open {H.escape(t["t"])} in the terminal">'
            f'<span class="rh-sym">{H.escape(t["t"])}</span>'
            f'{spark_svg(t["spark"])}'
            f'<span class="rh-px">{_px_txt(t["last"])}</span>'
            f'<span class="rh-chg {cls}">{mark} {_pct_txt(t["d1"])}</span></a>')

    top_rows = []
    for n in preview.get('top', []):
        g = n.get('g')
        top_rows.append(
            f'<li><span class="rh-grade rh-g-{H.escape(g or "na")}">{H.escape(g or "—")}</span>'
            f'<span class="rh-nt">{H.escape(n["title"])}</span>'
            f'<span class="rh-nm">{H.escape(" ".join(n["tk"]))}</span></li>')

    c = preview.get('counts', {})
    a = preview.get('alpha', {})
    alpha_txt = ('&mdash;' if not a.get('n') else
                 f"{a['n']} windows &middot; {_pct_txt(a['win'], 0)} hit &middot; "
                 f"{_pct_txt(a['exc_mean'], 1)} mean excess vs SPY")

    inline, inline_js = '', ''
    if embed_src:
        inline = (f'<button class="rh-ghost" type="button" data-rh-embed="{H.escape(embed_src)}">'
                  f'Run it inline</button>')
        inline_js = '''
<script>
(function () {
  var b = document.querySelector('.rh-term [data-rh-embed]');
  if (!b) return;
  b.addEventListener('click', function () {
    var f = document.createElement('iframe');
    f.className = 'rh-frame';
    f.src = b.getAttribute('data-rh-embed');
    f.title = 'RedHood Terminal';
    f.loading = 'lazy';
    b.closest('.rh-term').appendChild(f);
    b.remove();
  });
})();
</script>'''

    return f'''
<section class="rh-term" aria-label="RedHood Terminal preview">
  <style>
  .rh-term {{ --rh-ink:#F5F0E8; --rh-mut:rgba(245,240,232,0.45); --rh-wire:rgba(255,255,255,0.09);
    --rh-red:#C1121F; --rh-gold:#B8975A; --rh-bg:#0C0C0C; --rh-panel:#131313;
    font-family:"IBM Plex Mono",ui-monospace,Consolas,monospace; color:var(--rh-ink);
    background:var(--rh-bg); border:1px solid var(--rh-wire); border-radius:3px;
    margin:28px 0; overflow:hidden; font-variant-numeric:tabular-nums; }}
  .rh-term * {{ box-sizing:border-box; }}
  .rh-bar {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:7px 12px; background:linear-gradient(180deg,#171717,var(--rh-panel));
    border-bottom:1px solid var(--rh-wire); }}
  .rh-hood {{ width:10px; height:10px; background:var(--rh-red); flex:none;
    clip-path:polygon(50% 0,100% 38%,82% 100%,18% 100%,0 38%); }}
  .rh-name {{ font-size:11px; font-weight:700; letter-spacing:0.16em; }}
  .rh-name em {{ font-style:normal; color:var(--rh-red); }}
  .rh-tag {{ font-size:8.5px; letter-spacing:0.22em; color:var(--rh-mut); }}
  .rh-chip {{ display:flex; align-items:center; gap:6px; margin-left:auto;
    border:1px solid var(--rh-wire); padding:2px 8px; font-size:9px; letter-spacing:0.08em; }}
  .rh-dot {{ width:6px; height:6px; border-radius:50%; background:{rcolor}; flex:none; }}
  .rh-strip {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;
    padding:5px 12px; font-size:8.5px; letter-spacing:0.18em; text-transform:uppercase;
    color:var(--rh-gold); border-bottom:1px solid var(--rh-wire); }}
  .rh-strip .rh-dim {{ color:var(--rh-mut); letter-spacing:0.06em; text-transform:none;
    font-size:9px; margin-left:auto; }}
  .rh-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
    gap:1px; background:var(--rh-wire); }}
  .rh-tile {{ display:block; padding:7px 10px 6px; background:var(--rh-panel);
    text-decoration:none; color:inherit; transition:background .15s; }}
  .rh-tile:hover {{ background:#1B1B1B; }}
  .rh-sym {{ display:block; font-size:10px; font-weight:600; letter-spacing:0.06em;
    color:var(--rh-gold); margin-bottom:2px; }}
  .rh-spark {{ display:block; width:100%; height:26px; margin:1px 0 3px; }}
  .rh-px {{ font-size:13px; font-weight:600; margin-right:6px; }}
  .rh-chg {{ font-size:10px; }}
  .rh-term .up {{ color:#2AA198; }} .rh-term .dn {{ color:#D83A3A; }}
  .rh-term .flat {{ color:var(--rh-mut); }}
  .rh-body {{ display:grid; grid-template-columns:minmax(0,1.5fr) minmax(0,1fr); gap:0;
    border-top:1px solid var(--rh-wire); }}
  @media (max-width:640px) {{ .rh-body {{ grid-template-columns:minmax(0,1fr); }} }}
  .rh-col {{ padding:9px 12px; min-width:0; }}
  .rh-col + .rh-col {{ border-left:1px solid var(--rh-wire); }}
  @media (max-width:640px) {{ .rh-col + .rh-col {{ border-left:0; border-top:1px solid var(--rh-wire); }} }}
  .rh-h {{ font-size:8.5px; letter-spacing:0.18em; text-transform:uppercase;
    color:var(--rh-mut); margin:0 0 6px; }}
  .rh-term ul {{ list-style:none; margin:0; padding:0; }}
  .rh-term li {{ display:flex; align-items:baseline; gap:7px; padding:2px 0;
    border-bottom:1px solid rgba(255,255,255,0.045); font-size:10.5px; }}
  .rh-term li:last-child {{ border-bottom:0; }}
  .rh-grade {{ flex:none; width:17px; text-align:center; font-size:9px; font-weight:700;
    color:#0C0C0C; background:var(--rh-gold); border-radius:2px; }}
  .rh-g-A,.rh-g-A- {{ background:#F0D9A8; }} .rh-g-B {{ background:#D9B870; }}
  .rh-g-C {{ background:#B8975A; }} .rh-g-D {{ background:#8E7342; }}
  .rh-g-na {{ background:rgba(255,255,255,0.14); color:var(--rh-ink); }}
  .rh-nt {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .rh-nm {{ margin-left:auto; color:var(--rh-mut); font-size:9px; flex:none; }}
  .rh-kv {{ font-size:10px; color:var(--rh-mut); line-height:1.7; }}
  .rh-kv b {{ color:var(--rh-ink); font-weight:600; }}
  .rh-foot {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:9px 12px; border-top:1px solid var(--rh-wire); background:var(--rh-panel); }}
  .rh-cta {{ display:inline-flex; align-items:center; gap:7px; background:var(--rh-red);
    color:#fff; text-decoration:none; font-size:10px; font-weight:700; letter-spacing:0.14em;
    padding:7px 14px; border-radius:2px; transition:filter .15s; }}
  .rh-cta:hover {{ filter:brightness(1.18); }}
  .rh-ghost {{ background:none; border:1px solid var(--rh-wire); color:var(--rh-mut);
    font:inherit; font-size:9.5px; letter-spacing:0.1em; padding:6px 11px; border-radius:2px;
    cursor:pointer; }}
  .rh-ghost:hover {{ color:var(--rh-ink); border-color:var(--rh-gold); }}
  .rh-note {{ font-size:9px; color:var(--rh-mut); margin-left:auto; }}
  .rh-frame {{ width:100%; height:78vh; min-height:460px; border:0;
    border-top:1px solid var(--rh-wire); display:block; background:var(--rh-bg); }}
  </style>

  <div class="rh-bar">
    <span class="rh-hood"></span>
    <span class="rh-name">RED<em>HOOD</em></span>
    <span class="rh-tag">TERMINAL</span>
    <span class="rh-chip"><span class="rh-dot"></span>{H.escape(label)}
      &middot; T {_pct_txt(r.get('temp'), 1)} &middot; x{(r.get('mult') if r.get('mult') is not None else 0):.2f}
      {'&middot; DRIFT' if r.get('warn') else ''}</span>
  </div>

  <div class="rh-strip">
    <span>Watchlist</span>
    <span class="rh-dim">sparkline = last 60 sessions &middot; price &amp; change = latest close</span>
  </div>
  <div class="rh-grid">{''.join(tiles)}</div>

  <div class="rh-body">
    <div class="rh-col">
      <p class="rh-h">Latest narratives</p>
      <ul>{''.join(top_rows) or '<li>No narratives yet</li>'}</ul>
    </div>
    <div class="rh-col">
      <p class="rh-h">What's inside</p>
      <p class="rh-kv">
        <b>{c.get('symbols', 0)}</b> symbols &middot; <b>{c.get('bars', 0):,}</b> daily bars<br>
        <b>{c.get('narratives', 0)}</b> narratives over <b>{c.get('runs', 0)}</b> runs<br>
        Realised: {alpha_txt}
      </p>
    </div>
  </div>

  <div class="rh-foot">
    <a class="rh-cta" href="{H.escape(href)}">&#9632; LAUNCH TERMINAL</a>
    {inline}
    <span class="rh-note">charts &middot; narrative markers &middot; regime &middot; alpha
      &mdash; data as of {H.escape(preview.get('as_of') or '—')}</span>
  </div>
</section>{inline_js}
'''


# ---------------------------------------------------------------------------
# page assembly
# ---------------------------------------------------------------------------

def _read_src(name: str) -> str:
    path = os.path.join(SRC_DIR, name)
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def render_page(bundle: dict | None, mode: str = 'static',
                api_base: str = '') -> str:
    """Inline CSS + JS (+ optionally the data) into one self-contained page."""
    html = _read_src('index.html')
    css = '\n'.join(_read_src(f) for f in CSS_FILES)
    js = '\n'.join(f'/* ---- {f} ---- */\n' + _read_src(f) for f in JS_FILES)

    if bundle is not None:
        payload = json.dumps(bundle, ensure_ascii=False, separators=(',', ':'))
        data_block = f'window.RH_BUNDLE={payload};'
    else:
        data_block = 'window.RH_BUNDLE=null;'

    config = json.dumps({'mode': mode, 'api': api_base,
                         'built': (bundle or {}).get('meta', {}).get('built_at', _now_iso())})

    return (html
            .replace('/*%%CSS%%*/', css)
            .replace('/*%%CONFIG%%*/', f'window.RH_CONFIG={config};')
            .replace('/*%%DATA%%*/', data_block.replace('</', '<\\/'))
            .replace('/*%%JS%%*/', js))


def write_html(conn: sqlite3.Connection, path: str | None = None,
               max_bars: int = DEFAULT_BARS, tape_limit: int = TAPE_LIMIT) -> str:
    path = path or os.path.join(DOCS_DIR, 'terminal.html')
    bundle = build_bundle(conn, max_bars, tape_limit)
    out = render_page(bundle, mode='static')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(out)
    return path


# ---------------------------------------------------------------------------
# live mode
# ---------------------------------------------------------------------------

def serve(db: str, port: int = 8787, max_bars: int = DEFAULT_BARS) -> None:
    """Local server: same bundle over HTTP + /api/quotes for polled quotes."""
    import http.server
    import socketserver
    import urllib.parse

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8', code)

        def do_GET(self):                                     # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path.rstrip('/') or '/'

            if route in ('/', '/terminal.html'):
                page = render_page(None, mode='live', api_base='/api')
                return self._send(page.encode('utf-8'), 'text/html; charset=utf-8')

            if route == '/static':
                # The exact artifact that gets published, for eyeballing it.
                built = os.path.join(DOCS_DIR, 'terminal.html')
                if not os.path.exists(built):
                    return self._json({'error': 'run --html first', 'path': built}, 404)
                with open(built, encoding='utf-8') as fh:
                    return self._send(fh.read().encode('utf-8'), 'text/html; charset=utf-8')

            if route == '/api/bundle':
                conn = _connect(db)
                try:
                    bundle = build_bundle(conn, max_bars)
                finally:
                    conn.close()
                bundle['meta']['mode'] = 'live'
                return self._json(bundle)

            if route == '/api/quotes':
                qs = urllib.parse.parse_qs(parsed.query)
                syms = [s for s in (qs.get('symbols', [''])[0]).split(',') if s]
                return self._json({'at': _now_iso(), 'quotes': live_quotes(syms)})

            return self._json({'error': 'not found', 'path': route}, 404)

        def log_message(self, fmt, *args):                     # quieter console
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('127.0.0.1', port), Handler) as httpd:
        print(f"RedHood Terminal (live) -> http://127.0.0.1:{port}/")
        print("  /api/bundle   full data bundle")
        print("  /api/quotes?symbols=SPY,NVDA   polled quotes")
        print("Ctrl-C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


def live_quotes(symbols: list[str]) -> dict:
    """Last price / change for `symbols` via yfinance, best-effort."""
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out: dict[str, dict] = {}
    try:
        data = yf.download(symbols, period='5d', interval='1m', progress=False,
                           auto_adjust=False, group_by='ticker', threads=True)
    except Exception:                                          # noqa: BLE001
        return {}
    if data is None or getattr(data, 'empty', True):
        return {}
    multi = getattr(data.columns, 'nlevels', 1) > 1
    for sym in symbols:
        try:
            sub = data[sym] if multi and sym in set(data.columns.get_level_values(0)) else data
            closes = [float(x) for x in sub['Close'].dropna().tolist()]
            if not closes:
                continue
            out[sym] = {'last': _r(closes[-1]),
                        'chg': _r((closes[-1] / closes[0] - 1) if closes[0] else None, 6),
                        'n': len(closes)}
        except Exception:                                      # noqa: BLE001, S112
            continue
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_stats(bundle: dict) -> None:
    c = bundle['meta']['counts']
    print(f"RedHood Terminal bundle v{bundle['meta']['version']}  "
          f"built {bundle['meta']['built_at']}")
    print(f"  symbols     {c['symbols']} ({c['with_ohlc']} with OHLC candles)")
    print(f"  price bars  {c['bars']}")
    print(f"  narratives  {c['narratives']}  over {c['runs']} runs")
    print(f"  regime rows {c['regime']}")
    print(f"  tape        {len(bundle['tape'])} items")
    print(f"  notes       {len(bundle['notes'])}")
    print(f"  as of       {bundle['meta']['as_of']}")
    r = bundle['meta'].get('regime_now')
    if r:
        print(f"  regime now  {r['label']}  T={r['temp']}  S={r['S']}  "
              f"mult={r['mult']}  warn={r['warn']}")
    a = bundle['alpha']['by_horizon']
    for h, v in a.items():
        if v:
            print(f"  alpha {h:>7}  n={v['n']:<4} win={v['win']} "
                  f"excess_mean={v['exc_mean']}")


def main() -> int:
    p = argparse.ArgumentParser(description="RedHood Terminal builder")
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--html', nargs='?', const='', metavar='PATH',
                   help="write the self-contained page (default docs/terminal.html)")
    p.add_argument('--json', metavar='PATH', help="write just the data bundle")
    p.add_argument('--serve', action='store_true', help="run the live local server")
    p.add_argument('--port', type=int, default=8787)
    p.add_argument('--bars', type=int, default=DEFAULT_BARS,
                   help=f"max bars per symbol (default {DEFAULT_BARS})")
    p.add_argument('--tape', type=int, default=TAPE_LIMIT, help="tape items")
    p.add_argument('--snippet', nargs='?', const='-', metavar='PATH',
                   help="write the embeddable preview block ('-' for stdout)")
    p.add_argument('--stats', action='store_true', help="print bundle stats")
    p.add_argument('--open', action='store_true', help="open the page when written")
    args = p.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: no database at {args.db}", file=sys.stderr)
        return 1

    if args.serve:
        serve(args.db, args.port, args.bars)
        return 0

    conn = _connect(args.db)
    try:
        if args.snippet:
            snippet = render_snippet(build_preview(conn), embed_src='terminal.html')
            if args.snippet == '-':
                print(snippet)
            else:
                with open(args.snippet, 'w', encoding='utf-8') as fh:
                    fh.write(snippet)
                print(f"wrote {args.snippet} ({len(snippet) / 1024:.1f} KB)")
            return 0

        if args.json:
            bundle = build_bundle(conn, args.bars, args.tape)
            with open(args.json, 'w', encoding='utf-8') as fh:
                json.dump(bundle, fh, ensure_ascii=False, separators=(',', ':'))
            print(f"wrote {args.json} ({os.path.getsize(args.json) / 1e6:.2f} MB)")
            if args.stats:
                _print_stats(bundle)
            return 0

        if args.stats and args.html is None:
            _print_stats(build_bundle(conn, args.bars, args.tape))
            return 0

        path = write_html(conn, args.html or None, args.bars, args.tape)
        size = os.path.getsize(path) / 1e6
        print(f"wrote {path} ({size:.2f} MB)")
        if args.stats:
            _print_stats(build_bundle(conn, args.bars, args.tape))
        if args.open:
            import webbrowser
            webbrowser.open('file:///' + path.replace('\\', '/'))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
