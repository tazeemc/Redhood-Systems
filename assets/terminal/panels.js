/* ===========================================================================
   panels.js — every panel's renderer. Each takes state, returns/fills DOM.
   Nothing here fetches: app.js owns state and calls in.
   =========================================================================== */
'use strict';

(function (RH) {
  const { $, $$, el, esc, fmtPx, fmtPct, fmtNum, fmtVol, fmtAgo, fmtStamp,
          fmtDay, dirClass, dirMark, dayToISO, isoToDay, palette, getSeries,
          REGIME_COLOR, mean, median, viz } = RH;

  const GRADE_ORDER = ['A', 'A-', 'B', 'C', 'D', 'F'];
  const gradeSlot = (g) => Math.min(4, Math.max(0, GRADE_ORDER.indexOf(g) < 0 ? 4 : Math.floor(GRADE_ORDER.indexOf(g) * 5 / 6)));
  const gradeColor = (g, P) => (g ? P.grade[gradeSlot(g)] : P.neutral);

  const badge = (txt, cls) => el('span', { class: `badge ${cls || ''}`, text: txt });

  /* ───────────────────────────── monitor ─────────────────────────────── */
  const Monitor = {
    sort: { key: 'd1', dir: 'desc' },

    rows(state) {
      const b = state.bundle;
      let rows = b.symbols;
      if (state.monScope === 'wl') rows = rows.filter((r) => r.wl);
      else if (state.monScope === 'nar') rows = rows.filter((r) => r.nar > 0);
      const q = (state.monFilter || '').trim().toUpperCase();
      if (q) rows = rows.filter((r) => r.t.includes(q) || (r.name || '').toUpperCase().includes(q));

      const { key, dir } = this.sort;
      const sign = dir === 'asc' ? 1 : -1;
      return [...rows].sort((a, x) => {
        const va = a[key], vx = x[key];
        if (typeof va === 'string') return sign * va.localeCompare(vx);
        if (va === null || va === undefined) return 1;
        if (vx === null || vx === undefined) return -1;
        return sign * (va - vx);
      });
    },

    render(state) {
      const body = $('#monbody');
      const rows = this.rows(state);
      body.replaceChildren(...rows.map((r) => {
        const s = getSeries(r.t);
        const spark = s ? viz.sparkline(s.c.slice(-60), 56, 13) : el('span');
        const tr = el('tr', { 'data-sym': r.t, class: r.t === state.symbol ? 'sel' : '' },
          el('td', { class: 'l sym' }, r.t, r.wl ? ' ' : '', r.wl ? badge('W', 'wl') : ''),
          el('td', {}, fmtPx(r.last)),
          el('td', { class: dirClass(r.d1) }, `${dirMark(r.d1)} ${fmtPct(r.d1, 2)}`),
          el('td', { class: dirClass(r.d20) }, fmtPct(r.d20, 1)),
          el('td', {}, spark));
        return tr;
      }));

      $('#monfoot').textContent =
        `${rows.length} shown · ${state.bundle.meta.counts.symbols} total · ` +
        `${state.bundle.meta.counts.with_ohlc} with candles`;
      $$('#montable thead th').forEach((th) => {
        th.removeAttribute('data-dir');
        if (th.dataset.sort === this.sort.key) th.dataset.dir = this.sort.dir;
      });
    },
  };

  /* ──────────────────────────── blotter ──────────────────────────────── */
  const Blotter = {
    sort: { key: 'at', dir: 'desc' },

    rows(state) {
      let rows = state.bundle.narratives;
      if (state.gradeFilter) rows = rows.filter((n) => (n.g || {}).ltr === state.gradeFilter);
      if (state.bandFilter) rows = rows.filter((n) => n.band === state.bandFilter);
      const q = (state.narFilter || '').trim().toUpperCase();
      if (q) {
        rows = rows.filter((n) =>
          n.title.toUpperCase().includes(q) ||
          (n.hyp || '').toUpperCase().includes(q) ||
          n.tk.some((t) => t.t.includes(q)));
      }
      if (state.narTicker) rows = rows.filter((n) => n.tk.some((t) => t.t === state.narTicker));

      const { key, dir } = this.sort;
      const sign = dir === 'asc' ? 1 : -1;
      const val = (n) => (key === 'g' ? (n.g ? -GRADE_ORDER.indexOf(n.g.ltr) : -99) : n[key]);
      return [...rows].sort((a, x) => {
        const va = val(a), vx = val(x);
        if (typeof va === 'string') return sign * va.localeCompare(vx);
        if (va === null || va === undefined) return 1;
        if (vx === null || vx === undefined) return -1;
        return sign * (va - vx);
      });
    },

    render(state) {
      const rows = this.rows(state);
      const body = $('#narbody');
      body.replaceChildren(...rows.map((n) => {
        const g = n.g ? n.g.ltr : null;
        const tks = n.tk.slice(0, 3).map((t) => t.t).join(' ');
        return el('tr', { 'data-nar': n.id, class: n.id === state.narrative ? 'sel' : '' },
          el('td', { class: 'l mut' }, (n.at || '').slice(5, 10)),
          el('td', {}, g ? badge(g, `g-${g}`) : badge('—', 'na')),
          el('td', { class: n.ent >= 7 ? 'dn' : n.ent <= 4 ? 'up' : '' }, n.ent ?? '—'),
          el('td', { class: n.conv ? '' : 'mut' }, n.conv ? fmtNum(n.conv, 2) : '0'),
          el('td', { class: 'l', title: `${n.title}\n${tks}` },
            el('span', { text: n.title }),
            tks ? el('span', { class: 'note', text: `  ${tks}` }) : ''));
      }));

      const withRet = rows.filter((n) => n.ret.length).length;
      $('#narfoot').textContent = `${rows.length} of ${state.bundle.narratives.length} narratives · ${withRet} with realised returns`;
      $$('#nartable thead th').forEach((th) => {
        th.removeAttribute('data-dir');
        if (th.dataset.sort === this.sort.key) th.dataset.dir = this.sort.dir;
      });
    },
  };

  /* ───────────────────────────── detail ──────────────────────────────── */
  const Detail = {
    render(state) {
      const head = $('#detailhead'), body = $('#detailbody');
      $('#detailhint').textContent = '';
      if (state.detailMode === 'narrative' && state.narrative) {
        const n = state.bundle.narratives.find((x) => x.id === state.narrative);
        if (n) { head.textContent = 'Narrative'; body.replaceChildren(this.narrative(n, state)); return; }
      }
      head.textContent = 'Symbol';
      body.replaceChildren(this.symbol(state));
    },

    /* --- narrative dossier --- */
    narrative(n, state) {
      const P = palette();
      const frag = document.createDocumentFragment();
      const g = n.g;

      frag.append(el('div', { class: 'sect' },
        el('h4', {}, `${(n.at || '').slice(0, 10)} · run ${n.run}`),
        el('p', { style: 'color:var(--ink);font-weight:600', text: n.title })));

      const stats = el('div', { class: 'stats' },
        this.stat('Grade', g ? g.ltr : '—', g ? `${g.tot}/20` : 'ungraded',
          g ? gradeColor(g.ltr, P) : null),
        this.stat('Entropy', n.ent ?? '—', n.band || ''),
        this.stat('Size', n.conv ? fmtNum(n.conv, 2) : '0', 'conviction'),
        this.stat('Sources', n.feeds || 0, 'feed items'));
      frag.append(stats);

      if (g) {
        frag.append(el('div', { class: 'sect' },
          el('h4', {}, 'Grade components'),
          viz.barCard([
            { label: 'specificity', value: g.spec / 5 },
            { label: 'catalyst', value: g.cat / 5 },
            { label: 'risk', value: g.risk / 5 },
            { label: 'cohesion', value: g.coh / 5 },
          ], { w: 300, fmt: (v) => `${Math.round(v * 5)}/5`, zero: false })));
      }

      frag.append(this.textSect('Hypothesis', n.hyp));
      if (n.tk.length) {
        frag.append(el('div', { class: 'sect' },
          el('h4', {}, 'Instruments'),
          el('div', { class: 'pillrow' }, ...n.tk.map((t) =>
            el('span', {
              class: 'pill', 'data-sym': t.t,
              title: `${t.side}${t.w ? ` · weight ${fmtNum(t.w, 2)}` : ''}${t.lng ? ' · long-equity eligible' : ''}`,
            }, `${t.t} ${t.side}`)))));
      }

      if (n.ret.length) {
        const rows = [];
        for (const r of n.ret) {
          for (const [k, sk, lab] of [['h5', 'sh5', '5d'], ['h20', 'sh20', '20d'], ['h60', 'sh60', '60d'], ['td', 'std', 'live']]) {
            if (r[k] === null || r[k] === undefined) continue;
            rows.push({
              label: `${r.t} ${lab}`,
              value: r[sk] !== null && r[sk] !== undefined ? r[k] - r[sk] : r[k],
              note: fmtPct(r[k], 0),
            });
          }
        }
        frag.append(el('div', { class: 'sect' },
          el('h4', {}, 'Realised vs SPY'),
          el('div', { class: 'cleg' },
            el('span', { html: `<i style="background:${P.up}"></i>beat SPY` }),
            el('span', { html: `<i style="background:${P.down}"></i>lagged SPY` }),
            el('span', { text: 'grey column = raw return' })),
          viz.barCard(rows, { w: 300 }),
          el('p', { class: 'note', text: `entry ${n.ret[0].entry || '—'} · last ${n.ret[0].last || '—'}` })));
      }

      frag.append(this.textSect('Rationale', n.why));
      if (n.bear) frag.append(this.textSect('Bear case', n.bear));
      if (n.adj) frag.append(this.textSect('Conviction note', n.adj));
      if (n.cat.length) frag.append(this.listSect('Catalysts', n.cat));
      if (n.dis.length) frag.append(this.listSect('Disconfirming signals', n.dis));

      const prov = [];
      if (n.prior) prov.push(`${n.prior} prior mention${n.prior === 1 ? '' : 's'}`);
      if (n.cont) prov.push(`continuation of ${n.cont}`);
      prov.push(`id ${n.id}`);
      frag.append(el('p', { class: 'note', text: prov.join(' · ') }));
      return frag;
    },

    /* --- symbol dossier --- */
    symbol(state) {
      const P = palette();
      const frag = document.createDocumentFragment();
      const sym = state.symbol;
      const row = state.bundle.symbols.find((s) => s.t === sym);
      const s = getSeries(sym);
      if (!row || !s) {
        frag.append(el('p', { class: 'note', text: `No price history for ${sym}.` }));
        return frag;
      }

      frag.append(el('div', { class: 'stats' },
        this.stat('Last', fmtPx(row.last), row.to),
        this.stat('1d', fmtPct(row.d1, 2), '', row.d1 >= 0 ? P.up : P.down),
        this.stat('20d', fmtPct(row.d20, 1), '', row.d20 >= 0 ? P.up : P.down),
        this.stat('YTD', fmtPct(row.ytd, 1), '', row.ytd >= 0 ? P.up : P.down),
        this.stat('Vol 20d', row.vol20 !== null ? fmtPct(row.vol20, 1) : '—', 'annualised')));

      const dl = el('dl', { class: 'kv' });
      const add = (k, v) => { dl.append(el('dt', { text: k }), el('dd', { text: v })); };
      add('range', `${fmtPx(row.lo)} – ${fmtPx(row.hi)}`);
      add('history', `${row.n} bars · ${row.from} → ${row.to}`);
      add('bars', row.ohlc ? 'OHLC + volume' : 'close only');
      if (row.cls) add('class', row.cls);
      if (row.name) add('name', row.name);
      if (row.section) add('list', row.section);
      add('narratives', String(row.nar));
      frag.append(el('div', { class: 'sect' }, el('h4', {}, 'Instrument'), dl));

      const mentions = state.bundle.narratives.filter((n) => n.tk.some((t) => t.t === sym));
      if (mentions.length) {
        frag.append(el('div', { class: 'sect' },
          el('h4', {}, `Narrative history (${mentions.length})`),
          ...mentions.slice(0, 14).map((n) => {
            const g = n.g ? n.g.ltr : null;
            const side = (n.tk.find((t) => t.t === sym) || {}).side || '';
            const r = n.ret.find((x) => x.t === sym);
            const exc = r && r.td !== null && r.std !== null ? r.td - r.std : null;
            return el('div', {
              class: 'tapeline', 'data-nar': n.id, style: 'grid-template-columns:48px 34px 1fr auto',
            },
              el('span', { class: 'tt', text: (n.at || '').slice(0, 10) }),
              el('span', {}, g ? badge(g, `g-${g}`) : badge('—', 'na')),
              el('span', { class: 'tx', title: n.title, text: `${side ? side + ' · ' : ''}${n.title}` }),
              el('span', { class: exc === null ? 'note' : dirClass(exc), text: exc === null ? '' : fmtPct(exc, 0) }));
          })));
      } else {
        frag.append(el('p', { class: 'note', text: 'No narrative has referenced this symbol.' }));
      }
      return frag;
    },

    stat(label, value, note, color) {
      return el('div', { class: 'stat' },
        el('span', { class: 'sl', text: label }),
        el('span', { class: 'sv', style: color ? `color:${color}` : null, text: String(value) }),
        note ? el('span', { class: 'sn', text: note }) : '');
    },

    textSect(title, text) {
      return el('div', { class: 'sect' }, el('h4', {}, title), el('p', { text: text || '—' }));
    },

    listSect(title, items) {
      return el('div', { class: 'sect' }, el('h4', {}, title),
        el('ul', {}, ...items.map((i) => el('li', { text: i }))));
    },
  };

  /* ──────────────────────── lower tab renderers ─────────────────────── */
  const Lower = {
    returns(state) {
      const P = palette();
      const wrap = el('div');
      const sym = state.symbol;
      const rets = [];
      for (const n of state.bundle.narratives) {
        for (const r of n.ret) {
          if (r.t !== sym) continue;
          rets.push({ n, r });
        }
      }

      if (!rets.length) {
        wrap.append(el('p', { class: 'note', text: `No realised narrative returns for ${sym}. The blotter's "Realised vs SPY" block covers names that carried a thesis; pick one on the right, or load a symbol such as NVDA or GLD.` }));
        const all = this.leaderTable(state);
        if (all) wrap.append(all);
        return wrap;
      }

      const cards = el('div', { class: 'chartrow' });
      for (const { n, r } of rets.slice(0, 6)) {
        const rows = [['h5', 'sh5', '5d'], ['h20', 'sh20', '20d'], ['h60', 'sh60', '60d'], ['td', 'std', 'live']]
          .filter(([k]) => r[k] !== null && r[k] !== undefined)
          .map(([k, sk, lab]) => ({
            label: lab,
            value: r[sk] !== null && r[sk] !== undefined ? r[k] - r[sk] : r[k],
            note: fmtPct(r[k], 0),
          }));
        cards.append(el('div', { class: 'chartcard', 'data-nar': n.id },
          el('h4', {}, el('span', { text: n.title.slice(0, 44), style: 'color:var(--ink-2)' }),
            el('span', { text: `${(n.at || '').slice(0, 10)} · ${n.g ? n.g.ltr : '—'}` })),
          el('div', { class: 'cleg' }, el('span', { text: 'excess over SPY, same window · raw in grey' })),
          viz.barCard(rows, { w: 290 })));
      }
      wrap.append(cards);
      return wrap;
    },

    leaderTable(state) {
      const a = state.bundle.alpha;
      if (!a.leaders.length) return null;
      const mk = (title, rows) => el('div', { class: 'chartcard' },
        el('h4', {}, el('span', { text: title })),
        viz.barCard(rows.map((r) => ({ label: r.t, value: r.exc, note: r.g })), { w: 290 }));
      return el('div', { class: 'chartrow' },
        mk('Best excess vs SPY, to date', state.bundle.alpha.leaders.slice(0, 8)),
        mk('Worst excess vs SPY, to date', state.bundle.alpha.laggards.slice(0, 8)));
    },

    regime(state) {
      const P = palette();
      const hist = state.bundle.regime;
      const wrap = el('div');
      if (!hist.length) { wrap.append(el('p', { class: 'note', text: 'No regime history yet.' })); return wrap; }
      const now = hist[hist.length - 1];

      wrap.append(el('div', { class: 'stats' },
        Detail.stat('State', now.label, `as of ${now.asof || '—'}`, REGIME_COLOR(now.label, P)),
        Detail.stat('Temperature', fmtPct(now.temp, 2), 'annualised'),
        Detail.stat('Entropy S', fmtNum(now.S, 3), `eta ${fmtNum(now.eta, 3)}`),
        Detail.stat('KL D', fmtNum(now.kl, 3), `threshold ${fmtNum(now.klt, 3)}`),
        Detail.stat('Heat', fmtPct(now.heat, 1), `budget ${fmtPct(now.budget, 0)}`),
        Detail.stat('Signal x', fmtNum(now.mult, 2), now.warn ? 'DRIFT WARNING' : 'no drift',
          now.warn ? P.status.critical : null)));

      const x = (r, i) => i;
      const card = (title, sub, series, opts) => el('div', { class: 'chartcard' },
        el('h4', {}, el('span', { text: title }), el('span', { text: sub })),
        series.length > 1 ? el('div', { class: 'cleg' }, ...series.map((s) =>
          el('span', { html: `<i style="background:${s.color}"></i>${esc(s.label)}` }))) : '',
        viz.lineCard(series, opts));

      const row = el('div', { class: 'chartrow' });
      row.append(card('Temperature', 'realised vol, annualised',
        [{ label: 'T', color: P.cat[4], points: hist.map((r, i) => ({ x: x(r, i), y: r.temp })) }],
        { w: 290, h: 96, yFmt: (v) => fmtPct(v, 0), zero: true }));

      row.append(card('Entropy', 'observed vs equilibrium vs threshold',
        [{ label: 'S', color: P.cat[1], points: hist.map((r, i) => ({ x: x(r, i), y: r.S })) },
         { label: 'S eq', color: P.cat[3], points: hist.map((r, i) => ({ x: x(r, i), y: r.Seq })), dash: [3, 3], width: 1.5 },
         { label: 'S hi', color: P.neutral, points: hist.map((r, i) => ({ x: x(r, i), y: r.Shi })), dash: [2, 4], width: 1 }],
        { w: 290, h: 96, yFmt: (v) => fmtNum(v, 2) }));

      row.append(card('KL divergence', 'observed vs Boltzmann, with threshold',
        [{ label: 'D', color: P.cat[0], points: hist.map((r, i) => ({ x: x(r, i), y: r.kl })) },
         { label: 'threshold', color: P.neutral, points: hist.map((r, i) => ({ x: x(r, i), y: r.klt })), dash: [2, 4], width: 1 }],
        { w: 290, h: 96, yFmt: (v) => fmtNum(v, 2), zero: true }));

      row.append(card('Portfolio heat', 'fraction of equity at risk',
        [{ label: 'heat', color: P.cat[2], points: hist.map((r, i) => ({ x: x(r, i), y: r.heat })) }],
        { w: 290, h: 96, yFmt: (v) => fmtPct(v, 0), zero: true }));

      row.append(card('Signal multiplier', 'size scaler the detector hands the book',
        [{ label: 'x', color: P.gold, points: hist.map((r, i) => ({ x: x(r, i), y: r.mult })) }],
        { w: 290, h: 96, yFmt: (v) => fmtNum(v, 1), zero: true }));
      wrap.append(row);

      wrap.append(el('div', { class: 'sect', style: 'margin-top:6px' },
        el('h4', {}, 'State history'),
        viz.stripCard(hist.map((r) => ({ color: REGIME_COLOR(r.label, P) })), { w: 600, h: 14 }),
        el('div', { class: 'cleg' }, ...['TRENDING', 'CHOPPY', 'TRANSITION', 'CRISIS'].map((l) =>
          el('span', { html: `<i style="background:${REGIME_COLOR(l, P)}"></i>${l}` })),
          el('span', { text: `oldest → newest · ${hist.length} observations` }))));

      const tbl = el('table');
      tbl.append(el('thead', {}, el('tr', {},
        el('th', { class: 'l' }, 'Computed'), el('th', { class: 'l' }, 'State'),
        el('th', {}, 'T'), el('th', {}, 'S'), el('th', {}, 'eta'),
        el('th', {}, 'D'), el('th', {}, 'Heat'), el('th', {}, 'x'), el('th', {}, 'Warn'))));
      tbl.append(el('tbody', {}, ...[...hist].reverse().map((r) => el('tr', {},
        el('td', { class: 'l mut' }, fmtStamp(r.at)),
        el('td', { class: 'l', style: `color:${REGIME_COLOR(r.label, P)}` }, r.label),
        el('td', {}, fmtPct(r.temp, 1)), el('td', {}, fmtNum(r.S, 3)),
        el('td', {}, fmtNum(r.eta, 3)), el('td', {}, fmtNum(r.kl, 3)),
        el('td', {}, fmtPct(r.heat, 1)), el('td', {}, fmtNum(r.mult, 2)),
        el('td', { class: r.warn ? 'dn' : 'mut' }, r.warn ? 'DRIFT' : '—')))));
      wrap.append(el('div', { class: 'sect' }, el('h4', {}, 'Observations'), tbl));
      return wrap;
    },

    alpha(state) {
      const P = palette();
      const a = state.bundle.alpha;
      const wrap = el('div');
      const horizons = a.horizons;

      const byH = horizons.map((h) => a.by_horizon[h]).filter(Boolean);
      if (!byH.length) {
        wrap.append(el('p', { class: 'note', text: 'No realised returns computed yet. Run the pipeline so narrative_returns fills.' }));
        return wrap;
      }

      const tot = a.by_horizon[horizons[horizons.length - 1]];
      wrap.append(el('div', { class: 'stats' },
        Detail.stat('Observations', tot.n, 'ticker × narrative'),
        Detail.stat('Hit rate', fmtPct(tot.win, 1), 'raw return > 0',
          tot.win >= 0.5 ? P.up : P.down),
        Detail.stat('Beat SPY', tot.beat === null ? '—' : fmtPct(tot.beat, 1), 'same window',
          (tot.beat ?? 0) >= 0.5 ? P.up : P.down),
        Detail.stat('Mean excess', tot.exc_mean === null ? '—' : fmtPct(tot.exc_mean, 2), 'vs SPY',
          (tot.exc_mean ?? 0) >= 0 ? P.up : P.down),
        Detail.stat('Median excess', tot.exc_med === null ? '—' : fmtPct(tot.exc_med, 2), 'vs SPY',
          (tot.exc_med ?? 0) >= 0 ? P.up : P.down)));

      const row = el('div', { class: 'chartrow' });

      row.append(el('div', { class: 'chartcard' },
        el('h4', {}, el('span', { text: 'Mean excess by horizon' }), el('span', { text: 'vs SPY' })),
        viz.barCard(horizons.filter((h) => a.by_horizon[h]).map((h) => ({
          label: h, value: a.by_horizon[h].exc_mean, note: `n${a.by_horizon[h].n}`,
        })), { w: 290 })));

      row.append(el('div', { class: 'chartcard' },
        el('h4', {}, el('span', { text: 'Hit rate by horizon' }), el('span', { text: 'raw > 0' })),
        viz.barCard(horizons.filter((h) => a.by_horizon[h]).map((h) => ({
          label: h, value: a.by_horizon[h].win - 0.5, note: fmtPct(a.by_horizon[h].win, 0),
        })), { w: 290, fmt: (v) => fmtPct(v + 0.5, 0) }),
        el('p', { class: 'note', text: 'bars measure distance from a 50% coin flip' })));

      const grades = Object.keys(a.by_grade).filter((g) => a.by_grade[g]['20d']);
      if (grades.length) {
        row.append(el('div', { class: 'chartcard' },
          el('h4', {}, el('span', { text: 'Excess by grade, 20d' }), el('span', { text: 'does the grader add value?' })),
          viz.barCard(grades.map((g) => ({
            label: g, value: a.by_grade[g]['20d'].exc_mean, note: `n${a.by_grade[g]['20d'].n}`,
          })), { w: 290 })));
      }

      const bands = Object.keys(a.by_band).filter((b) => a.by_band[b]['20d']);
      if (bands.length) {
        row.append(el('div', { class: 'chartcard' },
          el('h4', {}, el('span', { text: 'Excess by entropy band, 20d' }), el('span', { text: 'risk label vs outcome' })),
          viz.barCard(bands.map((b) => ({
            label: b, value: a.by_band[b]['20d'].exc_mean, note: `n${a.by_band[b]['20d'].n}`,
          })), { w: 290 })));
      }

      if (a.scatter.length) {
        row.append(el('div', { class: 'chartcard' },
          el('h4', {}, el('span', { text: 'Entropy risk vs 20d excess' }), el('span', { text: `n${a.scatter.length}` })),
          el('div', { class: 'cleg' }, ...GRADE_ORDER.filter((g) => a.scatter.some((p) => p.g === g)).map((g) =>
            el('span', { html: `<i style="background:${gradeColor(g, P)};height:7px;border-radius:50%;width:7px"></i>${g}` }))),
          viz.scatterCard(a.scatter.map((p) => ({ x: p.x, y: p.y, c: gradeColor(p.g, P), label: p.t })),
            { w: 290, h: 120, xFmt: (v) => `ent ${Math.round(v)}`, yFmt: (v) => fmtPct(v, 0) })));
      }
      wrap.append(row);

      const tbl = el('table');
      tbl.append(el('thead', {}, el('tr', {},
        el('th', { class: 'l' }, 'Horizon'), el('th', {}, 'n'), el('th', {}, 'Mean raw'),
        el('th', {}, 'Median raw'), el('th', {}, 'Hit'), el('th', {}, 'Mean excess'),
        el('th', {}, 'Beat SPY'), el('th', {}, 'Best'), el('th', {}, 'Worst'))));
      tbl.append(el('tbody', {}, ...horizons.filter((h) => a.by_horizon[h]).map((h) => {
        const v = a.by_horizon[h];
        return el('tr', {},
          el('td', { class: 'l' }, h), el('td', { class: 'mut' }, v.n),
          el('td', { class: dirClass(v.raw_mean) }, fmtPct(v.raw_mean, 2)),
          el('td', { class: dirClass(v.raw_med) }, fmtPct(v.raw_med, 2)),
          el('td', {}, fmtPct(v.win, 0)),
          el('td', { class: dirClass(v.exc_mean) }, fmtPct(v.exc_mean, 2)),
          el('td', {}, v.beat === null ? '—' : fmtPct(v.beat, 0)),
          el('td', { class: 'up' }, fmtPct(v.best, 0)),
          el('td', { class: 'dn' }, fmtPct(v.worst, 0)));
      })));
      wrap.append(el('div', { class: 'sect' }, el('h4', {}, 'Full table'), tbl,
        el('p', { class: 'note', text: 'Excess = narrative return minus SPY over the identical window (narrative_returns). Every window counts once per ticker per narrative; overlapping theses on the same name are not de-duplicated.' })));
      return wrap;
    },

    tape(state) {
      const wrap = el('div');
      const items = state.bundle.tape;
      if (!items.length) { wrap.append(el('p', { class: 'note', text: 'No feed items.' })); return wrap; }

      const srcs = ['all', ...Array.from(new Set(items.map((i) => i.src)))];
      wrap.append(el('div', { class: 'pillrow', style: 'margin-bottom:4px' },
        ...srcs.map((s) => el('span', {
          class: `pill ${state.tapeSrc === s || (s === 'all' && !state.tapeSrc) ? 'on' : ''}`,
          'data-tapesrc': s,
        }, s))));

      const shown = items.filter((i) => !state.tapeSrc || state.tapeSrc === 'all' || i.src === state.tapeSrc);
      const list = el('div', { class: 'tapelist' });
      for (const i of shown.slice(0, 260)) {
        list.append(el('div', { class: `tapeline ${i.src === 'rss' ? 'rss' : ''}`, 'data-url': i.url || '' },
          el('span', { class: 'tt', text: fmtAgo(i.at), title: fmtStamp(i.at) }),
          el('span', { class: 'tw', text: i.who, title: i.who }),
          el('span', { class: 'tx', text: i.txt, title: i.txt })));
      }
      wrap.append(list);
      wrap.append(el('p', { class: 'note', text: `${shown.length} items · newest first · click opens the source` }));
      return wrap;
    },

    notes(state) {
      const P = palette();
      const wrap = el('div');
      const notes = state.bundle.notes;
      if (!notes.length) {
        wrap.append(el('p', { class: 'note', text: 'No analyst notes. They live in the analyst_notes table.' }));
        return wrap;
      }
      for (const n of notes) {
        const vcol = { positive: P.up, near_zero: P.neutral, negative: P.down, hedge_only: P.status.warn }[n.verdict] || P.neutral;
        wrap.append(el('div', { class: 'sect' },
          el('h4', {}, `${(n.at || '').slice(0, 10)} · ${n.who} · ${n.kind}`),
          el('p', { style: 'color:var(--ink);font-weight:600', text: n.title }),
          el('div', { class: 'stats' },
            Detail.stat('Verdict', n.verdict || '—', '', vcol),
            Detail.stat('Alpha score', n.score === null ? '—' : fmtNum(n.score, 2), '-1 … +1',
              (n.score ?? 0) >= 0 ? P.up : P.down),
            n.run ? Detail.stat('Run', n.run, n.nar ? 'narrative linked' : '') : ''),
          el('p', { text: n.tldr }),
          n.tags.length ? el('div', { class: 'pillrow' }, ...n.tags.map((t) => el('span', { class: 'pill', text: t }))) : '',
          el('details', {}, el('summary', { class: 'note', text: 'full memo' }),
            el('div', { class: 'bodytext', text: n.body }))));
      }
      return wrap;
    },

    runs(state) {
      const P = palette();
      const runs = state.bundle.runs;
      const wrap = el('div');
      const narByRun = {};
      for (const n of state.bundle.narratives) narByRun[n.run] = (narByRun[n.run] || 0) + 1;

      wrap.append(el('div', { class: 'chartrow' },
        el('div', { class: 'chartcard' },
          el('h4', {}, el('span', { text: 'Feed items per run' }), el('span', { text: `${runs.length} runs` })),
          viz.lineCard([{ label: 'feeds', color: P.cat[3], points: [...runs].reverse().map((r, i) => ({ x: i, y: r.feeds })) }],
            { w: 290, h: 92, yFmt: (v) => String(Math.round(v)), zero: true })),
        el('div', { class: 'chartcard' },
          el('h4', {}, el('span', { text: 'Narratives per run' }), el('span', { text: 'extracted' })),
          viz.lineCard([{ label: 'narratives', color: P.cat[0], points: [...runs].reverse().map((r, i) => ({ x: i, y: r.nar })) }],
            { w: 290, h: 92, yFmt: (v) => String(Math.round(v)), zero: true }))));

      const tbl = el('table');
      tbl.append(el('thead', {}, el('tr', {},
        el('th', {}, 'Run'), el('th', { class: 'l' }, 'When'), el('th', {}, 'Window'),
        el('th', {}, 'Feeds'), el('th', {}, 'Narratives'), el('th', {}, 'Stored'))));
      tbl.append(el('tbody', {}, ...runs.map((r) => el('tr', { 'data-run': r.id },
        el('td', {}, r.id), el('td', { class: 'l mut' }, fmtStamp(r.at)),
        el('td', {}, `${r.hours}h`), el('td', {}, r.feeds),
        el('td', {}, r.nar), el('td', { class: 'mut' }, narByRun[r.id] || 0)))));
      wrap.append(el('div', { class: 'sect' }, el('h4', {}, 'Pipeline runs'), tbl,
        el('p', { class: 'note', text: '"Narratives" is what the run reported; "Stored" is what survives in the table today.' })));
      return wrap;
    },
  };

  RH.panels = { Monitor, Blotter, Detail, Lower, gradeColor, GRADE_ORDER, badge };
})(window.RH);
