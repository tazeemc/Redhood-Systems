"""Long-only ledger for narrative-extracted tickers: forward returns vs SPY, novelty, robustness, heat.

Entry rule: first close on/after the run date; runs at/after 20:00 UTC (after the US close)
enter at the next session's close (no look-ahead).  Novelty: a pair is a 'first mention' when
the ticker had not appeared as a long on any STRICTLY EARLIER run date in this ledger.
"""
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')   # paper/ ; the repository root is ROOT/..
REPO = os.path.join(ROOT, '..')
import sys, json, math, sqlite3
import numpy as np, pandas as pd
sys.path.insert(0, REPO)                       # the shipped (v1.4) grader + pnl entry rule
from redhood_grader import grade
from redhood_pnl import entry_date_for_run
D = os.path.join(ROOT, 'data') + '/'
P = json.load(open(D + 'prices.json')); prices = {k: pd.Series(v).sort_index() for k, v in P['prices'].items()}
for k in prices: prices[k].index = pd.to_datetime(prices[k].index)
types = P['types']
con = sqlite3.connect('file:' + os.path.join(REPO, 'redhood.db') + '?mode=ro', uri=True); con.row_factory = sqlite3.Row
N = con.execute("select n.*, r.run_at from narratives n join runs r on r.id=n.run_id order by r.run_at").fetchall()
reg = pd.read_csv(D + 'regime_repo.csv', parse_dates=['date']).set_index('date')          # deployed detector
regv2 = pd.read_csv(D + 'regime_v2.csv', parse_dates=['date']).set_index('date')          # shipped v2 detector
spy = prices['SPY']
LAST = spy.index[-1].date().isoformat()

def fwd_return(series, entry_date, h):
    idx = series.index.searchsorted(pd.Timestamp(entry_date))
    if idx >= len(series): return None
    j = len(series) - 1 if h is None else idx + h
    if j >= len(series): return None
    return float(series.iloc[j] / series.iloc[idx] - 1), series.index[idx], series.index[j]

rows = []
for n in N:
    g = grade(n['hypothesis'] or '', n['catalysts'])          # v1.4 grader: false positives already excluded
    entry_after = entry_date_for_run(n['run_at'])
    for t in g.long_tickers:
        if t not in prices: continue
        s = prices[t]
        rec = dict(narrative_id=n['id'], run_at=n['run_at'][:10], run_ts=n['run_at'][:16], ticker=t, itype=types.get(t),
                   entropy_risk=n['entropy_risk'], band=n['entropy_band'], conviction=n['conviction_size'], grade=g.total, letter=g.letter)
        ok = True
        for h in (5, 20, 60, None):
            fr = fwd_return(s, entry_after, h); fs = fwd_return(spy, entry_after, h)
            key = 'todate' if h is None else f'h{h}'
            rec[key] = fr[0] if fr else np.nan; rec[key + '_spy'] = fs[0] if fs else np.nan
            if fr and h is None: rec['entry_date'] = fr[1].date().isoformat()
        if 'entry_date' not in rec: continue
        run_date = pd.Timestamp(n['run_at'][:10])
        d = reg.index[max(0, reg.index.searchsorted(run_date) - 1)]
        rec['regime_repo'] = reg.loc[d, 'label']; rec['mult_repo'] = reg.loc[d, 'mult']
        d2 = regv2.index[max(0, regv2.index.searchsorted(run_date) - 1)]
        rec['regime_v2'] = regv2.loc[d2, 'label']
        rows.append(rec)
L = pd.DataFrame(rows).sort_values(['run_at', 'run_ts', 'ticker']).reset_index(drop=True)
# novelty on strictly earlier run DATES
first_date = L.groupby('ticker').run_at.transform('min')
L['first'] = L.run_at == first_date
earlier = {}
pm = []
for _, r in L.iterrows():
    pm.append(sum(1 for d in earlier.get(r.ticker, []) if d < r.run_at))
    earlier.setdefault(r.ticker, []).append(r.run_at)
L['prior_mentions'] = pm
CLUSTERS = {'defense': 'LMT RTX NOC GD LHX ITA DFEN KTOS AVAV EUAD'.split(),
            'energy': 'XLE USO XOP OXY CVX XOM SLB HAL VLO MPC PSX DVN FANG UCO BNO TTE EQNR LNG GLNG FLNG STNG'.split(),
            'gold': ['GLD', 'GDX'],
            'semis_ai': 'NVDA AMD SMH SOXL MU AVGO TSM ASML KLAC QCOM SMCI DELL MSFT GOOGL ORCL PLTR CRM ADBE'.split()}
L['cluster'] = 'other'
for k, v in CLUSTERS.items(): L.loc[L.ticker.isin(v), 'cluster'] = k
L['month'] = L.run_at.str[:7]
L.to_csv(D + 'ledger.csv', index=False)
print('ledger rows:', len(L), 'tickers:', L.ticker.nunique(), 'narratives:', L.narrative_id.nunique(), 'runs:', L.run_ts.nunique(), 'run dates:', L.run_at.nunique())
print('entry span', L.entry_date.min(), '->', L.entry_date.max(), '| to-date =', LAST)
print('instrument types (pairs):', L.itype.value_counts().to_dict())
print('after-close entries shifted: %d pairs' % (L.entry_date > L.run_at).sum())
print('SPY %s -> %s: %.2f%%' % (L.entry_date.min(), LAST, 100 * (spy.iloc[-1] / spy.loc[L.entry_date.min()] - 1)))

HS = ('h5', 'h20', 'h60', 'todate')
def tstat(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float('nan')
def summarize(df, label, res=None, quiet=False):
    out = {}
    for h in HS:
        sub = df.dropna(subset=[h]); xs = sub[h] - sub[h + '_spy']
        if len(xs) == 0: continue
        bydate = sub.assign(ex=xs).groupby('run_at').ex.mean()
        bymonth = sub.assign(ex=xs).groupby('month').ex.mean()
        out[h] = dict(n=int(len(xs)), mean=float(sub[h].mean()), hit_raw=float((sub[h] > 0).mean()), mean_excess=float(xs.mean()),
                      median_excess=float(xs.median()), excess_hit=float((xs > 0).mean()), t_naive=tstat(xs),
                      n_dates=int(len(bydate)), t_bydate=tstat(bydate), n_months=int(len(bymonth)), t_bymonth=tstat(bymonth))
        if not quiet:
            print(f'  {label:30s} {h:7s} n={len(xs):3d} raw {100*sub[h].mean():6.2f}% | excess mean {100*xs.mean():6.2f}% med {100*xs.median():6.2f}% hit {100*(xs>0).mean():5.1f}% '
                  f'| t: naive {tstat(xs):5.2f}  by-date({len(bydate)}) {tstat(bydate):5.2f}  by-month({len(bymonth)}) {tstat(bymonth):5.2f}')
    if res is not None: res[label] = out
    return out

res = {}
print('\n=== ALL ==='); summarize(L, 'all', res)
print('\n=== novelty (strictly earlier run dates) ===')
summarize(L[L['first']], 'first', res); summarize(L[~L['first']], 'repeat', res); summarize(L[L.prior_mentions >= 3], 'fourth_plus', res)
print('\n=== novelty excluding defence and gold ===')
X = L[~L.cluster.isin(['defense', 'gold'])]
summarize(X[X['first']], 'first_ex_defgold', res); summarize(X[~X['first']], 'repeat_ex_defgold', res)
print('\n=== paired within run date: mean(repeat) - mean(first) ===')
paired = {}
for h in HS:
    sub = L.dropna(subset=[h]).assign(ex=lambda d: d[h] - d[h + '_spy'])
    g = sub.groupby(['run_at', 'first']).ex.mean().unstack()
    g = g.dropna()
    diff = g[False] - g[True]
    paired[h] = dict(n_dates=int(len(diff)), mean_diff=float(diff.mean()), t=tstat(diff))
    print(f'  {h:7s} dates with both={len(diff):2d} mean(repeat-first)={100*diff.mean():6.2f}%  t={tstat(diff):5.2f}')
res['paired'] = paired
sub = X.dropna(subset=['h60']).assign(ex=lambda d: d.h60 - d.h60_spy); g = sub.groupby(['run_at', 'first']).ex.mean().unstack().dropna(); diff = g[False] - g[True]
print(f'  ex-defence/gold h60: dates={len(diff)} mean(repeat-first)={100*diff.mean():6.2f}% t={tstat(diff):5.2f}')
res['paired_ex_defgold_h60'] = dict(n_dates=int(len(diff)), mean_diff=float(diff.mean()), t=tstat(diff))
# autocorrelation of the run-date means (repeat subset, 60d)
sub = L[~L['first']].dropna(subset=['h60']).assign(ex=lambda d: d.h60 - d.h60_spy).groupby('run_at').ex.mean()
ac = float(np.corrcoef(sub.values[:-1], sub.values[1:])[0, 1]); print(f'  lag-1 autocorrelation of run-date means (repeat, 60d): {ac:.2f}')
res['ac1_repeat_h60'] = ac
print('\n=== bands / verdicts / regimes / themes / months ===')
for b in ('low', 'mid', 'high'): summarize(L[L.band == b], f'band_{b}', res)
for cv in (0.0, 0.25, 0.5): summarize(L[L.conviction == cv], f'conv_{cv}', res)
summarize(L[L.conviction.isna()], 'conv_none', res)
for rg in ('TRENDING', 'CHOPPY'): summarize(L[L.regime_repo == rg], f'regime_repo_{rg}', res)
for rg in ('TRENDING', 'CHOPPY', 'TRANSITION'):
    if (L.regime_v2 == rg).any(): summarize(L[L.regime_v2 == rg], f'regime_v2_{rg}', res)
for k in ['defense', 'energy', 'gold', 'semis_ai', 'other']: summarize(L[L.cluster == k], f'cluster_{k}', res)
for m in sorted(L.month.unique()): summarize(L[L.month == m], f'month_{m}', res, quiet=True)
print('  by month (20d / 60d excess, n):', {m: (round(100 * res[f'month_{m}']['h20']['mean_excess'], 1) if 'h20' in res[f'month_{m}'] else None,
                                            round(100 * res[f'month_{m}']['h60']['mean_excess'], 1) if 'h60' in res[f'month_{m}'] else None,
                                            res[f'month_{m}']['todate']['n']) for m in sorted(L.month.unique())})
print('  defence first vs repeat h60:', round(100 * (L[(L.cluster == 'defense') & L['first']].pipe(lambda d: (d.h60 - d.h60_spy).mean())), 1),
      round(100 * (L[(L.cluster == 'defense') & ~L['first']].pipe(lambda d: (d.h60 - d.h60_spy).mean())), 1))
print('  repeat composition: defence %d gold %d of %d' % ((L[~L['first']].cluster == 'defense').sum(), (L[~L['first']].cluster == 'gold').sum(), (~L['first']).sum()))
# weighted 20d excess
L['w_flat'] = 1.0; L['w_conv'] = L.conviction.fillna(0.5) * 2; L['w_regime'] = L.mult_repo.clip(0, 2.5); L['w_both'] = L.w_conv * L.w_regime
print('\n=== weighted 20-day excess P&L ===')
for w in ('w_flat', 'w_conv', 'w_regime', 'w_both'):
    sub = L.dropna(subset=['h20']); ex = (sub.h20 - sub.h20_spy); pnl = (sub[w] * 2500 * ex).sum(); gross = (sub[w] * 2500).sum()
    print(f'  {w:9s}: deployed ${gross:>10,.0f}  excess P&L ${pnl:>9,.0f} = {100*pnl/gross:5.2f}%')
    res['weighted_' + w] = dict(deployed=float(gross), excess_pnl=float(pnl), pct=float(100 * pnl / gross))
# top tickers
tk = L.groupby('ticker').agg(n=('h20', 'size'), h20=('h20', 'mean'), h60=('h60', 'mean')).sort_values('n', ascending=False)
print('\n top tickers:', [(t, int(r.n), round(100 * r.h20, 1)) for t, r in tk.head(8).iterrows()])
# ---------- heat --------------------------------------------------------------------
EQ, STOP = 100_000.0, 0.08
events = []
for _, r in L.iterrows():
    e = pd.Timestamp(r.entry_date); idx = spy.index.searchsorted(e); x = min(idx + 20, len(spy) - 1)
    events.append((e, +1)); events.append((spy.index[x], -1))
ev = pd.DataFrame(events, columns=['date', 'd']).groupby('date').d.sum().sort_index()
open_pos = ev.cumsum().reindex(spy.index, method='ffill').fillna(0).loc['2026-02-20':]
heat = open_pos * 2500 * STOP / EQ; notional = open_pos * 2500 / EQ
hot = heat[heat > 0.06]
print('\n[heat] max open %d on %s; mean %.1f; notional max %.0f%%; heat max %.1f%% mean %.2f%%; days notional>100%%: %d; heat>6%%: %d (%s..%s and %s..%s)' % (
    open_pos.max(), open_pos.idxmax().date(), open_pos.mean(), 100 * notional.max(), 100 * heat.max(), 100 * heat.mean(), (notional > 1).sum(), len(hot),
    hot.index[0].date(), hot.loc[:'2026-05-31'].index[-1].date(), hot.loc['2026-06-01':].index[0].date(), hot.index[-1].date()))
pd.DataFrame(dict(open_positions=open_pos, heat=heat, notional=notional)).to_csv(D + 'heat.csv')
res['heat'] = dict(max_open=int(open_pos.max()), max_open_date=str(open_pos.idxmax().date()), mean_open=float(open_pos.mean()), max_notional=float(notional.max()),
                   max_heat=float(heat.max()), mean_heat=float(heat.mean()), days_notional_gt_1=int((notional > 1).sum()), days_heat_gt_6=int(len(hot)))
res['meta'] = dict(rows=int(len(L)), tickers=int(L.ticker.nunique()), narratives=int(L.narrative_id.nunique()), runs=int(L.run_ts.nunique()), run_dates=int(L.run_at.nunique()),
                   last_date=LAST, shifted=int((L.entry_date > L.run_at).sum()), itypes=L.itype.value_counts().to_dict())
json.dump(res, open(D + 'pnl_summary.json', 'w'), indent=1)
