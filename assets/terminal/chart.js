/* ===========================================================================
   chart.js — the price chart engine, plus the small multiples used by the
   lower panels. Canvas, hand-rolled, no dependencies: the page stays a single
   self-contained file that works offline and off a file:// URL.

   Direction is never carried by colour alone: up candles are hollow, down
   candles are filled, and every readout prints a signed number.
   =========================================================================== */
'use strict';

(function (RH) {
  const { el, fmtPx, fmtPct, fmtVol, fmtDay, dayToISO, sma, stdevBands,
          niceTicks, palette, getSeries } = RH;

  const PAD = { top: 4, right: 64, bottom: 18, left: 2 };
  const VOL_FRAC = 0.20;          // share of the plot height given to volume
  const MIN_BARS = 12;
  const MA_SPECS = [[20, 0], [50, 1], [200, 3]];   // [period, categorical slot]

  class Chart {
    constructor(canvas, box) {
      this.cv = canvas;
      this.box = box;
      this.ctx = canvas.getContext('2d');
      this.series = null;
      this.bench = null;                 // SPY series, for relative mode
      this.pins = [];                    // narrative markers
      this.i0 = 0; this.i1 = 0;          // visible index window
      this.hover = null;                 // hovered index
      this.hoverPin = null;
      this.style = 'candle';
      this.opts = { ma: true, bb: false, vol: true, pins: true, log: false, rel: false };
      this.onPinClick = null;
      this.onHover = null;
      this._drag = null;
      this._raf = null;

      this._bind();
      this._measure();
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(box);
    }

    /* ─────────────────────────── data & view ─────────────────────────── */
    setSeries(series, { pins = [], bench = null, keepView = false } = {}) {
      const prevSpan = this.i1 - this.i0;
      this.series = series;
      this.pins = pins;
      this.bench = bench;
      if (!series) return this.draw();
      if (keepView && prevSpan > 0) {
        this.i1 = series.n - 1;
        this.i0 = Math.max(0, this.i1 - prevSpan);
      } else {
        this.setRange(252);
      }
      this.resize();        // synchronous: a new symbol always lands on screen
    }

    /** bars = number of trailing bars, 0 = all, 'ytd' = since Jan 1 */
    setRange(bars) {
      const s = this.series;
      if (!s) return;
      this.i1 = s.n - 1;
      if (bars === 'ytd') {
        const y = new Date(s.d[s.n - 1] * 86400000).getUTCFullYear();
        const jan1 = Math.floor(Date.parse(`${y}-01-01T00:00:00Z`) / 86400000);
        let i = s.d.findIndex((d) => d >= jan1);
        if (i < 0) i = 0;
        this.i0 = Math.max(0, i - 1);
      } else if (!bars || bars <= 0) {
        this.i0 = 0;
      } else {
        this.i0 = Math.max(0, this.i1 - bars + 1);
      }
      if (this.i1 - this.i0 < MIN_BARS) this.i0 = Math.max(0, this.i1 - MIN_BARS);
      this.draw();
    }

    set(opt, val) {
      if (opt === 'style') this.style = val;
      else this.opts[opt] = val;
      // Synchronous: callers read back _data for the legend on the next line,
      // and a deferred frame would hand them the previous mode's numbers.
      this.redraw();
    }

    /** Draw now, cancelling any frame already queued. */
    redraw() {
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
      this._draw();
    }

    pan(bars) {
      const s = this.series; if (!s) return;
      const span = this.i1 - this.i0;
      let i0 = this.i0 + bars, i1 = this.i1 + bars;
      if (i0 < 0) { i0 = 0; i1 = span; }
      if (i1 > s.n - 1) { i1 = s.n - 1; i0 = i1 - span; }
      this.i0 = Math.max(0, i0); this.i1 = i1;
      this.draw();
    }

    zoom(factor, anchorIdx) {
      const s = this.series; if (!s) return;
      const span = this.i1 - this.i0;
      const next = Math.max(MIN_BARS, Math.min(s.n - 1, Math.round(span * factor)));
      const a = anchorIdx ?? (this.i0 + span / 2);
      const frac = span > 0 ? (a - this.i0) / span : 0.5;
      let i0 = Math.round(a - frac * next);
      let i1 = i0 + next;
      if (i0 < 0) { i0 = 0; i1 = next; }
      if (i1 > s.n - 1) { i1 = s.n - 1; i0 = Math.max(0, i1 - next); }
      this.i0 = i0; this.i1 = i1;
      this.draw();
    }

    /* ─────────────────────────── geometry ───────────────────────────── */
    /** Measure only. Separated from resize() so the first paint never has to
        wait on requestAnimationFrame, which a hidden or throttled tab
        may not run at all. */
    _measure() {
      const r = this.box.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.w = Math.max(80, Math.round(r.width));
      this.h = Math.max(80, Math.round(r.height));
      this.cv.width = Math.round(this.w * dpr);
      this.cv.height = Math.round(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    resize() {
      this._measure();
      this.redraw();
    }

    get plot() {
      const showVol = this.opts.vol && this.series?.hasVol && !this.opts.rel;
      const x0 = PAD.left, x1 = this.w - PAD.right;
      const yTop = PAD.top, yBot = this.h - PAD.bottom;
      const volH = showVol ? Math.max(18, (yBot - yTop) * VOL_FRAC) : 0;
      return { x0, x1, yTop, yBot, priceBot: yBot - volH - (showVol ? 6 : 0), volTop: yBot - volH, volH, showVol };
    }

    /** index -> x centre */
    xOf(i) {
      const { x0, x1 } = this.plot;
      const n = this.i1 - this.i0 + 1;
      const bw = (x1 - x0) / n;
      return x0 + (i - this.i0 + 0.5) * bw;
    }

    xToIndex(px) {
      const { x0, x1 } = this.plot;
      const n = this.i1 - this.i0 + 1;
      const bw = (x1 - x0) / n;
      return Math.max(this.i0, Math.min(this.i1, Math.round(this.i0 + (px - x0) / bw - 0.5)));
    }

    /** value -> y, honouring the log toggle */
    yOf(v) {
      const p = this.plot, { lo, hi } = this._scale;
      if (v === null || v === undefined || Number.isNaN(v)) return null;
      const t = this.opts.log
        ? (Math.log(Math.max(v, 1e-9)) - Math.log(Math.max(lo, 1e-9))) / (Math.log(Math.max(hi, 1e-9)) - Math.log(Math.max(lo, 1e-9)))
        : (v - lo) / (hi - lo);
      return p.priceBot - t * (p.priceBot - p.yTop);
    }

    yToValue(py) {
      const p = this.plot, { lo, hi } = this._scale;
      const t = (p.priceBot - py) / (p.priceBot - p.yTop);
      return this.opts.log
        ? Math.exp(Math.log(Math.max(lo, 1e-9)) + t * (Math.log(Math.max(hi, 1e-9)) - Math.log(Math.max(lo, 1e-9))))
        : lo + t * (hi - lo);
    }

    /** The plotted arrays for the current mode (absolute price or vs-SPY). */
    _plotted() {
      const s = this.series;
      if (!this.opts.rel || !this.bench) {
        return { o: s.o, h: s.h, l: s.l, c: s.c, candles: s.hasOHLC && this.style === 'candle' };
      }
      // Relative mode: both legs indexed to 0% at the left edge of the view.
      const byDay = new Map();
      for (let i = 0; i < this.bench.n; i++) byDay.set(this.bench.d[i], this.bench.c[i]);
      /** Latest benchmark close on or before `day`. Bench days are ascending. */
      const benchAt = (day) => {
        for (let i = this.bench.n - 1; i >= 0; i--) {
          if (this.bench.d[i] <= day && this.bench.c[i]) return this.bench.c[i];
        }
        return null;
      };
      const base = s.c[this.i0];
      // The benchmark does not necessarily trade on this symbol's left-edge
      // day - BTC-USD runs through weekends, a .TO listing trades on US
      // holidays. An exact-day baseline would then be null and null every
      // plotted point, blanking the whole chart, so fall back to the most
      // recent benchmark bar at or before that day.
      const bBase = benchAt(s.d[this.i0]);
      const c = s.c.map((v, i) => {
        const b = byDay.get(s.d[i]);
        if (!v || !base || !b || !bBase) return null;
        return (v / base) / (b / bBase) - 1;
      });
      return { o: c, h: c, l: c, c, candles: false, rel: true };
    }

    _computeScale(P) {
      const s = this.series, d = this._plotted();
      let lo = Infinity, hi = -Infinity;
      for (let i = this.i0; i <= this.i1; i++) {
        // Same close-only fallback the candle loop uses, so a bar missing its
        // high/low still pulls the scale around the price that gets drawn.
        const c = d.c[i], h = d.h[i] ?? c, l = d.l[i] ?? c;
        if (h !== null && h > hi) hi = h;
        if (l !== null && l < lo) lo = l;
      }
      if (this.opts.ma && !d.rel) {
        for (const [n] of MA_SPECS) {
          const m = this._ma(n);
          for (let i = this.i0; i <= this.i1; i++) {
            if (m[i] === null) continue;
            if (m[i] > hi) hi = m[i];
            if (m[i] < lo) lo = m[i];
          }
        }
      }
      if (this.opts.bb && !d.rel) {
        const b = this._bb();
        for (let i = this.i0; i <= this.i1; i++) {
          if (b.up[i] !== null && b.up[i] > hi) hi = b.up[i];
          if (b.lo[i] !== null && b.lo[i] < lo) lo = b.lo[i];
        }
      }
      if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
      if (lo === hi) { lo -= 1; hi += 1; }
      const padv = (hi - lo) * 0.06;
      this._scale = { lo: d.rel ? lo - padv : Math.max(lo - padv, this.opts.log ? 1e-6 : -Infinity), hi: hi + padv };
      this._data = d;

      let vmax = 0;
      if (this.plot.showVol && s.v) {
        for (let i = this.i0; i <= this.i1; i++) vmax = Math.max(vmax, s.v[i] || 0);
      }
      this._vmax = vmax || 1;
    }

    _ma(n) {
      this._maCache = this._maCache || {};
      const key = `${this.series.ticker}:${n}`;
      if (!this._maCache[key]) this._maCache[key] = sma(this.series.c, n);
      return this._maCache[key];
    }

    _bb() {
      const key = `${this.series.ticker}:bb`;
      this._bbCache = this._bbCache || {};
      if (!this._bbCache[key]) this._bbCache[key] = stdevBands(this.series.c, 20, 2);
      return this._bbCache[key];
    }

    /* ───────────────────────────── drawing ─────────────────────────── */
    draw() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = null; this._draw(); });
    }

    _draw() {
      const ctx = this.ctx;
      if (!this.w) this._measure();
      const P = palette();
      ctx.clearRect(0, 0, this.w, this.h);
      ctx.fillStyle = P.panel;
      ctx.fillRect(0, 0, this.w, this.h);

      if (!this.series || !this.series.n) return;
      if (this.i1 <= this.i0) this.setRange(252);
      this._computeScale(P);

      this._grid(P);
      if (this.opts.bb && !this._data.rel) this._bands(P);
      if (this._data.candles) this._candles(P); else this._line(P);
      if (this.opts.ma && !this._data.rel) this._mas(P);
      if (this.plot.showVol) this._volume(P);
      if (this.opts.pins) this._pins(P);
      this._axes(P);
      this._crosshair(P);
    }

    _grid(P) {
      const ctx = this.ctx, p = this.plot;
      ctx.save();
      ctx.strokeStyle = P.wire;
      ctx.lineWidth = 1;
      for (const t of niceTicks(this._scale.lo, this._scale.hi, 5)) {
        const y = Math.round(this.yOf(t)) + 0.5;
        if (y < p.yTop || y > p.priceBot) continue;
        ctx.beginPath(); ctx.moveTo(p.x0, y); ctx.lineTo(p.x1, y); ctx.stroke();
      }
      for (const { i } of this._timeTicks()) {
        const x = Math.round(this.xOf(i)) + 0.5;
        ctx.beginPath(); ctx.moveTo(x, p.yTop); ctx.lineTo(x, p.yBot); ctx.stroke();
      }
      if (this._data.rel) {                           // zero line in relative mode
        const y = this.yOf(0);
        if (y !== null && y > p.yTop && y < p.priceBot) {
          ctx.strokeStyle = P.wire2;
          ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(p.x0, y); ctx.lineTo(p.x1, y); ctx.stroke();
          ctx.setLineDash([]);
        }
      }
      ctx.restore();
    }

    _candles(P) {
      const ctx = this.ctx, d = this._data, s = this.series;
      const n = this.i1 - this.i0 + 1;
      const bw = (this.plot.x1 - this.plot.x0) / n;
      const body = Math.max(1, Math.min(bw * 0.68, 14));
      const thin = bw < 3.2;
      ctx.save();
      ctx.lineWidth = 1;
      for (let i = this.i0; i <= this.i1; i++) {
        const c = d.c[i];
        if (c === null) continue;
        // A series is marked ohlc=1 once over half its bars have an open, so
        // individual bars can still be close-only. Falling back to the close
        // keeps those drawn as a flat mark; without it null reaches yOf() as 0
        // and the bar paints a wick across the whole plot.
        const o = d.o[i] ?? c, h = d.h[i] ?? c, l = d.l[i] ?? c;
        const up = c >= o;
        const col = up ? P.up : P.down;
        const x = Math.round(this.xOf(i)) + 0.5;
        const yH = this.yOf(h), yL = this.yOf(l), yO = this.yOf(o), yC = this.yOf(c);

        ctx.strokeStyle = col;
        ctx.beginPath(); ctx.moveTo(x, yH); ctx.lineTo(x, yL); ctx.stroke();   // wick

        if (thin) continue;
        const top = Math.min(yO, yC), bot = Math.max(yO, yC);
        const hgt = Math.max(1, bot - top);
        const bx = Math.round(x - body / 2);
        // Hollow body = up, filled = down: direction without relying on hue.
        if (up) {
          ctx.fillStyle = P.panel;
          ctx.fillRect(bx, top, Math.round(body), hgt);
          ctx.strokeStyle = col;
          ctx.strokeRect(bx + 0.5, Math.round(top) + 0.5, Math.round(body) - 1, Math.max(1, Math.round(hgt) - 1));
        } else {
          ctx.fillStyle = col;
          ctx.fillRect(bx, top, Math.round(body), hgt);
        }
      }
      ctx.restore();
    }

    _line(P) {
      const ctx = this.ctx, d = this._data, p = this.plot;
      const last = d.c[this.i1], first = d.c[this.i0];
      const rising = (last ?? 0) >= (first ?? 0);
      const col = d.rel ? (rising ? P.up : P.down) : P.gold;

      ctx.save();
      // area fill, then the 2px stroke on top
      const grad = ctx.createLinearGradient(0, p.yTop, 0, p.priceBot);
      grad.addColorStop(0, col + '33');
      grad.addColorStop(1, col + '00');
      ctx.beginPath();
      let started = false, firstX = null;
      for (let i = this.i0; i <= this.i1; i++) {
        const v = d.c[i]; if (v === null) continue;
        const x = this.xOf(i), y = this.yOf(v);
        if (!started) { ctx.moveTo(x, y); started = true; firstX = x; } else ctx.lineTo(x, y);
      }
      if (started) {
        const lastX = this.xOf(this.i1);
        ctx.lineTo(lastX, p.priceBot); ctx.lineTo(firstX, p.priceBot); ctx.closePath();
        ctx.fillStyle = grad; ctx.fill();
      }
      ctx.beginPath();
      started = false;
      for (let i = this.i0; i <= this.i1; i++) {
        const v = d.c[i]; if (v === null) continue;
        const x = this.xOf(i), y = this.yOf(v);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineJoin = 'round';
      ctx.stroke();
      ctx.restore();
    }

    _mas(P) {
      const ctx = this.ctx;
      ctx.save(); ctx.lineWidth = 1.25;
      for (const [n, slot] of MA_SPECS) {
        const m = this._ma(n);
        ctx.strokeStyle = P.cat[slot];
        ctx.beginPath();
        let started = false;
        for (let i = this.i0; i <= this.i1; i++) {
          if (m[i] === null) { started = false; continue; }
          const x = this.xOf(i), y = this.yOf(m[i]);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    _bands(P) {
      const b = this._bb(), ctx = this.ctx;
      ctx.save();
      ctx.fillStyle = P.wire;
      ctx.beginPath();
      let started = false;
      for (let i = this.i0; i <= this.i1; i++) {
        if (b.up[i] === null) continue;
        const x = this.xOf(i), y = this.yOf(b.up[i]);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      for (let i = this.i1; i >= this.i0; i--) {
        if (b.lo[i] === null) continue;
        ctx.lineTo(this.xOf(i), this.yOf(b.lo[i]));
      }
      ctx.closePath(); ctx.fill();
      ctx.strokeStyle = P.ink3; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
      for (const key of ['up', 'lo']) {
        ctx.beginPath(); started = false;
        for (let i = this.i0; i <= this.i1; i++) {
          if (b[key][i] === null) continue;
          const x = this.xOf(i), y = this.yOf(b[key][i]);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();
    }

    _volume(P) {
      const ctx = this.ctx, p = this.plot, s = this.series, d = this._data;
      const n = this.i1 - this.i0 + 1;
      const bw = (p.x1 - p.x0) / n;
      const w = Math.max(1, Math.min(bw * 0.68, 14));
      ctx.save();
      for (let i = this.i0; i <= this.i1; i++) {
        const v = s.v[i]; if (!v) continue;
        const up = d.c[i] >= (d.o[i] ?? d.c[i]);
        const hgt = (v / this._vmax) * (p.volH - 2);
        ctx.fillStyle = (up ? P.up : P.down) + '66';
        ctx.fillRect(Math.round(this.xOf(i) - w / 2), p.yBot - hgt, Math.round(w), hgt);
      }
      ctx.strokeStyle = P.wire;
      ctx.beginPath(); ctx.moveTo(p.x0, p.volTop - 3.5); ctx.lineTo(p.x1, p.volTop - 3.5); ctx.stroke();
      ctx.restore();
    }

    /** Narrative markers: where the system actually had a thesis on this name. */
    _pins(P) {
      if (!this.pins.length) return;
      const ctx = this.ctx, p = this.plot;
      const d0 = this.series.d[this.i0], d1 = this.series.d[this.i1];
      this._pinHits = [];
      ctx.save();
      for (const pin of this.pins) {
        if (pin.day < d0 || pin.day > d1) continue;
        let i = this._indexForDay(pin.day);
        if (i === null) continue;
        const x = this.xOf(i);
        const y = p.priceBot - 2;
        const col = pin.color || P.gold;
        ctx.beginPath();
        ctx.moveTo(x, y - 8); ctx.lineTo(x - 4.2, y); ctx.lineTo(x + 4.2, y);
        ctx.closePath();
        ctx.fillStyle = col; ctx.fill();
        ctx.strokeStyle = P.panel; ctx.lineWidth = 1; ctx.stroke();
        ctx.strokeStyle = col + '55';
        ctx.setLineDash([2, 4]);
        ctx.beginPath(); ctx.moveTo(x, p.yTop); ctx.lineTo(x, y - 8); ctx.stroke();
        ctx.setLineDash([]);
        this._pinHits.push({ x, y, pin });
      }
      ctx.restore();
    }

    _indexForDay(day) {
      const d = this.series.d;
      let lo = 0, hi = d.length - 1, best = null;
      while (lo <= hi) {
        const m = (lo + hi) >> 1;
        if (d[m] === day) return m;
        if (d[m] < day) { best = m; lo = m + 1; } else hi = m - 1;
      }
      return best;
    }

    _timeTicks() {
      const s = this.series, out = [];
      const n = this.i1 - this.i0 + 1;
      const target = Math.max(2, Math.min(9, Math.floor((this.plot.x1 - this.plot.x0) / 78)));
      const step = Math.max(1, Math.floor(n / target));
      let lastLabel = '';
      for (let i = this.i0; i <= this.i1; i += step) {
        const style = n > 400 ? 'month' : n > 90 ? 'month' : 'day';
        const label = fmtDay(s.d[i], style);
        if (label === lastLabel) continue;
        lastLabel = label;
        out.push({ i, label });
      }
      return out;
    }

    _axes(P) {
      const ctx = this.ctx, p = this.plot;
      ctx.save();
      ctx.font = '9.5px var(--mono, monospace)';
      ctx.fillStyle = P.ink3;
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const rel = this._data.rel;
      for (const t of niceTicks(this._scale.lo, this._scale.hi, 5)) {
        const y = this.yOf(t);
        if (y < p.yTop || y > p.priceBot) continue;
        ctx.fillText(rel ? fmtPct(t, 1) : fmtPx(t), p.x1 + 5, y);
      }
      if (p.showVol) {
        ctx.fillText(fmtVol(this._vmax), p.x1 + 5, p.volTop + 5);
      }
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      for (const { i, label } of this._timeTicks()) {
        ctx.fillText(label, this.xOf(i), p.yBot + 4);
      }
      ctx.restore();
      this._lastTag(P);
    }

    _lastTag(P) {
      const ctx = this.ctx, p = this.plot, d = this._data;
      const v = d.c[this.i1];
      if (v === null || v === undefined) return;
      const y = this.yOf(v);
      if (y === null || y < p.yTop || y > p.priceBot) return;
      const txt = d.rel ? fmtPct(v, 1) : fmtPx(v);
      const up = d.c[this.i1] >= (d.o[this.i1] ?? d.c[this.i1]);
      ctx.save();
      ctx.font = '10px var(--mono, monospace)';
      const w = Math.max(ctx.measureText(txt).width + 8, 44);
      ctx.fillStyle = up ? P.up : P.down;
      ctx.fillRect(p.x1 + 1, y - 7, w, 14);
      ctx.strokeStyle = P.wire2;
      ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(p.x0, y + 0.5); ctx.lineTo(p.x1, y + 0.5); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#0A0A0A';
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText(txt, p.x1 + 5, y);
      ctx.restore();
    }

    _crosshair(P) {
      const i = this.hover;
      if (i === null || i === undefined) return;
      const ctx = this.ctx, p = this.plot, d = this._data;
      const x = Math.round(this.xOf(i)) + 0.5;
      ctx.save();
      ctx.strokeStyle = P.ink3;
      ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(x, p.yTop); ctx.lineTo(x, p.yBot); ctx.stroke();
      if (this._mouseY !== null && this._mouseY > p.yTop && this._mouseY < p.priceBot) {
        const y = Math.round(this._mouseY) + 0.5;
        ctx.beginPath(); ctx.moveTo(p.x0, y); ctx.lineTo(p.x1, y); ctx.stroke();
        ctx.setLineDash([]);
        const v = this.yToValue(this._mouseY);
        const txt = d.rel ? fmtPct(v, 1) : fmtPx(v);
        ctx.font = '10px var(--mono, monospace)';
        const w = Math.max(ctx.measureText(txt).width + 8, 44);
        ctx.fillStyle = P.ink;
        ctx.fillRect(p.x1 + 1, y - 7, w, 14);
        ctx.fillStyle = P.bg;
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(txt, p.x1 + 5, y);
      }
      ctx.setLineDash([]);
      // date tag on the time axis
      const label = fmtDay(this.series.d[i], 'long');
      ctx.font = '9.5px var(--mono, monospace)';
      const tw = ctx.measureText(label).width + 10;
      ctx.fillStyle = P.ink;
      ctx.fillRect(Math.min(Math.max(x - tw / 2, p.x0), p.x1 - tw), p.yBot + 1, tw, 14);
      ctx.fillStyle = P.bg;
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText(label, Math.min(Math.max(x, p.x0 + tw / 2), p.x1 - tw / 2), p.yBot + 3);
      ctx.restore();
    }

    /* ───────────────────────── interaction ─────────────────────────── */
    _bind() {
      const cv = this.cv;

      cv.addEventListener('mousemove', (e) => {
        const r = cv.getBoundingClientRect();
        const mx = e.clientX - r.left, my = e.clientY - r.top;
        this._mouseY = my;
        if (this._drag) {
          const n = this.i1 - this.i0 + 1;
          const bw = (this.plot.x1 - this.plot.x0) / n;
          const shift = Math.round((this._drag.x - mx) / bw);
          if (shift !== 0) {
            this.i0 = this._drag.i0 + shift; this.i1 = this._drag.i1 + shift;
            const s = this.series;
            if (this.i0 < 0) { this.i1 -= this.i0; this.i0 = 0; }
            if (this.i1 > s.n - 1) { this.i0 -= this.i1 - (s.n - 1); this.i1 = s.n - 1; }
            this.i0 = Math.max(0, this.i0);
          }
        }
        this.hover = this.series ? this.xToIndex(mx) : null;
        this.hoverPin = this._pinAt(mx, my);
        cv.style.cursor = this.hoverPin ? 'pointer' : this._drag ? 'grabbing' : 'crosshair';
        if (this.onHover) this.onHover(this.hover, this.hoverPin);
        this.draw();
      });

      cv.addEventListener('mouseleave', () => {
        this.hover = null; this.hoverPin = null; this._mouseY = null;
        if (this.onHover) this.onHover(null, null);
        this.draw();
      });

      cv.addEventListener('mousedown', (e) => {
        const r = cv.getBoundingClientRect();
        const mx = e.clientX - r.left, my = e.clientY - r.top;
        const pin = this._pinAt(mx, my);
        if (pin && this.onPinClick) { this.onPinClick(pin.pin); return; }
        this._drag = { x: mx, i0: this.i0, i1: this.i1 };
        cv.style.cursor = 'grabbing';
      });

      window.addEventListener('mouseup', () => { this._drag = null; });

      cv.addEventListener('wheel', (e) => {
        if (!this.series) return;
        e.preventDefault();
        const r = cv.getBoundingClientRect();
        const anchor = this.xToIndex(e.clientX - r.left);
        this.zoom(e.deltaY > 0 ? 1.18 : 1 / 1.18, anchor);
      }, { passive: false });

      cv.addEventListener('dblclick', () => this.setRange(252));
    }

    _pinAt(mx, my) {
      for (const hit of this._pinHits || []) {
        if (Math.abs(hit.x - mx) <= 6 && Math.abs(hit.y - 4 - my) <= 9) return hit;
      }
      return null;
    }

    /** Readout for the legend: OHLC + volume + change at the hovered bar. */
    readout(i) {
      const s = this.series; if (!s) return null;
      const idx = i ?? this.i1;
      const d = this._data || { o: s.o, h: s.h, l: s.l, c: s.c };
      const prev = idx > 0 ? d.c[idx - 1] : null;
      const c = d.c[idx];
      return {
        i: idx, day: s.d[idx], iso: dayToISO(s.d[idx]),
        o: d.o[idx], h: d.h[idx], l: d.l[idx], c,
        v: s.v ? s.v[idx] : null,
        chg: prev && c !== null ? c / prev - 1 : null,
        rel: !!d.rel,
      };
    }
  }

  /* ═══════════════════════ small multiples ═══════════════════════════════
     Used by the lower panels. Same rules: one axis, thin marks, recessive
     grid, no dual scales — anything on a second measure gets its own card.
     ===================================================================== */

  function hidpi(canvas, w, h) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return ctx;
  }

  /** Inline sparkline for the monitor rows. */
  function sparkline(values, w = 56, h = 14, color = null) {
    const cv = document.createElement('canvas');
    cv.className = 'spark';
    const ctx = hidpi(cv, w, h);
    const vals = values.filter((v) => v !== null && v !== undefined);
    if (vals.length < 2) return cv;
    const P = palette();
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    const col = color || (vals[vals.length - 1] >= vals[0] ? P.up : P.down);
    const x = (i) => (i / (values.length - 1)) * (w - 1) + 0.5;
    const y = (v) => h - 1.5 - ((v - lo) / span) * (h - 3);

    ctx.beginPath();
    let started = false;
    values.forEach((v, i) => {
      if (v === null) return;
      if (!started) { ctx.moveTo(x(i), y(v)); started = true; } else ctx.lineTo(x(i), y(v));
    });
    ctx.strokeStyle = col; ctx.lineWidth = 1.25; ctx.lineJoin = 'round';
    ctx.stroke();
    const lastV = values[values.length - 1];
    if (lastV !== null) {
      ctx.beginPath(); ctx.arc(x(values.length - 1), y(lastV), 1.5, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill();
    }
    return cv;
  }

  /**
   * Multi-series line card. series: [{label, color, points:[{x,y}], dash}]
   * x is a number (day or index); one y-axis only, by design.
   */
  function lineCard(series, { w = 300, h = 110, yFmt = fmtPx, xFmt = null, zero = false, grid = true } = {}) {
    const cv = document.createElement('canvas');
    cv.className = 'minichart';
    const ctx = hidpi(cv, w, h);
    const P = palette();
    const pad = { t: 6, r: 44, b: 14, l: 4 };
    const pts = series.flatMap((s) => s.points).filter((p) => p && p.y !== null && isFinite(p.y));
    if (!pts.length) return cv;
    let ylo = Math.min(...pts.map((p) => p.y)), yhi = Math.max(...pts.map((p) => p.y));
    if (zero) { ylo = Math.min(ylo, 0); yhi = Math.max(yhi, 0); }
    if (ylo === yhi) { ylo -= 1; yhi += 1; }
    const padv = (yhi - ylo) * 0.08; ylo -= padv; yhi += padv;
    const xlo = Math.min(...pts.map((p) => p.x)), xhi = Math.max(...pts.map((p) => p.x));
    const X = (v) => pad.l + ((v - xlo) / (xhi - xlo || 1)) * (w - pad.l - pad.r);
    const Y = (v) => h - pad.b - ((v - ylo) / (yhi - ylo)) * (h - pad.t - pad.b);

    if (grid) {
      ctx.strokeStyle = P.wire; ctx.lineWidth = 1;
      ctx.font = '9px var(--mono, monospace)'; ctx.fillStyle = P.ink3;
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      for (const t of niceTicks(ylo, yhi, 3)) {
        const y = Math.round(Y(t)) + 0.5;
        if (y < pad.t || y > h - pad.b) continue;
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
        ctx.fillText(yFmt(t), w - pad.r + 4, y);
      }
    }
    if (zero) {
      const y = Math.round(Y(0)) + 0.5;
      ctx.strokeStyle = P.wire2; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
      ctx.setLineDash([]);
    }
    for (const s of series) {
      const p = s.points.filter((q) => q && q.y !== null && isFinite(q.y));
      if (!p.length) continue;
      ctx.beginPath();
      p.forEach((q, i) => (i ? ctx.lineTo(X(q.x), Y(q.y)) : ctx.moveTo(X(q.x), Y(q.y))));
      ctx.strokeStyle = s.color || P.gold;
      ctx.lineWidth = s.width || 2;
      ctx.lineJoin = 'round';
      if (s.dash) ctx.setLineDash(s.dash);
      ctx.stroke();
      ctx.setLineDash([]);
      if (p.length === 1) {
        ctx.beginPath(); ctx.arc(X(p[0].x), Y(p[0].y), 2.5, 0, Math.PI * 2);
        ctx.fillStyle = s.color || P.gold; ctx.fill();
      }
      const lastP = p[p.length - 1];
      ctx.beginPath(); ctx.arc(X(lastP.x), Y(lastP.y), 2, 0, Math.PI * 2);
      ctx.fillStyle = s.color || P.gold; ctx.fill();
    }
    if (xFmt) {
      ctx.font = '9px var(--mono, monospace)'; ctx.fillStyle = P.ink3;
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left'; ctx.fillText(xFmt(xlo), pad.l, h - pad.b + 3);
      ctx.textAlign = 'right'; ctx.fillText(xFmt(xhi), w - pad.r, h - pad.b + 3);
    }
    return cv;
  }

  /**
   * Horizontal bar card with a diverging scale around zero.
   * rows: [{label, value, note}] — value is a decimal fraction.
   */
  function barCard(rows, { w = 300, rowH = 15, fmt = (v) => fmtPct(v, 1), zero = true } = {}) {
    const h = Math.max(rowH, rows.length * rowH) + 4;
    const cv = document.createElement('canvas');
    cv.className = 'minichart';
    const ctx = hidpi(cv, w, h);
    const P = palette();
    const labelW = 62, valW = 52;
    const plotW = w - labelW - valW;
    const vals = rows.map((r) => r.value).filter((v) => v !== null && isFinite(v));
    if (!vals.length) return cv;
    const amax = Math.max(...vals.map(Math.abs)) || 1;
    const mid = zero ? labelW + plotW / 2 : labelW;
    const scale = zero ? (plotW / 2) / amax : plotW / amax;

    ctx.font = '9.5px var(--mono, monospace)';
    ctx.textBaseline = 'middle';
    rows.forEach((r, i) => {
      const y = 2 + i * rowH + rowH / 2;
      ctx.fillStyle = P.ink2; ctx.textAlign = 'left';
      ctx.fillText(String(r.label).slice(0, 9), 1, y);
      if (r.value === null || !isFinite(r.value)) {
        ctx.fillStyle = P.ink3; ctx.textAlign = 'right';
        ctx.fillText('—', w - 2, y);
        return;
      }
      const len = Math.abs(r.value) * scale;
      const x = r.value >= 0 ? mid : mid - len;
      // 4px rounded data-end, anchored to the zero baseline
      const bh = Math.min(8, rowH - 5);
      ctx.fillStyle = r.value >= 0 ? P.up : P.down;
      const rad = Math.min(4, len);
      ctx.beginPath();
      if (r.value >= 0) {
        ctx.moveTo(x, y - bh / 2); ctx.lineTo(x + Math.max(0, len - rad), y - bh / 2);
        ctx.quadraticCurveTo(x + len, y - bh / 2, x + len, y);
        ctx.quadraticCurveTo(x + len, y + bh / 2, x + Math.max(0, len - rad), y + bh / 2);
        ctx.lineTo(x, y + bh / 2);
      } else {
        ctx.moveTo(mid, y - bh / 2); ctx.lineTo(x + rad, y - bh / 2);
        ctx.quadraticCurveTo(x, y - bh / 2, x, y);
        ctx.quadraticCurveTo(x, y + bh / 2, x + rad, y + bh / 2);
        ctx.lineTo(mid, y + bh / 2);
      }
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = P.ink; ctx.textAlign = 'right';
      ctx.fillText(fmt(r.value), w - 2, y);
      if (r.note) {
        ctx.fillStyle = P.ink3; ctx.textAlign = 'right';
        ctx.fillText(r.note, labelW - 3, y);
      }
    });
    if (zero) {
      ctx.strokeStyle = P.wire2;
      ctx.beginPath(); ctx.moveTo(mid + 0.5, 1); ctx.lineTo(mid + 0.5, h - 1); ctx.stroke();
    }
    return cv;
  }

  /** Scatter with an ordinal colour ramp (grade). points: [{x,y,c,label}] */
  function scatterCard(points, { w = 300, h = 130, xFmt = (v) => String(v), yFmt = (v) => fmtPct(v, 0), xLabel = '', yLabel = '', onPick = null } = {}) {
    const cv = document.createElement('canvas');
    cv.className = 'minichart';
    const ctx = hidpi(cv, w, h);
    const P = palette();
    const pad = { t: 6, r: 42, b: 20, l: 4 };
    const pts = points.filter((p) => p.x !== null && p.y !== null && isFinite(p.x) && isFinite(p.y));
    if (!pts.length) return cv;
    let xlo = Math.min(...pts.map((p) => p.x)), xhi = Math.max(...pts.map((p) => p.x));
    let ylo = Math.min(0, ...pts.map((p) => p.y)), yhi = Math.max(0, ...pts.map((p) => p.y));
    if (xlo === xhi) { xlo -= 1; xhi += 1; }
    if (ylo === yhi) { ylo -= 0.01; yhi += 0.01; }
    const padv = (yhi - ylo) * 0.08; ylo -= padv; yhi += padv;
    const X = (v) => pad.l + ((v - xlo) / (xhi - xlo)) * (w - pad.l - pad.r);
    const Y = (v) => h - pad.b - ((v - ylo) / (yhi - ylo)) * (h - pad.t - pad.b);

    ctx.strokeStyle = P.wire; ctx.lineWidth = 1;
    ctx.font = '9px var(--mono, monospace)'; ctx.fillStyle = P.ink3;
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    for (const t of niceTicks(ylo, yhi, 3)) {
      const y = Math.round(Y(t)) + 0.5;
      if (y < pad.t || y > h - pad.b) continue;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
      ctx.fillText(yFmt(t), w - pad.r + 4, y);
    }
    const y0 = Math.round(Y(0)) + 0.5;
    ctx.strokeStyle = P.wire2; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(pad.l, y0); ctx.lineTo(w - pad.r, y0); ctx.stroke();
    ctx.setLineDash([]);

    for (const p of pts) {
      ctx.beginPath();
      ctx.arc(X(p.x), Y(p.y), 4, 0, Math.PI * 2);
      ctx.fillStyle = p.c || P.gold;
      ctx.fill();
      ctx.strokeStyle = P.panel; ctx.lineWidth = 2;   // 2px surface ring on overlap
      ctx.stroke();
    }
    ctx.font = '9px var(--mono, monospace)'; ctx.fillStyle = P.ink3;
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left'; ctx.fillText(xFmt(xlo), pad.l, h - pad.b + 4);
    ctx.textAlign = 'right'; ctx.fillText(xFmt(xhi), w - pad.r, h - pad.b + 4);
    if (xLabel) { ctx.textAlign = 'center'; ctx.fillText(xLabel, (w - pad.r) / 2, h - pad.b + 4); }
    return cv;
  }

  /** Discrete state strip (regime history): one cell per observation. */
  function stripCard(cells, { w = 300, h = 16 } = {}) {
    const cv = document.createElement('canvas');
    cv.className = 'minichart';
    const ctx = hidpi(cv, w, h);
    if (!cells.length) return cv;
    const cw = w / cells.length;
    cells.forEach((c, i) => {
      ctx.fillStyle = c.color;
      ctx.fillRect(i * cw, 0, Math.max(1, cw - 1), h);     // 2px-ish surface gap
    });
    return cv;
  }

  RH.Chart = Chart;
  RH.viz = { sparkline, lineCard, barCard, scatterCard, stripCard, hidpi };
})(window.RH);
