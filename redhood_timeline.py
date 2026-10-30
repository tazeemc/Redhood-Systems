"""
redhood_timeline.py
RedHood Systems — Paginated Historical Timeline
===============================================
Builds a page-able timeline of past runs from redhood.db so the system can
"remember": every run with its thermodynamic regime, the narratives it
produced (entropy-risk score, bear-case verdict, grade, long-side tickers),
the realised forward returns of those tickers, and how often each theme and
ticker had already appeared.

Three consumers:
  1. The extraction prompt — recent_context() renders a compact block the
     LLM reads before extracting new narratives (what was said recently,
     which tickers are crowded, what has actually worked).
  2. The report — continuation flags ("seen 3x before") per narrative, and a
     regime-history strip.
  3. People — a self-contained docs/timeline.html with client-side pagination
     and filters, and a CLI (`python redhood_timeline.py --page 2 --size 10`).

Pure stdlib (sqlite3 + json + html). No network.

Usage:
    python redhood_timeline.py                   # page 1, 10 runs per page
    python redhood_timeline.py --page 3 --size 5
    python redhood_timeline.py --context         # print the prompt block
    python redhood_timeline.py --html            # write docs/timeline.html
    python redhood_timeline.py --flag            # (re)compute prior_mentions / continuation_of
"""

from __future__ import annotations

import argparse
import html as H
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'redhood.db')
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
DEFAULT_PAGE_SIZE = 10
LOOKBACK_DAYS = 30            # window for "seen before" / redundancy counts
TITLE_SIMILARITY = 0.5        # Jaccard threshold on title tokens for continuation

_STOP = {'the', 'and', 'of', 'to', 'in', 'on', 'for', 'a', 'an', 'as', 'vs', 'with', 'from', 'into',
         'amid', 'after', 'before', 'over', 'under', 'by', 'at', 'is', 'are', 'risk', 'market',
         'markets', 'trade', 'rally', 'selloff', 'sell-off', 'pressure', 'fears', 'concerns'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _tokens(title: str) -> set:
    toks = re.findall(r"[a-z0-9]+", (title or '').lower())
    return {t for t in toks if t not in _STOP and len(t) > 2}


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity of the content tokens of two titles."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))


def _pct(v, digits: int = 1) -> str:
    return '--' if v is None else f"{100 * v:+.{digits}f}%"


# ---------------------------------------------------------------------------
# Continuation flags  (narratives.prior_mentions / continuation_of)
# ---------------------------------------------------------------------------

def find_continuation(conn: sqlite3.Connection, title: str, created_at: str,
                      lookback_days: int = LOOKBACK_DAYS, exclude_id: str | None = None,
                      threshold: float = TITLE_SIMILARITY) -> tuple[int, str | None]:
    """How many earlier narratives (within lookback) share this title's theme, and the latest one's id."""
    try:
        since = (datetime.fromisoformat(created_at[:19]) - timedelta(days=lookback_days)).isoformat()
    except ValueError:
        since = ''
    rows = conn.execute(
        "SELECT id, title, created_at FROM narratives WHERE created_at >= ? AND created_at < ? "
        "ORDER BY created_at DESC", (since, created_at)).fetchall()
    count = 0
    latest = None
    for r in rows:
        if exclude_id and r[0] == exclude_id:
            continue
        if title_similarity(title, r[1]) >= threshold:
            count += 1
            if latest is None:
                latest = r[0]
    return count, latest


def flag_continuations(conn: sqlite3.Connection, since: str | None = None, verbose: bool = False) -> int:
    """Populate narratives.prior_mentions / continuation_of (idempotent). Returns rows updated."""
    if not _col_exists(conn, 'narratives', 'prior_mentions'):
        conn.execute("ALTER TABLE narratives ADD COLUMN prior_mentions INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(conn, 'narratives', 'continuation_of'):
        conn.execute("ALTER TABLE narratives ADD COLUMN continuation_of TEXT")
    sql = "SELECT id, title, created_at FROM narratives"
    params: tuple = ()
    if since:
        sql += " WHERE created_at >= ?"
        params = (since,)
    sql += " ORDER BY created_at"
    n = 0
    for nid, title, created in conn.execute(sql, params).fetchall():
        count, latest = find_continuation(conn, title, created, exclude_id=nid)
        conn.execute("UPDATE narratives SET prior_mentions = ?, continuation_of = ? WHERE id = ?",
                     (count, latest, nid))
        n += 1
    conn.commit()
    if verbose:
        print(f"Continuation flags computed for {n} narratives")
    return n


# ---------------------------------------------------------------------------
# Redundancy (ticker mention counts) and realised returns
# ---------------------------------------------------------------------------

def ticker_redundancy(conn: sqlite3.Connection, as_of: str | None = None,
                      lookback_days: int = LOOKBACK_DAYS, side: str = 'long') -> list[dict]:
    """Long-side tickers mentioned in the lookback window with counts and realised 20-day excess return.

    Uses grader-vetted rows (is_long_equity = 1) when present, else the
    star-schema 'Long' rows.  Sorted by count desc.
    """
    as_of = as_of or latest_run_at(conn) or _now_iso()
    since = (datetime.fromisoformat(as_of[:19]) - timedelta(days=lookback_days)).isoformat()
    has_returns = _table_exists(conn, 'narrative_returns')
    rows = conn.execute(
        "SELECT nt.ticker, nt.narrative_id, r.run_at FROM narrative_tickers nt "
        "JOIN narratives n ON n.id = nt.narrative_id JOIN runs r ON r.id = n.run_id "
        "WHERE r.run_at >= ? AND r.run_at <= ? AND (nt.is_long_equity = 1 OR nt.side = 'Long')",
        (since, as_of)).fetchall()
    counts: dict[str, dict] = {}
    seen_pairs = set()
    for ticker, nid, run_at in rows:
        if (ticker, nid) in seen_pairs:
            continue
        seen_pairs.add((ticker, nid))
        d = counts.setdefault(ticker, {'ticker': ticker, 'mentions': 0, 'last_run': run_at, 'excess_h20': [], 'excess_h5': []})
        d['mentions'] += 1
        d['last_run'] = max(d['last_run'], run_at)
    if has_returns and counts:
        for ticker in counts:
            rr = conn.execute(
                "SELECT h5, spy_h5, h20, spy_h20 FROM narrative_returns WHERE ticker = ?", (ticker,)).fetchall()
            counts[ticker]['excess_h5'] = [a - b for a, b, _, _ in rr if a is not None and b is not None]
            counts[ticker]['excess_h20'] = [a - b for _, _, a, b in rr if a is not None and b is not None]
    out = []
    for d in counts.values():
        e20 = d.pop('excess_h20')
        e5 = d.pop('excess_h5')
        d['mean_excess_h20'] = (sum(e20) / len(e20)) if e20 else None
        d['mean_excess_h5'] = (sum(e5) / len(e5)) if e5 else None
        d['n_realised'] = len(e20)
        out.append(d)
    out.sort(key=lambda d: (-d['mentions'], d['ticker']))
    return out


def realised_lesson(conn: sqlite3.Connection, min_rows: int = 30) -> dict | None:
    """First-vs-repeat mention excess returns from narrative_returns, if enough data."""
    if not _table_exists(conn, 'narrative_returns'):
        return None
    try:
        from redhood_pnl import novelty_summary
    except ImportError:
        return None
    s = novelty_summary(conn)
    if s.get('first', {}).get('n', 0) + s.get('repeat', {}).get('n', 0) < min_rows:
        return None
    return s


# ---------------------------------------------------------------------------
# Timeline pages
# ---------------------------------------------------------------------------

def _regime_for_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    if not _table_exists(conn, 'regime_history'):
        return None
    r = conn.execute(
        "SELECT label, temperature, entropy, eta, kl_divergence, kl_threshold, heat, heat_budget, "
        "signal_multiplier, warning, computed_at FROM regime_history WHERE run_id = ? "
        "ORDER BY computed_at DESC LIMIT 1", (run_id,)).fetchone()
    if not r:
        return None
    keys = ('label', 'temperature', 'entropy', 'eta', 'kl_divergence', 'kl_threshold', 'heat',
            'heat_budget', 'signal_multiplier', 'warning', 'computed_at')
    return dict(zip(keys, r, strict=True))


def run_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def latest_run_at(conn: sqlite3.Connection) -> str | None:
    """Timestamp of the newest run — the system's own 'now' for lookback windows."""
    row = conn.execute("SELECT MAX(run_at) FROM runs").fetchone()
    return row[0] if row and row[0] else None


def get_page(conn: sqlite3.Connection, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """One page of the timeline (newest runs first).

    Returns {'page', 'page_size', 'total_runs', 'total_pages', 'runs': [...]}
    where each run carries its regime (if recorded) and its narratives with
    tickers, grades, verdicts, continuation flags and realised returns.
    """
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total = run_count(conn)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    has_grades = _table_exists(conn, 'narrative_grades')
    has_returns = _table_exists(conn, 'narrative_returns')
    has_flags = _col_exists(conn, 'narratives', 'prior_mentions')
    runs = conn.execute(
        "SELECT id, run_at, hours_back, feeds_collected, narratives_extracted, html_path "
        "FROM runs ORDER BY run_at DESC, id DESC LIMIT ? OFFSET ?",
        (page_size, (page - 1) * page_size)).fetchall()
    out_runs = []
    for rid, run_at, hours_back, feeds, n_narr, html_path in runs:
        narrs = []
        cols = "id, title, entropy_risk, entropy_band, hypothesis, conviction_adjustment, conviction_size, created_at"
        if has_flags:
            cols += ", prior_mentions, continuation_of"
        for row in conn.execute(f"SELECT {cols} FROM narratives WHERE run_id = ? ORDER BY created_at, id", (rid,)).fetchall():
            nid = row[0]
            d = {'id': nid, 'title': row[1], 'entropy_risk': row[2], 'entropy_band': row[3],
                 'hypothesis': row[4], 'conviction_adjustment': row[5], 'conviction_size': row[6],
                 'created_at': row[7],
                 'prior_mentions': row[8] if has_flags else 0, 'continuation_of': row[9] if has_flags else None}
            d['tickers'] = [{'ticker': t, 'side': s_} for t, s_ in conn.execute(
                "SELECT ticker, side FROM narrative_tickers WHERE narrative_id = ? ORDER BY side, ticker", (nid,)).fetchall()]
            d['long_tickers'] = [t for t, in conn.execute(
                "SELECT ticker FROM narrative_tickers WHERE narrative_id = ? AND is_long_equity = 1 ORDER BY ticker", (nid,)).fetchall()]
            if has_grades:
                g = conn.execute("SELECT total_score, letter_grade FROM narrative_grades WHERE narrative_id = ?", (nid,)).fetchone()
                d['grade'] = {'total': g[0], 'letter': g[1]} if g else None
            if has_returns:
                d['returns'] = [
                    {'ticker': t, 'entry_date': ed, 'h5': h5, 'h20': h20, 'h60': h60, 'todate': td,
                     'excess_h5': (h5 - s5) if h5 is not None and s5 is not None else None,
                     'excess_h20': (h20 - s20) if h20 is not None and s20 is not None else None,
                     'excess_h60': (h60 - s60) if h60 is not None and s60 is not None else None,
                     'excess_todate': (td - st) if td is not None and st is not None else None}
                    for t, ed, h5, h20, h60, td, s5, s20, s60, st in conn.execute(
                        "SELECT ticker, entry_date, h5, h20, h60, todate, spy_h5, spy_h20, spy_h60, spy_todate "
                        "FROM narrative_returns WHERE narrative_id = ? ORDER BY ticker", (nid,)).fetchall()]
            narrs.append(d)
        out_runs.append({'run_id': rid, 'run_at': run_at, 'hours_back': hours_back, 'feeds_collected': feeds,
                         'narratives_extracted': n_narr, 'html_path': html_path,
                         'regime': _regime_for_run(conn, rid), 'narratives': narrs})
    return {'page': page, 'page_size': page_size, 'total_runs': total, 'total_pages': total_pages, 'runs': out_runs}


def regime_strip(conn: sqlite3.Connection, limit: int = 12) -> list[dict]:
    """Most recent regime states (newest first) for the report's history strip."""
    if not _table_exists(conn, 'regime_history'):
        return []
    rows = conn.execute(
        "SELECT label, temperature, kl_divergence, warning, computed_at, run_id FROM regime_history "
        "ORDER BY computed_at DESC LIMIT ?", (limit,)).fetchall()
    return [{'label': a, 'temperature': b, 'kl_divergence': c, 'warning': bool(d), 'computed_at': e, 'run_id': f}
            for a, b, c, d, e, f in rows]


# ---------------------------------------------------------------------------
# Prompt context
# ---------------------------------------------------------------------------

def recent_context(conn: sqlite3.Connection, n_runs: int = 8, max_chars: int = 3500,
                   as_of: str | None = None) -> str:
    """Compact historical block for the extraction prompt (empty string if no history)."""
    if run_count(conn) == 0:
        return ''
    page = get_page(conn, 1, n_runs)
    lines = [f"HISTORICAL CONTEXT — last {len(page['runs'])} runs, newest first "
             f"(of {page['total_runs']} runs in the system's memory):"]
    for run in page['runs']:
        reg = run.get('regime') or {}
        rtxt = f"regime {reg['label']} T={100 * reg['temperature']:.1f}%" if reg else "regime n/a"
        when = run['run_at'][:16].replace('T', ' ')
        lines.append(f"[{when} | {rtxt}]")
        for n in run['narratives']:
            verdict = (n.get('conviction_adjustment') or '').split('—')[0].split(' - ')[0].strip() or 'n/a'
            tick = ', '.join(n['long_tickers']) if n['long_tickers'] else ''
            seen = f" | seen {n['prior_mentions']}x before" if n.get('prior_mentions') else ''
            realised = ''
            if n.get('returns'):
                ex = [r['excess_h20'] for r in n['returns'] if r.get('excess_h20') is not None]
                if ex:
                    realised = f" | realised 20d vs SPY {_pct(sum(ex) / len(ex))}"
            lines.append(f"  - \"{n['title']}\" (entropy {n['entropy_risk']}/10; verdict {verdict}"
                         f"{'; longs ' + tick if tick else ''}{seen}{realised})")
    red = [d for d in ticker_redundancy(conn, as_of=as_of) if d['mentions'] >= 2][:15]
    if red:
        lines.append(f"TICKER REDUNDANCY — long-side tickers mentioned 2+ times in the last {LOOKBACK_DAYS} days "
                     "(count; realised mean 20-day excess vs SPY where known):")
        lines.append("  " + "; ".join(
            f"{d['ticker']} x{d['mentions']}" + (f" ({_pct(d['mean_excess_h20'])})" if d['mean_excess_h20'] is not None else '')
            for d in red))
    lesson = realised_lesson(conn)
    if lesson:
        f, r = lesson['first'], lesson['repeat']
        lines.append("REALISED LESSON from this system's own ledger: first mentions of a ticker averaged "
                     f"{_pct(f.get('h20'))} vs SPY over 20 days (n={f.get('h20_n')}); repeat mentions averaged "
                     f"{_pct(r.get('h20'))} over 20 days and {_pct(r.get('h60'))} over 60 days (n={r.get('h60_n')}). "
                     "Repetition has meant crowding, not confirmation.")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 20].rsplit('\n', 1)[0] + "\n  …(truncated)"
    return text


# ---------------------------------------------------------------------------
# HTML timeline (self-contained, client-side pagination)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RedHood Timeline</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=IBM+Plex+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root { --red:#C1121F; --cream:#F5F0E8; --gold:#B8975A; --dark:#0A0A0A; --mid:#1C1C1C; --wire:rgba(255,255,255,0.08);
          --muted:rgba(245,240,232,0.5); --trending:#00e5a0; --choppy:#f5a623; --crisis:#ff4060; --transition:#7b8cde; }
  body { background: var(--dark); color: var(--cream); font-family: "IBM Plex Mono", monospace; font-size: 12px; padding: 24px; }
  h1 { font-family: "Playfair Display", serif; font-size: 34px; font-weight: 900; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 11px; margin: 6px 0 18px; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:16px; }
  .toolbar label { color: var(--muted); font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; }
  select, input, button { background: var(--mid); color: var(--cream); border: 1px solid var(--wire); padding: 6px 8px; font-family: inherit; font-size: 12px; }
  button { cursor: pointer; } button:disabled { opacity: 0.4; cursor: default; }
  .run { border: 1px solid var(--wire); margin-bottom: 14px; }
  .run-head { display:flex; flex-wrap:wrap; gap:14px; align-items:center; padding: 10px 14px; background: var(--mid); border-bottom: 1px solid var(--wire); }
  .run-date { font-family: "Playfair Display", serif; font-size: 18px; }
  .badge { font-weight: 700; font-size: 10px; letter-spacing: 0.14em; padding: 3px 8px; border: 1px solid; }
  .TRENDING { color: var(--trending); border-color: var(--trending); } .CHOPPY { color: var(--choppy); border-color: var(--choppy); }
  .CRISIS { color: var(--crisis); border-color: var(--crisis); } .TRANSITION { color: var(--transition); border-color: var(--transition); }
  .meta { color: var(--muted); font-size: 10px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 7px 12px; vertical-align: top; border-top: 1px solid var(--wire); }
  th { color: var(--muted); font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; border-top: none; }
  .title { font-family: "Playfair Display", serif; font-size: 14px; }
  .pos { color: var(--trending); } .neg { color: var(--crisis); } .dim { color: var(--muted); }
  .seen { color: var(--gold); font-size: 10px; }
  .pager { display:flex; gap:8px; align-items:center; margin: 16px 0; }
  .strip { display:flex; gap:3px; margin: 10px 0 18px; } .strip span { width: 22px; height: 10px; display:inline-block; }
  .s-TRENDING{background:var(--trending)} .s-CHOPPY{background:var(--choppy)} .s-CRISIS{background:var(--crisis)} .s-TRANSITION{background:var(--transition)} .s-none{background:var(--wire)}
</style>
</head>
<body>
<h1>RedHood Timeline</h1>
<div class="sub">%%SUBTITLE%%</div>
<div class="strip" title="Regime history, oldest to newest">%%STRIP%%</div>
<div class="toolbar">
  <label>Page size</label><select id="size"><option>5</option><option selected>10</option><option>20</option><option>50</option></select>
  <label>Regime</label><select id="regime"><option value="">all</option><option>TRENDING</option><option>CHOPPY</option><option>CRISIS</option><option>TRANSITION</option></select>
  <label>Ticker</label><input id="ticker" placeholder="e.g. LMT" size="8">
  <label>Entropy ≥</label><input id="ent" type="number" min="1" max="10" placeholder="1" size="3">
</div>
<div class="pager"><button id="prev">&larr; newer</button><span id="pageinfo"></span><button id="next">older &rarr;</button></div>
<div id="runs"></div>
<div class="pager"><button id="prev2">&larr; newer</button><span id="pageinfo2"></span><button id="next2">older &rarr;</button></div>
<script id="data" type="application/json">%%DATA%%</script>
<script>
(function () {
  const runs = JSON.parse(document.getElementById('data').textContent);
  let page = 1;
  const $ = id => document.getElementById(id);
  const pct = v => v == null ? '<span class="dim">--</span>' : '<span class="' + (v >= 0 ? 'pos' : 'neg') + '">' + (100 * v >= 0 ? '+' : '') + (100 * v).toFixed(1) + '%</span>';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  function filtered() {
    const reg = $('regime').value, tk = $('ticker').value.trim().toUpperCase(), ent = parseInt($('ent').value || '0', 10);
    return runs.filter(r => {
      if (reg && !(r.regime && r.regime.label === reg)) return false;
      if (tk && !r.narratives.some(n => n.tickers.some(t => t.ticker === tk))) return false;
      if (ent && !r.narratives.some(n => n.entropy_risk >= ent)) return false;
      return true;
    });
  }
  function render() {
    const size = parseInt($('size').value, 10), rows = filtered();
    const pages = Math.max(1, Math.ceil(rows.length / size));
    page = Math.min(Math.max(1, page), pages);
    const slice = rows.slice((page - 1) * size, page * size);
    $('runs').innerHTML = slice.map(r => {
      const reg = r.regime ? '<span class="badge ' + r.regime.label + '">' + r.regime.label + '</span><span class="meta">T ' + (100 * r.regime.temperature).toFixed(1) + '% · D ' + (r.regime.kl_divergence == null ? '--' : r.regime.kl_divergence.toFixed(3)) + (r.regime.warning ? ' · DRIFT' : '') + ' · heat ' + (100 * (r.regime.heat || 0)).toFixed(1) + '%</span>' : '<span class="meta">regime not recorded</span>';
      const trs = r.narratives.map(n => {
        const ret = (n.returns || []).map(x => esc(x.ticker) + ' 20d ' + pct(x.excess_h20) + ' · 60d ' + pct(x.excess_h60)).join('<br>');
        const seen = n.prior_mentions ? '<div class="seen">&#8635; seen ' + n.prior_mentions + '× before</div>' : '';
        return '<tr><td><div class="title">' + esc(n.title) + '</div>' + seen + '</td><td>' + n.entropy_risk + '/10</td><td>' + esc((n.conviction_adjustment || '').split('—')[0].trim() || '--') + '</td><td>' + (n.grade ? n.grade.letter + ' (' + n.grade.total + ')' : '--') + '</td><td>' + n.tickers.map(t => esc(t.ticker) + '<span class="dim">/' + esc(t.side).slice(0,1) + '</span>').join(' ') + '</td><td>' + (ret || '<span class="dim">--</span>') + '</td></tr>';
      }).join('');
      return '<div class="run"><div class="run-head"><span class="run-date">' + esc(r.run_at.slice(0, 16).replace('T', ' ')) + '</span>' + reg + '<span class="meta">' + r.feeds_collected + ' feeds · ' + r.narratives_extracted + ' narratives · window ' + r.hours_back + 'h</span></div>' +
        '<table><thead><tr><th>Narrative</th><th>Entropy</th><th>Verdict</th><th>Grade</th><th>Tickers</th><th>Realised vs SPY (long side)</th></tr></thead><tbody>' + (trs || '<tr><td colspan="6" class="dim">no narratives</td></tr>') + '</tbody></table></div>';
    }).join('') || '<div class="dim">No runs match the filters.</div>';
    const info = 'page ' + page + ' / ' + pages + ' · ' + rows.length + ' runs';
    $('pageinfo').textContent = info; $('pageinfo2').textContent = info;
    for (const b of ['prev', 'prev2']) $(b).disabled = page <= 1;
    for (const b of ['next', 'next2']) $(b).disabled = page >= pages;
  }
  for (const b of ['prev', 'prev2']) $(b).onclick = () => { page--; render(); };
  for (const b of ['next', 'next2']) $(b).onclick = () => { page++; render(); };
  for (const id of ['size', 'regime', 'ticker', 'ent']) $(id).addEventListener('input', () => { page = 1; render(); });
  render();
})();
</script>
</body>
</html>
"""


def write_html(conn: sqlite3.Connection, path: str | None = None, max_runs: int = 500) -> str:
    """Write the self-contained timeline page; returns the path."""
    path = path or os.path.join(DOCS_DIR, 'timeline.html')
    page = get_page(conn, 1, max_runs)
    strip = regime_strip(conn, limit=60)
    strip_html = ''.join(
        f'<span class="s-{H.escape(s["label"])}" title="{H.escape(s["computed_at"][:16])} {H.escape(s["label"])}"></span>'
        for s in reversed(strip)) or '<span class="s-none"></span>'
    subtitle = (f"{page['total_runs']} runs · {sum(len(r['narratives']) for r in page['runs'])} narratives · "
                f"generated {_now_iso()[:16].replace('T', ' ')} UTC · regime history: "
                + ", ".join(f"{k} {v}" for k, v in _label_counts(strip).items()))
    data = json.dumps(page['runs'], ensure_ascii=False).replace('</', '<\\/')
    html_out = (_HTML_TEMPLATE.replace('%%DATA%%', data).replace('%%STRIP%%', strip_html)
                .replace('%%SUBTITLE%%', H.escape(subtitle)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html_out)
    return path


def _label_counts(strip: list[dict]) -> dict:
    out: dict[str, int] = {}
    for s in strip:
        out[s['label']] = out.get(s['label'], 0) + 1
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_page(page: dict) -> None:
    print(f"Timeline page {page['page']}/{page['total_pages']}  ({page['total_runs']} runs, {page['page_size']} per page)")
    for run in page['runs']:
        reg = run.get('regime')
        rtxt = (f"{reg['label']} T={100 * reg['temperature']:.1f}% D={reg['kl_divergence']:.3f}"
                + (' DRIFT' if reg.get('warning') else '') + f" heat={100 * (reg.get('heat') or 0):.1f}%") if reg else 'regime n/a'
        print(f"\n== run #{run['run_id']}  {run['run_at'][:16].replace('T', ' ')}  [{rtxt}]  "
              f"{run['feeds_collected']} feeds, {run['narratives_extracted']} narratives")
        for n in run['narratives']:
            seen = f"  (seen {n['prior_mentions']}x before)" if n.get('prior_mentions') else ''
            g = n.get('grade')
            gtxt = f" grade {g['letter']}" if g else ''
            verdict = (n.get('conviction_adjustment') or '').split('—')[0].strip() or 'n/a'
            print(f"  - {n['title']}  [entropy {n['entropy_risk']}/10; {verdict}{gtxt}]{seen}")
            if n['long_tickers']:
                rets = {r['ticker']: r for r in n.get('returns', [])}
                parts = []
                for t in n['long_tickers']:
                    r = rets.get(t)
                    parts.append(f"{t} 20d {_pct(r['excess_h20'])} / 60d {_pct(r['excess_h60'])}" if r else f"{t} (no prices)")
                print("      longs: " + "; ".join(parts))


def main():
    p = argparse.ArgumentParser(description="RedHood paginated historical timeline")
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--page', type=int, default=1)
    p.add_argument('--size', type=int, default=DEFAULT_PAGE_SIZE)
    p.add_argument('--context', action='store_true', help='Print the prompt context block and exit')
    p.add_argument('--html', nargs='?', const='', metavar='PATH', help='Write the HTML timeline (default docs/timeline.html)')
    p.add_argument('--flag', action='store_true', help='Compute prior_mentions / continuation_of for all narratives')
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    if args.flag:
        flag_continuations(conn, verbose=True)
    if args.context:
        print(recent_context(conn))
    elif args.html is not None:
        out = write_html(conn, args.html or None)
        print(f"Timeline written to {out}")
    elif not args.flag:
        _print_page(get_page(conn, args.page, args.size))
    conn.close()


if __name__ == '__main__':
    main()
