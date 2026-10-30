"""Figures for the revised paper (PDF, single axis per panel, restrained palette)."""
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')   # paper/ ; the repository root is ROOT/..
REPO = os.path.join(ROOT, '..')
import json, math, sqlite3, collections, sys
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
D = os.path.join(ROOT, 'data') + '/'; F = os.path.join(ROOT, 'figures') + '/'
import os; os.makedirs(F, exist_ok=True)
BLUE, ORANGE, AQUA, VIOLET = '#2a78d6', '#eb6834', '#1baf7a', '#6250d6'
INK, INK2, GRID = '#0b0b0b', '#52514e', '#e4e3df'
REG = {'TRENDING': '#cde2fb', 'CHOPPY': '#fde3b0', 'CRISIS': '#f4b8b8', 'TRANSITION': '#d9d3f5'}
plt.rcParams.update({'font.family': 'serif', 'font.size': 9, 'axes.edgecolor': INK2, 'axes.labelcolor': INK, 'xtick.color': INK2, 'ytick.color': INK2,
                     'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False, 'legend.frameon': False,
                     'figure.dpi': 150, 'savefig.bbox': 'tight'})
spy = pd.read_csv(D + 'SPY.csv', parse_dates=['date']).set_index('date')['close']
R = pd.read_csv(D + 'regime_repo.csv', parse_dates=['date']).set_index('date')
E = pd.read_csv(D + 'regime_stdbins.csv', parse_dates=['date']).set_index('date')
V = pd.read_csv(D + 'regime_v2.csv', parse_dates=['date']).set_index('date')

def shade(ax, labels, alpha=0.9):
    """Colour background by regime label (contiguous runs)."""
    lab = labels.dropna(); start = lab.index[0]; cur = lab.iloc[0]
    for d, v in lab.items():
        if v != cur:
            ax.axvspan(start, d, color=REG[cur], alpha=alpha, lw=0); start, cur = d, v
    ax.axvspan(start, lab.index[-1], color=REG[cur], alpha=alpha, lw=0)

# ---------------- Figure 1: SPY regime diagnostics -------------------------------------
fig, axes = plt.subplots(4, 1, figsize=(7.2, 8.2), sharex=True, gridspec_kw=dict(height_ratios=[1.3, 1, 1, 1.1]))
ax = axes[0]; ax.plot(spy.index, spy.values, color=INK, lw=1.0); ax.set_ylabel('SPY close (USD)')
ax.set_title('(a) SPY, 23 Oct 2024 – 22 Oct 2026', loc='left', fontsize=9, color=INK)
ax = axes[1]; ax.plot(R.index, 100 * R['T'], color=BLUE, lw=1.2, label='20-day T (repo)'); ax.plot(E.index, 100 * E['T'], color=ORANGE, lw=1.2, label='60-day T')
ax.axhline(15, color=INK2, lw=0.8, ls='--'); ax.text(spy.index[3], 15.8, r'$T_{\rm base}=15\%$', color=INK2, fontsize=8)
ax.set_ylabel('temperature T (% ann.)'); ax.legend(loc='upper right', fontsize=8); ax.set_title('(b) Market temperature (annualised realised volatility)', loc='left', fontsize=9)
ax = axes[2]; ax.plot(R.index, R['S'], color=BLUE, lw=1.2, label='range-adaptive bins (as deployed, k=10, N=20)')
ax.plot(E.index, E['S'], color=ORANGE, lw=1.2, label=r'fixed levels in units of $T_{\rm base}$ (k=10, N=60)')
ax.axhline(math.log(10), color=INK2, lw=0.8, ls=':'); ax.text(spy.index[3], math.log(10) + 0.03, r'$\ln 10$ (maximum for 10 bins)', color=INK2, fontsize=8)
ax.axhline(2.5, color='#d03b3b', lw=0.8, ls='--'); ax.text(spy.index[3], 2.53, r'deployed threshold $S_{\rm base}=2.5$ (unreachable)', color='#d03b3b', fontsize=8)
ax.set_ylim(1.2, 3.0); ax.set_ylabel('entropy S (nats)'); ax.legend(loc='upper right', fontsize=7.5, bbox_to_anchor=(1.0, 1.02)); ax.set_title('(c) Two entropy estimators on the same returns', loc='left', fontsize=9)
ax = axes[3]; ax.set_ylim(0, 2); ax.set_yticks([0.5, 1.5]); ax.set_yticklabels(['detector\nv2', 'as\ndeployed']); ax.grid(False)
lab = R['label']; start = lab.index[0]; cur = lab.iloc[0]
for d, v in lab.items():
    if v != cur: ax.axvspan(start, d, ymin=0.5, ymax=1.0, color=REG[cur], lw=0); start, cur = d, v
ax.axvspan(start, lab.index[-1], ymin=0.5, ymax=1.0, color=REG[cur], lw=0)
lab = V['label']; start = lab.index[0]; cur = lab.iloc[0]
for d, v in lab.items():
    if v != cur: ax.axvspan(start, d, ymin=0.0, ymax=0.5, color=REG[cur], lw=0); start, cur = d, v
ax.axvspan(start, lab.index[-1], ymin=0.0, ymax=0.5, color=REG[cur], lw=0)
fig.legend(handles=[Patch(color=REG[k], label=k.title()) for k in ['TRENDING', 'CHOPPY', 'CRISIS', 'TRANSITION']], loc='lower center', ncol=4, fontsize=8, bbox_to_anchor=(0.5, -0.01))
ax.set_title('(d) Regime labels', loc='left', fontsize=9); ax.axvline(pd.Timestamp('2026-02-22'), color=INK2, lw=0.8, ls='--')
ax.text(pd.Timestamp('2026-02-26'), 1.75, 'RedHood\nlive period', fontsize=7, color=INK2, va='top')
fig.align_ylabels(axes); plt.savefig(F + 'fig1_regimes.pdf'); plt.close()

# ---------------- Figure 2: Monte Carlo null distributions ----------------------------
rng = np.random.default_rng(3); N = 20; ds = 0.15 / np.sqrt(252)
def plug_entropy(x, bins):
    h, _ = np.histogram(x, bins=bins, density=True); p = h / (h.sum() + 1e-12); p = p[p > 0]; return float(-(p * np.log(p)).sum())
def repo_kl(x, bins=15):
    T = x.std(ddof=1) * np.sqrt(252); h, e = np.histogram(x, bins=bins, density=True); c = (e[:-1] + e[1:]) / 2; emp = h / (h.sum() + 1e-12)
    sigma = T / np.sqrt(252); b = np.exp(-np.abs(c) / (sigma + 1e-12)); b /= b.sum() + 1e-12; m = emp > 0
    return float(np.sum(emp[m] * np.log(emp[m] / (b[m] + 1e-12))))
def kl_fixed(x, bins):
    s = x.std(ddof=1); b = s / np.sqrt(2); h, e = np.histogram(x, bins=bins); emp = h / h.sum()
    cdf = lambda r: np.where(r < 0, 0.5 * np.exp(r / b), 1 - 0.5 * np.exp(-r / b)); ref = cdf(e[1:]) - cdf(e[:-1]); ref /= ref.sum(); m = emp > 0
    return float(np.sum(emp[m] * np.log(emp[m] / ref[m])))
lap20 = rng.laplace(0, ds / np.sqrt(2), size=(10000, 20)); lap60 = rng.laplace(0, ds / np.sqrt(2), size=(10000, 60))
S20 = np.array([plug_entropy(x, 10) for x in lap20]); KL20 = np.array([repo_kl(x) for x in lap20]); KL60 = np.array([kl_fixed(x, 7) for x in lap60])
fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.7), gridspec_kw=dict(wspace=0.18))
ax = axes[0]; ax.hist(S20, bins=40, color=BLUE, alpha=0.9); ax.axvline(math.log(10), color=INK2, ls=':', lw=1); ax.axvline(2.5, color='#d03b3b', ls='--', lw=1)
ax.text(math.log(10) - 0.02, ax.get_ylim()[1] * 0.92, r'$\ln 10$', ha='right', fontsize=8, color=INK2); ax.text(2.5 + 0.02, ax.get_ylim()[1] * 0.92, '2.5', fontsize=8, color='#d03b3b')
ax.set_xlabel('S (nats)'); ax.set_ylabel('simulations'); ax.set_title('(a) plug-in S, k=10, N=20', loc='left', fontsize=9); ax.set_yticks([])
ax = axes[1]; ax.hist(KL20, bins=40, color=BLUE, alpha=0.9); ax.axvline(0.25, color='#d03b3b', ls='--', lw=1); ax.text(0.26, ax.get_ylim()[1] * 0.92, 'alert 0.25', fontsize=8, color='#d03b3b')
ax.set_xlabel(r'$D_{KL}$ (nats)'); ax.set_title(r'(b) $D_{KL}$ as deployed, k=15, N=20', loc='left', fontsize=9); ax.set_yticks([]); ax.text(0.98, 0.78, '%.0f%% of null\nsamples exceed\nthe alert' % (100 * (KL20 > 0.25).mean()), transform=ax.transAxes, ha='right', fontsize=7.5, color=INK2)
ax = axes[2]; ax.hist(KL60, bins=40, color=ORANGE, alpha=0.9); q95 = 0.110; ax.axvline(q95, color=INK, ls='--', lw=1); ax.text(q95 + 0.005, ax.get_ylim()[1] * 0.92, 'shipped alert\n$D_{hi}$ = 0.110', fontsize=8, color=INK)
ax.set_xlabel(r'$D_{KL}$ (nats)'); ax.set_title(r'(c) calibrated $D_{KL}$, k=7, N=60', loc='left', fontsize=9); ax.set_yticks([])
plt.tight_layout(); plt.savefig(F + 'fig2_null.pdf'); plt.close()

# ---------------- Figure 3: Boltzmann occupation + densities ---------------------------
occ = pd.read_csv(D + 'occupation.csv'); EB = json.load(open(D + 'entropy_boltzmann_summary.json'))
r = np.log(spy / spy.shift(1)).dropna().values
fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))
ax = axes[0]; m = occ['count'] > 0
core = m & (occ.z.abs() <= 2)
ax.scatter(occ.E[m], np.log(occ.density[m]), color=BLUE, s=22, zorder=3, label='observed level occupation (all 500 returns)')
from scipy import stats
sl, ic, *_ = stats.linregress(occ.E[core], np.log(occ.density[core])); xx = np.linspace(0, 14, 50)
ax.plot(xx, ic + sl * xx, color=ORANGE, lw=1.4, label=r'Boltzmann line, core fit: $T_{\rm eff}=%.2f$' % (-1 / sl))
ax.set_xlabel(r'level energy $E=z^2/2$,  $z=r/\sigma$'); ax.set_ylabel(r'$\ln p(E)$'); ax.legend(fontsize=7.5, loc='lower left'); ax.set_title('(a) Occupation of fixed return levels', loc='left', fontsize=9)
far = m & (occ.z.abs() >= 4)
for e_, d_ in zip(occ.E[far], np.log(occ.density[far])): ax.annotate('', xy=(e_, d_), xytext=(e_, d_ + 2.5), arrowprops=dict(arrowstyle='->', color=INK2, lw=0.7))
ax.text(27, -13.5, 'April 2025 sessions, |z| = 4.3 – 9.6:\nthe Boltzmann line predicts none', fontsize=7.5, color=INK2, ha='center')
ax.set_ylim(-22, 1)
ax = axes[1]; bins = np.linspace(-0.07, 0.07, 57); ax.hist(r, bins=bins, density=True, color='#d9d9d6', label='SPY daily log returns')
xx = np.linspace(-0.07, 0.07, 600); f = EB['fits']
ax.plot(xx, stats.norm.pdf(xx, f['Gaussian']['params']['mu'], f['Gaussian']['params']['sigma']), color=AQUA, lw=1.2, label='Gaussian')
ax.plot(xx, stats.laplace.pdf(xx, f['Laplace']['params']['mu'], f['Laplace']['params']['b']), color=BLUE, lw=1.2, label='Laplace (Boltzmann core)')
ax.plot(xx, stats.t.pdf(xx, f['Student-t']['params']['nu'], f['Student-t']['params']['mu'], f['Student-t']['params']['s']), color=ORANGE, lw=1.2, label=r'Student-$t$, $\nu=%.1f$' % f['Student-t']['params']['nu'])
ax.set_yscale('log'); ax.set_ylim(0.05, 400); ax.set_xlabel('daily log return'); ax.set_ylabel('density (log scale)'); ax.legend(fontsize=7, loc='upper left'); ax.set_title('(b) Fitted densities', loc='left', fontsize=9)
plt.tight_layout(); plt.savefig(F + 'fig3_boltzmann.pdf'); plt.close()

# ---------------- Figure 4: narrative layer ------------------------------------------
con = sqlite3.connect('file:' + os.path.join(REPO, 'redhood.db') + '?mode=ro', uri=True); con.row_factory = sqlite3.Row
T = con.execute('select ticker from narrative_tickers').fetchall(); cnt = collections.Counter(t['ticker'] for t in T); freq = sorted(cnt.values(), reverse=True)
N = con.execute('select entropy_risk, conviction_size from narratives').fetchall()
fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8))
ax = axes[0]; ranks = np.arange(1, len(freq) + 1); ax.loglog(ranks, freq, 'o', color=BLUE, ms=3.5, label='ticker mentions (n=545, 202 tickers)')
xs = np.log(ranks); ys = np.log(freq); b, a = np.polyfit(xs, ys, 1); ax.loglog(ranks, np.exp(a + b * xs), color=ORANGE, lw=1.3, label='rank–frequency fit, slope %.2f' % b)
ax.set_xlabel('rank'); ax.set_ylabel('mentions'); ax.legend(fontsize=7.5, loc='lower left'); ax.set_title('(a) Redundancy: Zipf-like mention frequencies', loc='left', fontsize=9)
for t, rk, c in (('VIX', 1, 33), ('XLE, USO', 2, 24), ('LMT', 4, 22)): ax.annotate(t, (rk, c), xytext=(5, 1), textcoords='offset points', fontsize=7, color=INK2)
ax = axes[1]; by = collections.defaultdict(list)
for n in N:
    if n['entropy_risk'] is not None and n['conviction_size'] is not None: by[n['entropy_risk']].append(n['conviction_size'])
ks = sorted(by); means = [np.mean(by[k]) for k in ks]; passr = [np.mean([v == 0 for v in by[k]]) for k in ks]; ns = [len(by[k]) for k in ks]
w = 0.38; ax.bar(np.array(ks) - w / 2, means, width=w, color=BLUE, label='mean size multiplier after bear-case pass')
ax.bar(np.array(ks) + w / 2, passr, width=w, color=ORANGE, label='share rated "Pass" (0×)')
ax.set_xticks(ks); ax.set_xticklabels([f'{k}\n(n={n_})' for k, n_ in zip(ks, ns)], fontsize=7.5)
ax.set_xlabel('LLM entropy-risk score (1–10)'); ax.set_ylim(0, 0.78); ax.set_ylabel('fraction'); ax.legend(fontsize=7.5, loc='upper right'); ax.set_title(r'(b) Entropy score vs adversarial sizing ($\rho_s=-0.33$)', loc='left', fontsize=9)
plt.tight_layout(); plt.savefig(F + 'fig4_narratives.pdf'); plt.close()

# ---------------- Figure 5: ledger & heat --------------------------------------------
L = pd.read_csv(D + 'ledger.csv'); H = pd.read_csv(D + 'heat.csv', index_col=0, parse_dates=True)
hs = ['h5', 'h20', 'h60', 'todate']; hl = ['5d', '20d', '60d', 'to 22 Oct']
fig = plt.figure(figsize=(7.2, 5.4)); gs = fig.add_gridspec(2, 2, height_ratios=[1, 0.9], hspace=0.55, wspace=0.28)
def novelty_panel(ax, df, title):
    w = 0.38
    for i, (lab, sub, col) in enumerate([('first mention', df[df['first']], BLUE), ('repeat mention', df[~df['first']], ORANGE)]):
        vals = [100 * (sub[h] - sub[h + '_spy']).dropna().mean() for h in hs]
        ax.bar(np.arange(4) + (i - 0.5) * w, vals, width=w, color=col, label=f'{lab} (n={len(sub)})')
    ax.axhline(0, color=INK2, lw=0.8); ax.set_xticks(range(4)); ax.set_xticklabels(hl); ax.set_ylabel('mean excess return vs SPY (%)')
    ax.set_ylim(-14, 9); ax.legend(fontsize=7.5, loc='lower left'); ax.set_title(title, loc='left', fontsize=9)
novelty_panel(fig.add_subplot(gs[0, 0]), L, '(a) All long-side pairs')
novelty_panel(fig.add_subplot(gs[0, 1]), L[~L.cluster.isin(['defense', 'gold'])], '(b) Excluding defence and gold themes')
ax = fig.add_subplot(gs[1, :]); ax.fill_between(H.index, 0, 100 * H.heat, color=ORANGE, alpha=0.85, lw=0, label='heat: equity at risk at stops (%)')
ax.axhline(6, color=INK, ls='--', lw=0.9); ax.text(H.index[2], 6.4, 'illustrative heat capacity 6%', fontsize=7.5, color=INK)
ax.set_ylim(0, 22); ax.set_ylabel('% of $100k equity'); ax.set_title('(c) Portfolio heat implied by the narrative flow', loc='left', fontsize=9); ax.legend(fontsize=7.5, loc='upper right')
ax.text(H.heat.idxmax(), 100 * H.heat.max() + 0.5, '%d open positions' % int(H.open_positions.max()), fontsize=7.5, ha='center', color=INK2)
plt.savefig(F + 'fig5_ledger.pdf'); plt.close()
print('figures written to', F, os.listdir(F))
