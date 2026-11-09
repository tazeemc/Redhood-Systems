/* ===========================================================================
   app.js — state, the command language, the keyboard model, wiring.
   =========================================================================== */
'use strict';

(function (RH) {
  const { $, $$, el, esc, Source, getSeries, palette, REGIME_COLOR,
          fmtPx, fmtPct, fmtNum, fmtVol, fmtStamp, fmtDay, dayToISO, isoToDay,
          dirClass, dirMark, Chart, panels, viz } = RH;
  const { Monitor, Blotter, Detail, Lower, gradeColor } = panels;

  /* ───────────────────────────── state ──────────────────────────────── */
  const state = {
    bundle: null,
    symbol: 'SPY',
    narrative: null,
    detailMode: 'symbol',
    monScope: 'wl',
    monFilter: '',
    narFilter: '',
    narTicker: null,
    gradeFilter: '',
    bandFilter: '',
    tab: 'returns',
    tapeSrc: 'all',
    focus: 'chart',
    history: [],
    histIdx: -1,
  };

  let chart = null;

  /* ───────────────────────── command language ────────────────────────── */
  const FUNCS = {
    GP:   { desc: 'Chart the symbol', run: (sym) => { if (sym) loadSymbol(sym); focusPanel('chart'); } },
    DES:  { desc: 'Symbol description & narrative history', run: (sym) => { if (sym) loadSymbol(sym); state.detailMode = 'symbol'; focusPanel('detail'); render(); } },
    MON:  { desc: 'Monitor: watchlist and price grid', run: () => focusPanel('monitor') },
    WL:   { desc: 'Monitor, watchlist scope', run: () => { setScope('wl'); focusPanel('monitor'); } },
    ALL:  { desc: 'Monitor, every symbol', run: () => { setScope('all'); focusPanel('monitor'); } },
    NRTV: { desc: 'Narrative blotter', run: () => focusPanel('blotter') },
    N:    { desc: 'Narrative blotter', run: () => focusPanel('blotter') },
    RET:  { desc: 'Realised returns for the loaded symbol', run: () => setTab('returns') },
    REG:  { desc: 'Regime detector: temperature, entropy, KL, heat', run: () => setTab('regime') },
    ALPH: { desc: 'Realised alpha: hit rate and excess vs SPY', run: () => setTab('alpha') },
    TAPE: { desc: 'Feed tape: RSS and Twitter', run: () => setTab('tape') },
    NOTE: { desc: 'Analyst notes and memos', run: () => setTab('notes') },
    RUNS: { desc: 'Pipeline run history', run: () => setTab('runs') },
    TOP:  { desc: 'Highest-graded recent narrative', run: () => {
      const best = [...state.bundle.narratives].sort((a, b) =>
        ((b.g || {}).tot || 0) - ((a.g || {}).tot || 0) || (b.at || '').localeCompare(a.at || ''))[0];
      if (best) selectNarrative(best.id);
    } },
    ZOOM: { desc: 'Full-screen the focused panel', run: () => toggleZoom() },
    HELP: { desc: 'Keyboard and command help', run: () => showHelp(true) },
    H:    { desc: 'Keyboard and command help', run: () => showHelp(true) },
  };

  const FNBAR = [['MON', 'MON'], ['NRTV', 'NRTV'], ['REG', 'REG'], ['ALPH', 'ALPH'],
                 ['TAPE', 'TAPE'], ['NOTE', 'NOTE']];

  /** `NVDA GP` / `GP NVDA` / `NVDA` / `REG` — order-insensitive, like the real thing. */
  function runCommand(raw) {
    const text = (raw || '').trim().toUpperCase().replace(/\s+/g, ' ');
    if (!text) return;
    state.history.unshift(text);
    state.histIdx = -1;

    const parts = text.split(' ');
    const func = parts.find((p) => FUNCS[p]);
    const sym = parts.find((p) => p !== func && isSymbol(p));

    if (func) {
      FUNCS[func].run(sym || state.symbol);
      toast(`${func}${sym ? ' ' + sym : ''}`);
      return;
    }
    if (sym) { loadSymbol(sym); toast(sym); return; }

    // Not a symbol or function: treat it as a narrative search.
    state.narFilter = text;
    $('#narfilter').value = text;
    focusPanel('blotter');
    render();
    const hits = Blotter.rows(state).length;
    toast(hits ? `${hits} narrative${hits === 1 ? '' : 's'} match "${text}"` : `no match for "${text}"`);
  }

  const isSymbol = (s) => !!state.bundle.series[s] || !!state.bundle.symbols.find((r) => r.t === s);

  /* suggestions: symbols first, then functions, then narrative text hits */
  function suggest(q) {
    const text = (q || '').trim().toUpperCase();
    if (!text) return [];
    const out = [];
    const tail = text.split(' ').pop();

    for (const r of state.bundle.symbols) {
      if (!r.t.startsWith(tail)) continue;
      out.push({ k: r.t, d: r.name || r.cls || 'symbol', r: `${fmtPx(r.last)}  ${fmtPct(r.d1, 1)}`, cmd: r.t });
      if (out.length > 9) break;
    }
    for (const [k, f] of Object.entries(FUNCS)) {
      if (!k.startsWith(tail) || out.length > 13) continue;
      out.push({ k, d: f.desc, r: 'function', cmd: `${k}` });
    }
    if (out.length < 9 && text.length > 2) {
      for (const n of state.bundle.narratives) {
        if (out.length > 13) break;
        if (!n.title.toUpperCase().includes(text)) continue;
        out.push({ k: (n.g || {}).ltr || '—', d: n.title, r: (n.at || '').slice(0, 10), nar: n.id });
      }
    }
    return out;
  }

  /* ─────────────────────────── actions ──────────────────────────────── */
  function loadSymbol(sym) {
    if (!sym) return;
    const s = getSeries(sym);
    if (!s) { toast(`no price history for ${sym}`); return; }
    state.symbol = sym;
    state.detailMode = 'symbol';
    state.narTicker = null;
    chart.setSeries(s, { pins: pinsFor(sym), bench: getSeries('SPY') });
    render();
  }

  /** Narrative markers for the chart: entry date where known, else run date. */
  function pinsFor(sym) {
    const P = palette();
    const out = [];
    for (const n of state.bundle.narratives) {
      const leg = n.tk.find((t) => t.t === sym);
      if (!leg) continue;
      const r = n.ret.find((x) => x.t === sym);
      const iso = (r && r.entry) || (n.at || '').slice(0, 10);
      if (!iso) continue;
      out.push({
        day: isoToDay(iso), id: n.id, title: n.title, side: leg.side,
        grade: (n.g || {}).ltr || null, color: gradeColor((n.g || {}).ltr, P),
        ret: r || null,
      });
    }
    return out;
  }

  function selectNarrative(id) {
    state.narrative = id;
    state.detailMode = 'narrative';
    const n = state.bundle.narratives.find((x) => x.id === id);
    if (n && n.tk.length) {
      const first = n.tk.find((t) => getSeries(t.t));
      if (first && first.t !== state.symbol) {
        state.symbol = first.t;
        chart.setSeries(getSeries(first.t), { pins: pinsFor(first.t), bench: getSeries('SPY') });
      }
    }
    render();
    const row = $(`#narbody tr[data-nar="${CSS.escape(id)}"]`);
    if (row) row.scrollIntoView({ block: 'nearest' });
  }

  function setScope(scope) {
    state.monScope = scope;
    $$('#monscope button').forEach((b) => b.classList.toggle('on', b.dataset.scope === scope));
    Monitor.render(state);
  }

  function setTab(tab) {
    state.tab = tab;
    $$('#lowtabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    renderLower();
    $$('#fnbar button').forEach((b) => b.classList.toggle('on', b.dataset.cmd === tab.toUpperCase()));
  }

  function focusPanel(name) {
    state.focus = name;
    $$('.panel').forEach((p) => p.classList.toggle('focused', p.dataset.panel === name));
    const p = $(`#p-${name}`);
    if (p) p.focus({ preventScroll: true });
    renderStatus();
  }

  function toggleZoom() {
    const p = $(`#p-${state.focus}`);
    if (!p) return;
    const on = !p.classList.contains('zoomed');
    $$('.panel').forEach((x) => x.classList.remove('zoomed'));
    document.body.classList.toggle('zoom', on);
    if (on) p.classList.add('zoomed');
    if (chart) setTimeout(() => chart.resize(), 30);
    renderStatus();
  }

  let toastTimer = null;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 1600);
  }

  /* ─────────────────────────── rendering ────────────────────────────── */
  function render() {
    Monitor.render(state);
    Blotter.render(state);
    Detail.render(state);
    renderChartHead();
    renderLower();
    renderStatus();
  }

  function renderChartHead() {
    const row = state.bundle.symbols.find((s) => s.t === state.symbol);
    const s = getSeries(state.symbol);
    $('#symname').textContent = state.symbol;
    $('#symmeta').textContent = row
      ? [row.name, row.cls, row.ohlc ? 'OHLCV' : 'close only', `${row.n} bars`, row.nar ? `${row.nar} narratives` : null]
        .filter(Boolean).join(' · ')
      : '';
    const q = $('#quote');
    if (!row || !s) { q.replaceChildren(); return; }
    q.replaceChildren(
      el('span', { class: 'px', text: fmtPx(row.last) }),
      el('span', { class: `ch ${dirClass(row.d1)}`, text: `${dirMark(row.d1)} ${fmtPct(row.d1, 2)}` }),
      el('span', { class: 'sub', text: `20d ${fmtPct(row.d20, 1)} · ytd ${fmtPct(row.ytd, 1)} · ${row.to}` }));
    updateLegend(null);
  }

  function updateLegend(i) {
    if (!chart || !chart.series) return;
    const P = palette();
    const r = chart.readout(i);
    if (!r) return;
    const parts = [];
    const push = (k, v, cls) => parts.push(
      el('span', {}, el('span', { class: 'k', text: k + ' ' }),
      el('span', { class: 'v ' + (cls || ''), text: v })));

    if (r.rel) {
      push('vsSPY', fmtPct(r.c, 2), dirClass(r.c));
    } else if (chart.series.hasOHLC && chart.style === 'candle') {
      push('O', fmtPx(r.o)); push('H', fmtPx(r.h)); push('L', fmtPx(r.l));
      push('C', fmtPx(r.c), dirClass(r.chg));
    } else {
      push('C', fmtPx(r.c), dirClass(r.chg));
    }
    push('chg', fmtPct(r.chg, 2), dirClass(r.chg));
    if (r.v) push('vol', fmtVol(r.v));
    if (chart.opts.ma && !r.rel) {
      for (const [n, slot] of [[20, 0], [50, 1], [200, 3]]) {
        const m = chart._ma(n)[r.i];
        if (m === null || m === undefined) continue;
        parts.push(el('span', {},
          el('span', { class: 'k', html: `<i class="sw" style="background:${P.cat[slot]}"></i>MA${n} ` }),
          el('span', { class: 'v', text: fmtPx(m) })));
      }
    }
    parts.push(el('span', { class: 'k', text: fmtDay(r.day, 'long') }));
    $('#legend').replaceChildren(...parts);
  }

  function renderLower() {
    const body = $('#lowbody');
    const fn = Lower[state.tab];
    body.replaceChildren(fn ? fn(state) : el('p', { class: 'note', text: 'unknown tab' }));
    body.scrollTop = 0;
  }

  function renderRegimeChip() {
    const P = palette();
    const r = state.bundle.meta.regime_now;
    const chip = $('#regimechip');
    if (!r) { chip.replaceChildren(el('span', { class: 'lbl', text: 'NO REGIME' })); return; }
    chip.replaceChildren(
      el('span', { class: 'dot', style: `background:${REGIME_COLOR(r.label, P)}` }),
      el('span', { class: 'lbl', text: r.label }),
      el('span', { class: 'num', text: `T ${fmtPct(r.temp, 1)} · x${fmtNum(r.mult, 2)}${r.warn ? ' · DRIFT' : ''}` }));
    chip.title = `Regime as of ${r.asof} — entropy ${fmtNum(r.S, 3)}, eta ${fmtNum(r.eta, 3)}, ` +
      `KL ${fmtNum(r.kl, 3)} vs threshold ${fmtNum(r.klt, 3)}, heat ${fmtPct(r.heat, 1)}`;
  }

  function renderStatus() {
    const m = state.bundle.meta;
    $('#st-left').innerHTML =
      `<b>${esc(state.focus)}</b> focused · <span class="k">/</span> command · ` +
      `<span class="k">?</span> help · <span class="k">F1-F4</span> panels · <span class="k">Z</span> zoom`;
    $('#st-mid').textContent =
      `${m.counts.symbols} symbols · ${m.counts.bars.toLocaleString('en-US')} bars · ` +
      `${m.counts.narratives} narratives · ${m.counts.runs} runs`;
    $('#st-right').innerHTML =
      `${Source.live ? '<b>LIVE</b>' : 'STATIC'} · data as of <b>${esc(m.as_of || '—')}</b> · built ${esc((m.built_at || '').slice(0, 16).replace('T', ' '))}Z`;
  }

  function renderTape() {
    const track = $('#tapetrack');
    const rows = state.bundle.symbols.filter((r) => r.wl || r.nar > 2).slice(0, 36);
    const mk = () => rows.map((r) => el('span', { class: 'tapeitem', 'data-sym': r.t },
      el('span', { class: 'ts', text: r.t }),
      el('span', { class: 'tp', text: fmtPx(r.last) }),
      el('span', { class: dirClass(r.d1), text: `${dirMark(r.d1)}${fmtPct(r.d1, 2)}` })));
    track.replaceChildren(...mk(), ...mk());        // duplicated for a seamless loop
  }

  function renderFnbar() {
    $('#fnbar').replaceChildren(...FNBAR.map(([label, cmd]) =>
      el('button', { 'data-cmd': cmd, title: (FUNCS[cmd] || {}).desc || '', text: label })));
  }

  function renderFilters() {
    const grades = Array.from(new Set(state.bundle.narratives.map((n) => (n.g || {}).ltr).filter(Boolean)))
      .sort((a, b) => panels.GRADE_ORDER.indexOf(a) - panels.GRADE_ORDER.indexOf(b));
    const gf = $('#gradefilter');
    gf.replaceChildren(el('option', { value: '' }, 'all grades'),
      ...grades.map((g) => el('option', { value: g }, `grade ${g}`)));
    const bands = Array.from(new Set(state.bundle.narratives.map((n) => n.band).filter(Boolean)));
    const bf = $('#bandfilter');
    bf.replaceChildren(el('option', { value: '' }, 'all bands'),
      ...bands.map((b) => el('option', { value: b }, `${b} entropy`)));
  }

  /* ──────────────────────────── help card ───────────────────────────── */
  const HELP = [
    ['Command line', [
      ['NVDA', 'load a symbol'],
      ['NVDA GP', 'load and focus the chart'],
      ['SPY DES', 'symbol dossier + narrative history'],
      ['REG / ALPH', 'regime detector / realised alpha'],
      ['TAPE / NOTE / RUNS', 'feed tape / memos / run history'],
      ['TOP', 'jump to the best-graded narrative'],
      ['free text', 'search narratives'],
    ]],
    ['Navigation', [
      ['/ or :', 'focus the command line'],
      ['Esc', 'leave the command line / close overlays'],
      ['F1 … F4', 'monitor · chart · blotter · detail'],
      ['Tab', 'cycle panel focus'],
      ['j / k', 'move down / up a focused list'],
      ['Enter', 'open the highlighted row'],
      ['Z', 'full-screen the focused panel'],
      ['t', 'light / dark'],
    ]],
    ['Chart', [
      ['drag', 'pan'],
      ['wheel', 'zoom at the cursor'],
      ['← / →', 'pan by a bar'],
      ['+ / −', 'zoom in / out'],
      ['1 … 6', '1M 3M 6M YTD 1Y MAX'],
      ['c', 'candles / line'],
      ['m / b', 'moving averages / Bollinger'],
      ['v / n', 'volume / narrative markers'],
      ['l / r', 'log scale / relative to SPY'],
      ['double-click', 'reset to 1Y'],
    ]],
    ['Reading the chart', [
      ['hollow candle', 'close ≥ open'],
      ['filled candle', 'close < open'],
      ['▲ marker', 'a narrative referenced this name'],
      ['marker colour', 'letter grade, light = better'],
      ['click marker', 'open that narrative'],
    ]],
  ];

  function showHelp(on) {
    const h = $('#help');
    if (on && !h.dataset.built) {
      $('#helpgrid').replaceChildren(...HELP.map(([title, rows]) =>
        el('section', {}, el('h4', {}, title),
          el('dl', {}, ...rows.flatMap(([k, d]) => [el('dt', { text: k }), el('dd', { text: d })])))));
      h.dataset.built = '1';
    }
    h.hidden = !on;
  }

  /* ─────────────────────────── event wiring ─────────────────────────── */
  function wire() {
    /* command line */
    const cmd = $('#cmd'), ac = $('#ac');
    let acItems = [], acIdx = -1;

    const closeAc = () => { ac.hidden = true; acIdx = -1; acItems = []; };
    const paintAc = () => {
      if (!acItems.length) return closeAc();
      ac.replaceChildren(...acItems.map((it, i) =>
        el('li', { role: 'option', 'aria-selected': i === acIdx ? 'true' : 'false', 'data-i': i },
          el('span', { class: 'k', text: it.k }),
          el('span', { class: 'd', text: it.d }),
          el('span', { class: 'r', text: it.r || '' }))));
      ac.hidden = false;
    };
    const takeAc = (i) => {
      const it = acItems[i];
      if (!it) return;
      closeAc();
      cmd.value = '';
      if (it.nar) selectNarrative(it.nar);
      else runCommand(it.cmd);
    };

    cmd.addEventListener('input', () => { acItems = suggest(cmd.value); acIdx = acItems.length ? 0 : -1; paintAc(); });
    cmd.addEventListener('blur', () => setTimeout(closeAc, 120));
    cmd.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); acIdx = Math.min(acIdx + 1, acItems.length - 1); paintAc(); }
      else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (acIdx > 0) { acIdx--; paintAc(); }
        else if (state.history.length) {
          state.histIdx = Math.min(state.histIdx + 1, state.history.length - 1);
          cmd.value = state.history[state.histIdx] || '';
          closeAc();
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (acIdx >= 0 && acItems.length) takeAc(acIdx);
        else { const v = cmd.value; cmd.value = ''; closeAc(); runCommand(v); }
      } else if (e.key === 'Escape') { closeAc(); cmd.blur(); }
      e.stopPropagation();
    });
    ac.addEventListener('mousedown', (e) => {
      const li = e.target.closest('li[data-i]');
      if (li) { e.preventDefault(); takeAc(+li.dataset.i); }
    });

    /* function bar */
    $('#fnbar').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-cmd]');
      if (b) runCommand(b.dataset.cmd);
    });

    /* monitor */
    $('#monscope').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-scope]');
      if (b) setScope(b.dataset.scope);
    });
    $('#monfilter').addEventListener('input', (e) => { state.monFilter = e.target.value; Monitor.render(state); });
    $('#montable thead').addEventListener('click', (e) => {
      const th = e.target.closest('th[data-sort]');
      if (!th) return;
      const k = th.dataset.sort;
      Monitor.sort = { key: k, dir: Monitor.sort.key === k && Monitor.sort.dir === 'desc' ? 'asc' : 'desc' };
      Monitor.render(state);
    });
    $('#monbody').addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-sym]');
      if (tr) { loadSymbol(tr.dataset.sym); focusPanel('monitor'); }
    });

    /* blotter */
    $('#nartable thead').addEventListener('click', (e) => {
      const th = e.target.closest('th[data-sort]');
      if (!th) return;
      const k = th.dataset.sort;
      Blotter.sort = { key: k, dir: Blotter.sort.key === k && Blotter.sort.dir === 'desc' ? 'asc' : 'desc' };
      Blotter.render(state);
    });
    $('#narbody').addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-nar]');
      if (tr) { selectNarrative(tr.dataset.nar); focusPanel('blotter'); }
    });
    $('#narfilter').addEventListener('input', (e) => { state.narFilter = e.target.value; Blotter.render(state); });
    $('#gradefilter').addEventListener('change', (e) => { state.gradeFilter = e.target.value; Blotter.render(state); });
    $('#bandfilter').addEventListener('change', (e) => { state.bandFilter = e.target.value; Blotter.render(state); });

    /* chart controls */
    $('#rangeseg').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-range]');
      if (!b) return;
      $$('#rangeseg button').forEach((x) => x.classList.toggle('on', x === b));
      const r = b.dataset.range;
      chart.setRange(r === 'ytd' ? 'ytd' : +r);
    });
    $('#styleseg').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-style]');
      if (!b) return;
      $$('#styleseg button').forEach((x) => x.classList.toggle('on', x === b));
      chart.set('style', b.dataset.style);
      updateLegend(null);
    });
    $('#ovseg').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-ov]');
      if (!b) return;
      const key = b.dataset.ov;
      const on = !b.classList.contains('on');
      b.classList.toggle('on', on);
      chart.set(key, on);
      updateLegend(null);
    });

    /* lower tabs */
    $('#lowtabs').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-tab]');
      if (b) setTab(b.dataset.tab);
    });

    /* delegated clicks inside panel bodies: symbols, narratives, tape links */
    document.addEventListener('click', (e) => {
      const pill = e.target.closest('[data-sym]');
      if (pill && !e.target.closest('tr[data-sym]')) {
        const sym = pill.dataset.sym;
        if (sym) { loadSymbol(sym); return; }
      }
      const nar = e.target.closest('[data-nar]');
      if (nar && nar.dataset.nar && !e.target.closest('#narbody')) { selectNarrative(nar.dataset.nar); return; }
      const src = e.target.closest('[data-tapesrc]');
      if (src) { state.tapeSrc = src.dataset.tapesrc; renderLower(); return; }
      const line = e.target.closest('.tapeline[data-url]');
      if (line && line.dataset.url) { window.open(line.dataset.url, '_blank', 'noopener'); return; }
    });

    /* panel focus by click */
    $$('.panel').forEach((p) => p.addEventListener('mousedown', () => focusPanel(p.dataset.panel)));

    /* chart hover -> legend + crosshair pin tooltip */
    chart.onHover = (i, pin) => {
      updateLegend(i);
      const xh = $('#xhair');
      if (pin) {
        const p = pin.pin;
        const exc = p.ret && p.ret.td !== null && p.ret.std !== null ? p.ret.td - p.ret.std : null;
        xh.innerHTML =
          `<b>${esc(p.title)}</b><br>${esc(dayToISO(p.day))} · ${esc(p.side)}` +
          (p.grade ? ` · grade ${esc(p.grade)}` : '') +
          (exc === null ? '' : ` · vs SPY ${esc(fmtPct(exc, 1))}`);
        xh.hidden = false;
      } else xh.hidden = true;
    };
    chart.onPinClick = (pin) => selectNarrative(pin.id);

    /* theme */
    $('#themebtn').addEventListener('click', toggleTheme);
    $('#helpbtn').addEventListener('click', () => showHelp(true));
    $('#helpclose').addEventListener('click', () => showHelp(false));
    $('#help').addEventListener('click', (e) => { if (e.target.id === 'help') showHelp(false); });

    /* tape clicks */
    $('#tapetrack').addEventListener('click', (e) => {
      const it = e.target.closest('.tapeitem[data-sym]');
      if (it) loadSymbol(it.dataset.sym);
    });

    /* global keys */
    document.addEventListener('keydown', onKey);
  }

  const PANEL_KEYS = { F1: 'monitor', F2: 'chart', F3: 'blotter', F4: 'detail' };
  const PANEL_CYCLE = ['monitor', 'chart', 'blotter', 'detail'];
  const RANGE_KEYS = { 1: 21, 2: 63, 3: 126, 4: 'ytd', 5: 252, 6: 0 };

  function onKey(e) {
    if (e.target.matches('input, select, textarea')) return;

    if (PANEL_KEYS[e.key]) { e.preventDefault(); focusPanel(PANEL_KEYS[e.key]); return; }

    switch (e.key) {
      case '/': case ':':
        e.preventDefault(); $('#cmd').focus(); $('#cmd').select(); return;
      case '?':
        e.preventDefault(); showHelp($('#help').hidden); return;
      case 'Escape':
        if (!$('#help').hidden) { showHelp(false); return; }
        if (document.body.classList.contains('zoom')) { toggleZoom(); return; }
        return;
      case 'Tab': {
        e.preventDefault();
        const i = PANEL_CYCLE.indexOf(state.focus);
        focusPanel(PANEL_CYCLE[(i + (e.shiftKey ? -1 : 1) + PANEL_CYCLE.length) % PANEL_CYCLE.length]);
        return;
      }
      case 'z': case 'Z': e.preventDefault(); toggleZoom(); return;
      case 't': case 'T': toggleTheme(); return;
      case 'j': case 'ArrowDown': if (moveList(1)) e.preventDefault(); return;
      case 'k': case 'ArrowUp': if (moveList(-1)) e.preventDefault(); return;
      case 'Enter': openFocused(); return;
    }

    /* chart keys — live whenever the chart or no list is focused */
    if (state.focus === 'chart' || state.focus === 'detail') {
      if (RANGE_KEYS[e.key] !== undefined) {
        e.preventDefault();
        const v = RANGE_KEYS[e.key];
        chart.setRange(v);
        $$('#rangeseg button').forEach((b) => b.classList.toggle('on', b.dataset.range === String(v)));
        return;
      }
      switch (e.key) {
        case 'ArrowLeft': e.preventDefault(); chart.pan(-Math.max(1, Math.round((chart.i1 - chart.i0) * 0.08))); return;
        case 'ArrowRight': e.preventDefault(); chart.pan(Math.max(1, Math.round((chart.i1 - chart.i0) * 0.08))); return;
        case '+': case '=': e.preventDefault(); chart.zoom(1 / 1.3); return;
        case '-': case '_': e.preventDefault(); chart.zoom(1.3); return;
        case 'c': case 'C': clickSeg('#styleseg', chart.style === 'candle' ? 'line' : 'candle', 'style'); return;
        case 'm': case 'M': toggleOv('ma'); return;
        case 'b': case 'B': toggleOv('bb'); return;
        case 'v': case 'V': toggleOv('vol'); return;
        case 'n': case 'N': toggleOv('pins'); return;
        case 'l': case 'L': toggleOv('log'); return;
        case 'r': case 'R': toggleOv('rel'); return;
      }
    }
  }

  function clickSeg(seg, val, kind) {
    const b = $(`${seg} button[data-${kind}="${val}"]`);
    if (b) b.click();
  }

  function toggleOv(key) {
    const b = $(`#ovseg button[data-ov="${key}"]`);
    if (b) b.click();
  }

  /** j/k within whichever list has focus. */
  function moveList(delta) {
    const map = { monitor: ['#monbody tr', 'sym'], blotter: ['#narbody tr', 'nar'] };
    const cfg = map[state.focus];
    if (!cfg) return false;
    const rows = $$(cfg[0]);
    if (!rows.length) return false;
    let i = rows.findIndex((r) => r.classList.contains('sel'));
    if (i < 0) i = delta > 0 ? -1 : 0;
    const next = rows[Math.max(0, Math.min(rows.length - 1, i + delta))];
    if (!next) return true;
    rows.forEach((r) => r.classList.remove('sel'));
    next.classList.add('sel');
    next.scrollIntoView({ block: 'nearest' });
    return true;
  }

  function openFocused() {
    if (state.focus === 'monitor') {
      const tr = $('#monbody tr.sel');
      if (tr) loadSymbol(tr.dataset.sym);
    } else if (state.focus === 'blotter') {
      const tr = $('#narbody tr.sel');
      if (tr) selectNarrative(tr.dataset.nar);
    }
  }

  function toggleTheme() {
    const root = document.documentElement;
    const next = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    try { localStorage.setItem('rh-theme', next); } catch { /* private mode */ }
    chart.draw();
    render();
    renderTape();
    renderRegimeChip();
  }

  function startClock() {
    const tick = () => {
      const d = new Date();
      const utc = d.toISOString().slice(11, 19);
      $('#clock').textContent = `${utc}Z · ${d.toLocaleTimeString('en-GB', { hour12: false })} local`;
    };
    tick();
    setInterval(tick, 1000);
  }

  /** Live mode only: fold polled quotes into the symbol rows. */
  async function pollQuotes() {
    if (!Source.live) return;
    const syms = state.bundle.symbols.filter((r) => r.wl).map((r) => r.t).slice(0, 20);
    const q = await Source.quotes(syms);
    let touched = false;
    for (const [t, v] of Object.entries(q)) {
      const row = state.bundle.symbols.find((r) => r.t === t);
      if (!row || v.last === null) continue;
      row.last = v.last;
      if (v.chg !== null && v.chg !== undefined) row.d1 = v.chg;
      touched = true;
    }
    if (touched) { Monitor.render(state); renderTape(); renderChartHead(); }
    setTimeout(pollQuotes, 60000);
  }

  /* ──────────────────────────── bootstrap ───────────────────────────── */
  async function boot() {
    try {
      const saved = localStorage.getItem('rh-theme');
      if (saved) document.documentElement.dataset.theme = saved;
    } catch { /* ignore */ }

    try {
      state.bundle = await Source.load();
    } catch (err) {
      document.body.innerHTML =
        `<div style="padding:24px;font:12px monospace;color:#F5F0E8">` +
        `<h1 style="color:#C1121F">RedHood Terminal — no data</h1>` +
        `<p>${esc(err.message)}</p>` +
        `<p>Build the static page with <code>python redhood_terminal.py --html</code>, ` +
        `or run <code>python redhood_terminal.py --serve</code> for live mode.</p></div>`;
      return;
    }

    chart = new Chart($('#chart'), $('#chartbox'));
    RH.chart = chart;
    RH.state = state;

    renderFnbar();
    renderFilters();
    renderTape();
    renderRegimeChip();
    startClock();
    wire();

    // Open on the watchlist's first charted name, else SPY, else anything.
    const first = state.bundle.symbols.find((r) => r.wl && getSeries(r.t))
      || state.bundle.symbols.find((r) => r.t === 'SPY')
      || state.bundle.symbols[0];
    state.symbol = first ? first.t : 'SPY';
    const s = getSeries(state.symbol);
    if (s) chart.setSeries(s, { pins: pinsFor(state.symbol), bench: getSeries('SPY') });

    setTab('returns');
    focusPanel('chart');
    render();

    if (Source.live) pollQuotes();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window.RH);
