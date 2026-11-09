/* ===========================================================================
   util.js — formatting, DOM helpers, the data adapter, indicator maths.
   The adapter is the seam between STATIC (bundle baked in) and LIVE
   (bundle fetched from redhood_terminal.py --serve); nothing above it cares.
   =========================================================================== */
'use strict';

const RH = (window.RH = {});
const CFG = window.RH_CONFIG || { mode: 'static', api: '' };

/* ───────────────────────────── dom helpers ────────────────────────────── */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ───────────────────────────── formatting ─────────────────────────────── */
const EPOCH_MS = 86400000;

/** integer days-since-epoch -> Date (UTC midnight) */
const dayToDate = (d) => new Date(d * EPOCH_MS);
const dayToISO = (d) => new Date(d * EPOCH_MS).toISOString().slice(0, 10);
const isoToDay = (iso) => Math.floor(Date.parse(iso + 'T00:00:00Z') / EPOCH_MS);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDay(d, style) {
  const t = dayToDate(d);
  const mon = MONTHS[t.getUTCMonth()];
  if (style === 'month') return `${mon} ${String(t.getUTCFullYear()).slice(2)}`;
  if (style === 'year') return String(t.getUTCFullYear());
  if (style === 'long') return `${t.getUTCDate()} ${mon} ${t.getUTCFullYear()}`;
  return `${mon} ${t.getUTCDate()}`;
}

/** price: keeps precision useful across BTC and penny names alike */
function fmtPx(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 10000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (a >= 100) return v.toFixed(2);
  if (a >= 1) return v.toFixed(2);
  if (a >= 0.01) return v.toFixed(4);
  return v.toPrecision(3);
}

/** decimal fraction -> signed percent string */
function fmtPct(v, nd = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = (v * 100).toFixed(nd);
  return (v > 0 ? '+' : '') + s + '%';
}

function fmtNum(v, nd = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return Number(v).toFixed(nd);
}

function fmtVol(v) {
  if (!v) return '—';
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return String(v);
}

/** sign class for colour + the glyph that carries sign without colour */
const dirClass = (v) => (v === null || v === undefined || Number.isNaN(v) ? 'flat' : v > 0 ? 'up' : v < 0 ? 'dn' : 'flat');
const dirMark = (v) => (v === null || v === undefined || Number.isNaN(v) ? '' : v > 0 ? '▲' : v < 0 ? '▼' : '·');

function fmtAgo(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (Number.isNaN(t)) return iso.slice(0, 16).replace('T', ' ');
  const s = (Date.now() - t) / 1000;
  if (s < 90) return 'now';
  if (s < 5400) return Math.round(s / 60) + 'm';
  if (s < 172800) return Math.round(s / 3600) + 'h';
  return Math.round(s / 86400) + 'd';
}

const fmtStamp = (iso) => (iso || '').slice(0, 16).replace('T', ' ');

/* ──────────────────────────── theme palette ───────────────────────────── */
/** Live read of the CSS custom properties, so JS charts and CSS never drift. */
function palette() {
  const cs = getComputedStyle(document.documentElement);
  const g = (n) => cs.getPropertyValue(n).trim();
  return {
    ink: g('--ink'), ink2: g('--ink-2'), ink3: g('--ink-3'),
    wire: g('--wire'), wire2: g('--wire-2'),
    panel: g('--panel'), panel2: g('--panel-2'), bg: g('--bg'),
    brand: g('--brand'), gold: g('--gold'),
    up: g('--up'), down: g('--down'), neutral: g('--neutral'),
    cat: [g('--c1'), g('--c2'), g('--c3'), g('--c4'), g('--c5')],
    grade: [g('--g1'), g('--g2'), g('--g3'), g('--g4'), g('--g5')],
    status: { good: g('--good'), warn: g('--warn'), serious: g('--serious'), critical: g('--critical') },
  };
}

const REGIME_COLOR = (label, P) => ({
  TRENDING: P.status.good,
  CHOPPY: P.status.warn,
  TRANSITION: P.status.serious,
  CRISIS: P.status.critical,
}[String(label || '').toUpperCase()] || P.neutral);

/* ───────────────────────────── maths helpers ──────────────────────────── */
function sma(arr, n) {
  const out = new Array(arr.length).fill(null);
  let sum = 0, count = 0;
  for (let i = 0; i < arr.length; i++) {
    const v = arr[i];
    if (v !== null) { sum += v; count++; }
    if (i >= n) { const old = arr[i - n]; if (old !== null) { sum -= old; count--; } }
    if (i >= n - 1 && count === n) out[i] = sum / n;
  }
  return out;
}

function stdevBands(arr, n, k = 2) {
  const mid = sma(arr, n), up = [], lo = [];
  for (let i = 0; i < arr.length; i++) {
    if (mid[i] === null) { up.push(null); lo.push(null); continue; }
    let s = 0, c = 0;
    for (let j = i - n + 1; j <= i; j++) { if (arr[j] !== null) { s += (arr[j] - mid[i]) ** 2; c++; } }
    const sd = c ? Math.sqrt(s / c) : 0;
    up.push(mid[i] + k * sd); lo.push(mid[i] - k * sd);
  }
  return { mid, up, lo };
}

const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
function median(a) {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** "nice" axis ticks: 1 / 2 / 2.5 / 5 x 10^n */
function niceTicks(min, max, target = 5) {
  if (!(isFinite(min) && isFinite(max)) || min === max) return [min];
  const raw = (max - min) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 4 ? 2.5 : norm < 7 ? 5 : 10) * mag;
  const out = [];
  for (let t = Math.ceil(min / step) * step; t <= max + step * 0.001; t += step) out.push(+t.toFixed(10));
  return out;
}

/* ───────────────────────────── data adapter ───────────────────────────── */
/**
 * One interface over both shapes:
 *   static — window.RH_BUNDLE is baked into the page
 *   live   — GET {api}/bundle, and optional GET {api}/quotes?symbols=…
 */
const Source = {
  mode: CFG.mode || 'static',
  bundle: null,

  async load() {
    if (window.RH_BUNDLE) { this.bundle = window.RH_BUNDLE; this.mode = 'static'; return this.bundle; }
    const r = await fetch(`${CFG.api || '/api'}/bundle`, { headers: { accept: 'application/json' } });
    if (!r.ok) throw new Error(`bundle fetch failed: ${r.status} ${r.statusText}`);
    this.bundle = await r.json();
    this.mode = 'live';
    return this.bundle;
  },

  /** Polled quotes; resolves to {} in static mode so callers need no branch. */
  async quotes(symbols) {
    if (this.mode !== 'live' || !symbols || !symbols.length) return {};
    try {
      const r = await fetch(`${CFG.api || '/api'}/quotes?symbols=${encodeURIComponent(symbols.join(','))}`);
      if (!r.ok) return {};
      return (await r.json()).quotes || {};
    } catch { return {}; }
  },

  get live() { return this.mode === 'live'; },
};

/**
 * Series accessor. Decodes the wire format once per symbol and caches it:
 *   d0 + gap deltas -> absolute day numbers
 *   volume in thousands -> shares
 * Close-only symbols are normalised to the OHLC shape so the chart needs no
 * special case; hasOHLC says whether candles are meaningful.
 */
const _seriesCache = new Map();

function getSeries(ticker) {
  if (_seriesCache.has(ticker)) return _seriesCache.get(ticker);
  const s = Source.bundle?.series?.[ticker];
  if (!s) return null;

  const n = s.c.length;
  const d = new Int32Array(n);
  d[0] = s.d0;
  for (let i = 1; i < n; i++) d[i] = d[i - 1] + (s.d[i - 1] || 1);

  const out = {
    ticker, n, d,
    c: s.c,
    o: s.ohlc ? s.o : s.c,
    h: s.ohlc ? s.h : s.c,
    l: s.ohlc ? s.l : s.c,
    v: s.v ? s.v.map((k) => k * 1000) : null,
    hasOHLC: !!s.ohlc,
    hasVol: !!(s.v && s.v.some((k) => k > 0)),
  };
  _seriesCache.set(ticker, out);
  return out;
}

Object.assign(RH, {
  $, $$, el, esc, CFG, Source, getSeries, palette, REGIME_COLOR,
  dayToDate, dayToISO, isoToDay, fmtDay, fmtPx, fmtPct, fmtNum, fmtVol,
  fmtAgo, fmtStamp, dirClass, dirMark, sma, stdevBands, mean, median, niceTicks,
});
