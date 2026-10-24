"""
RedHood Systems - Signal Card History
=====================================
Accumulates every signal card from every published report into one archive
(docs/cards_history.json) and renders a searchable history page
(docs/cards.html).

Cards are read back out of the report HTML itself, so the live publish path
and a backfill over the archived reports share one code path. Reports that
predate signal cards contribute link-only entries from their links table.

Usage:
    python card_history.py                 # rebuild from docs/redhood_reads_*.html
    python card_history.py report.html ... # merge specific reports
"""

import glob
import html as H
import json
import os
import re
import sys
from datetime import datetime

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
HISTORY_JSON = 'cards_history.json'
HISTORY_HTML = 'cards.html'

_CARD_RE = re.compile(
    r'<div class="tweet-embed"[^>]*?data-handle="(?P<handle>[^"]*)"[^>]*?'
    r'data-cited="(?P<cited>[01])"[^>]*?data-ts="(?P<ts>[^"]*)"[^>]*>'
    r'.*?<span class="tw-handle">(?P<author>.*?)</span>'
    r'.*?<div class="tw-body">(?P<text>.*?)</div>'
    r'\s*<a class="tw-link" href="(?P<url>[^"]*)"', re.S)
_ROW_RE = re.compile(
    r'<tr(?: id="feed-\d+")?>(?:<td class="feed-num">\d+</td>)?'
    r'<td class="ts">(?P<ts>[^<]*)</td><td class="author">(?P<author>[^<]*)</td>'
    r'<td><a href="(?P<url>[^"]*)"', re.S)
_REPORT_TS_RE = re.compile(r'redhood_reads_(\d{8}_\d{6})')


def _key(url: str) -> str:
    """Dedupe key: the post URL without Nitter's #m fragment or a trailing slash."""
    return url.split('#', 1)[0].rstrip('/')


def _source(url: str) -> str:
    if 't.me/' in url:
        return 'telegram'
    if 'x.com/' in url or 'twitter.com/' in url:
        return 'twitter'
    return 'rss'


def _norm_ts(ts: str) -> str:
    return ts.strip().replace(' ', 'T')[:19]


def report_time(name: str) -> str:
    """Run time encoded in a report filename, else now."""
    m = _REPORT_TS_RE.search(name)
    if m:
        return datetime.strptime(m.group(1), '%Y%m%d_%H%M%S').isoformat()
    return datetime.now().replace(microsecond=0).isoformat()


def extract_cards(report_html: str) -> list[dict]:
    """Pull signal cards (and link-only table rows) out of a report's HTML."""
    cards = []
    for m in _CARD_RE.finditer(report_html):
        url = H.unescape(m['url'])
        cards.append({
            'url': url, 'author': H.unescape(m['author']), 'handle': H.unescape(m['handle']),
            'ts': _norm_ts(m['ts']), 'text': H.unescape(m['text']),
            'cited': m['cited'] == '1', 'source': _source(url),
        })
    for m in _ROW_RE.finditer(report_html):
        url = H.unescape(m['url'])
        author = H.unescape(m['author'])
        cards.append({
            'url': url, 'author': author, 'handle': author.lstrip('@').lower(),
            'ts': _norm_ts(m['ts']), 'text': '', 'cited': False, 'source': _source(url),
        })
    return [c for c in cards if c['url']]


def merge(history: dict, cards: list[dict], report: str, seen_at: str) -> int:
    """Fold one report's cards into history in place. Returns the count of new cards."""
    entries = history.setdefault('cards', {})
    added = 0
    for c in cards:
        k = _key(c['url'])
        e = entries.get(k)
        if e is None:
            entries[k] = {**c, 'first_seen': seen_at, 'last_seen': seen_at, 'reports': [report]}
            added += 1
            continue
        if report not in e['reports']:
            e['reports'].append(report)
        e['first_seen'] = min(e['first_seen'], seen_at)
        e['last_seen'] = max(e['last_seen'], seen_at)
        e['cited'] = e['cited'] or c['cited']
        if len(c['text']) > len(e['text']):  # a full card beats a link-only row
            e['text'] = c['text']
    if cards:
        history['updated'] = max(history.get('updated', ''), seen_at)
    return added


def load(text: str | None) -> dict:
    return json.loads(text) if text else {'cards': {}}


def dump(history: dict) -> str:
    return json.dumps(history, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def render_page(history: dict) -> str:
    """Self-contained history page; cards render client-side from embedded JSON."""
    cards = sorted(history.get('cards', {}).values(), key=lambda c: c['ts'], reverse=True)
    rows = [[c['ts'], c['author'], c['text'], c['url'], int(c['cited']), c['source'],
             len(c['reports'])] for c in cards]
    data = json.dumps(rows, ensure_ascii=False).replace('</', '<\\/')
    return (_PAGE
            .replace('%%DATA%%', data)
            .replace('%%TOTAL%%', str(len(rows)))
            .replace('%%UPDATED%%', H.escape(history.get('updated', '')[:16].replace('T', ' '))))


def rebuild(paths: list[str], history: dict | None = None) -> dict:
    history = history if history is not None else {'cards': {}}
    for p in sorted(paths):
        with open(p, encoding='utf-8') as f:
            name = os.path.basename(p)
            merge(history, extract_cards(f.read()), name, report_time(name))
    return history


_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RedHood Card History</title>
<style>
  :root {
    --gold: #B8975A; --cream: #F5F0E8; --tangerine: #F47B3A; --dark: #0A0A0A;
    --wire: rgba(255,255,255,0.08); --muted: rgba(245,240,232,0.5); --card: #141414;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--dark); color: var(--cream);
         font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  header { position: sticky; top: 0; z-index: 2; background: rgba(10,10,10,0.96);
           border-bottom: 1px solid var(--wire); padding: 14px 16px; }
  h1 { margin: 0 0 4px; font-size: 18px; letter-spacing: 0.04em; }
  h1 span { color: #C1121F; }
  .sub { color: var(--muted); font-size: 11px; }
  .sub a { color: var(--tangerine); text-decoration: none; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
  .bar input, .bar select, .bar button { background: rgba(0,0,0,0.4); color: var(--cream);
         border: 1px solid var(--wire); border-radius: 6px; padding: 8px 10px; font: inherit; }
  .bar input { flex: 1 1 200px; min-width: 0; }
  .bar button.on { color: var(--gold); border-color: rgba(184,151,90,0.6); }
  .count { color: var(--muted); font-size: 11px; margin-left: auto; }
  main { padding: 8px 16px 40px; max-width: 1400px; margin: 0 auto; }
  h2 { font-size: 12px; letter-spacing: 0.14em; color: var(--muted); margin: 22px 0 10px;
       border-bottom: 1px solid var(--wire); padding-bottom: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 10px; }
  .card { background: var(--card); border: 1px solid var(--wire); border-left: 2px solid var(--wire);
          border-radius: 6px; padding: 12px; display: flex; flex-direction: column; min-width: 0; }
  .card.cited { border-left-color: var(--gold); }
  .head { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; }
  .who { color: var(--tangerine); overflow: hidden; text-overflow: ellipsis; }
  .ts { color: var(--muted); white-space: nowrap; }
  .tag { color: var(--gold); font-size: 9px; letter-spacing: 0.16em; margin-right: 6px; }
  .body { margin: 8px 0; flex: 1; overflow-wrap: anywhere; color: rgba(245,240,232,0.85); }
  .body.empty { color: var(--muted); font-style: italic; }
  .foot { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); }
  .foot a { color: var(--tangerine); text-decoration: none; letter-spacing: 0.1em; }
  #more { display: block; margin: 24px auto; }
  @media (max-width: 600px) { header { position: static; } }
</style>
</head>
<body>
<header>
  <h1>Red<span>Hood</span> Card History</h1>
  <div class="sub">%%TOTAL%% cards &middot; updated %%UPDATED%% &middot; <a href="latest.html">Latest report &rarr;</a></div>
  <div class="bar">
    <input id="q" type="search" placeholder="Search text or handles" autocomplete="off">
    <select id="acct" aria-label="Account"><option value="">All accounts</option></select>
    <select id="src" aria-label="Source">
      <option value="">All sources</option><option value="twitter">X</option>
      <option value="telegram">Telegram</option><option value="rss">RSS</option>
    </select>
    <button id="cited" type="button">Cited only</button>
    <span id="count" class="count"></span>
  </div>
</header>
<main><div id="out"></div><div class="bar"><button id="more" type="button">Show more</button></div></main>
<script>
(function(){
  "use strict";
  var ROWS = %%DATA%%;  // [ts, author, text, url, cited, source, reportCount]
  var PAGE = 120, shown = PAGE, citedOnly = false;
  var q = document.getElementById('q'), acct = document.getElementById('acct'),
      src = document.getElementById('src'), citedBtn = document.getElementById('cited'),
      out = document.getElementById('out'), more = document.getElementById('more'),
      count = document.getElementById('count');
  var LINK = {twitter: 'View on X', telegram: 'View on Telegram', rss: 'Read post'};

  var authors = {};
  ROWS.forEach(function(r){ authors[r[1]] = (authors[r[1]] || 0) + 1; });
  Object.keys(authors).sort(function(a, b){ return a.toLowerCase() < b.toLowerCase() ? -1 : 1; })
    .forEach(function(a){
      var o = document.createElement('option'); o.value = a; o.textContent = a + ' (' + authors[a] + ')';
      acct.appendChild(o);
    });

  function el(tag, cls, text){
    var e = document.createElement(tag); if (cls) e.className = cls;
    if (text != null) e.textContent = text; return e;
  }
  function card(r){
    var c = el('div', 'card' + (r[4] ? ' cited' : ''));
    var head = el('div', 'head'); head.appendChild(el('span', 'who', r[1]));
    var ts = el('span', 'ts');
    if (r[4]) ts.appendChild(el('span', 'tag', '◆ CITED'));
    ts.appendChild(document.createTextNode(r[0].slice(11, 16)));
    head.appendChild(ts); c.appendChild(head);
    c.appendChild(el('div', 'body' + (r[2] ? '' : ' empty'), r[2] || 'Link only (no text captured)'));
    var foot = el('div', 'foot');
    foot.appendChild(el('span', '', r[6] > 1 ? 'in ' + r[6] + ' reports' : ''));
    var a = el('a', '', (LINK[r[5]] || 'Open') + ' →');
    if (/^https?:\/\//.test(r[3])) { a.href = r[3]; a.target = '_blank'; a.rel = 'noopener'; }
    foot.appendChild(a); c.appendChild(foot);
    return c;
  }
  function filtered(){
    var term = q.value.trim().toLowerCase(), who = acct.value, s = src.value;
    return ROWS.filter(function(r){
      if (citedOnly && !r[4]) return false;
      if (who && r[1] !== who) return false;
      if (s && r[5] !== s) return false;
      return !term || (r[1] + ' ' + r[2]).toLowerCase().indexOf(term) !== -1;
    });
  }
  function render(){
    var rows = filtered(), day = null, grid = null;
    out.textContent = '';
    rows.slice(0, shown).forEach(function(r){
      var d = r[0].slice(0, 10);
      if (d !== day) {
        day = d; out.appendChild(el('h2', '', d));
        grid = el('div', 'grid'); out.appendChild(grid);
      }
      grid.appendChild(card(r));
    });
    count.textContent = Math.min(shown, rows.length) + ' / ' + rows.length + ' shown';
    more.style.display = rows.length > shown ? '' : 'none';
  }
  function reset(){ shown = PAGE; render(); }
  q.addEventListener('input', reset);
  acct.addEventListener('change', reset);
  src.addEventListener('change', reset);
  citedBtn.addEventListener('click', function(){
    citedOnly = !citedOnly; citedBtn.classList.toggle('on', citedOnly); reset();
  });
  more.addEventListener('click', function(){ shown += PAGE; render(); });
  render();
})();
</script>
</body>
</html>
"""


def main(argv: list[str]) -> None:
    json_path = os.path.join(DOCS_DIR, HISTORY_JSON)
    if argv:
        history = None
        if os.path.exists(json_path):
            with open(json_path, encoding='utf-8') as f:
                history = load(f.read())
        history = rebuild(argv, history)
    else:
        history = rebuild(glob.glob(os.path.join(DOCS_DIR, 'redhood_reads_*.html')))
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(dump(history))
    with open(os.path.join(DOCS_DIR, HISTORY_HTML), 'w', encoding='utf-8') as f:
        f.write(render_page(history))
    cards = history['cards'].values()
    print(f"Card history: {len(cards)} cards "
          f"({sum(1 for c in cards if c['text'])} with text, {sum(1 for c in cards if c['cited'])} cited)")


if __name__ == '__main__':
    main(sys.argv[1:])
