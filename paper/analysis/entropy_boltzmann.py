"""Standardised-bin (fixed energy level) entropy, Boltzmann occupation test, and fat-tail density fits on SPY."""
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')   # paper/ ; the repository root is ROOT/..
REPO = os.path.join(ROOT, '..')
import json, math
import numpy as np, pandas as pd
from scipy import stats, optimize, integrate

D = os.path.join(ROOT, 'data') + '/'
spy = pd.read_csv(D + 'SPY.csv', parse_dates=['date']).set_index('date')['close']
r = np.log(spy / spy.shift(1)).dropna()
print('returns n=%d mean %.5f sd %.5f skew %.2f exkurt %.2f' % (len(r), r.mean(), r.std(), stats.skew(r), stats.kurtosis(r)))

# ---------- A. Standardised-bin entropy -------------------------------------------
EDGES_Z = np.array([-np.inf, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, np.inf])   # k = 10 fixed levels
K = len(EDGES_Z) - 1
def std_entropy(x, sigma_ref, mm=True):
    z = x / sigma_ref
    h, _ = np.histogram(z, bins=EDGES_Z); n = h.sum(); p = h / n; p = p[p > 0]
    S = -(p * np.log(p)).sum() + ((K - 1) / (2 * n) if mm else 0.0)
    return S, min(S / math.log(K), 1.0)
def laplace_level_entropy(sigma_ratio):
    """Entropy of the fixed levels when returns are Laplace with sd = sigma_ratio * sigma_ref (the 'equilibrium' occupation)."""
    b = sigma_ratio / np.sqrt(2)
    cdf = lambda z: np.where(z < 0, 0.5 * np.exp(z / b), 1 - 0.5 * np.exp(-z / b))
    p = cdf(EDGES_Z[1:]) - cdf(EDGES_Z[:-1]); p = p[p > 0]
    return float(-(p * np.log(p)).sum())
W = 60
T_BASE = 0.15
sigma_ref = pd.Series(T_BASE / np.sqrt(252), index=r.index)   # fixed lattice scale = base temperature
rows = []
for i in range(W, len(r) + 1):
    x = r.iloc[i - W:i].values; sref = sigma_ref.iloc[i - 1]
    if np.isnan(sref): continue
    T = x.std(ddof=1) * np.sqrt(252)
    S, eta = std_entropy(x, sref)
    rows.append(dict(date=r.index[i - 1], T=T, S=S, eta=eta, sref_ann=sref * np.sqrt(252)))
E = pd.DataFrame(rows).set_index('date')
print('\n[standardised-bin entropy, W=60, k=10 levels in units of trailing-250d sigma] n=%d' % len(E))
print(' S range %.3f-%.3f (ln10=%.3f); eta range %.3f-%.3f' % (E.S.min(), E.S.max(), math.log(K), E.eta.min(), E.eta.max()))
print(' corr(T, S_std) = %.3f   (vs negative under range-adaptive bins)' % np.corrcoef(E['T'], E.S)[0, 1])
print(' equilibrium S for T/Tref = 1: %.3f ; = 0.75: %.3f ; = 1.5: %.3f ; = 2: %.3f' % tuple(laplace_level_entropy(q) for q in (1, .75, 1.5, 2)))
# Regime classification with thresholds: T_base = trailing sref (i.e. T/Tref) and S relative to equilibrium at T/Tref=1 (plus MC band)
rng = np.random.default_rng(11)
null = np.array([std_entropy(rng.laplace(0, 1 / np.sqrt(2), W), 1.0)[0] for _ in range(6000)])
S_hi = float(np.percentile(null, 95)); S_eq = float(null.mean())
print(' null (Laplace, T=Tref, W=60): S mean %.3f p5 %.3f p95 %.3f -> S_hi = %.3f' % (null.mean(), np.percentile(null, 5), S_hi, S_hi))
E['Tratio'] = E['T'] / E['sref_ann']
E['label'] = np.select([(E.Tratio <= 1.0) & (E.S <= S_hi), (E.Tratio > 1.0) & (E.S <= S_hi), (E.Tratio > 1.0) & (E.S > S_hi)],
                       ['TRENDING', 'CHOPPY', 'CRISIS'], default='TRANSITION')
print(' labels:', E.label.value_counts().to_dict())
print(' 2026-02-22 onward:', E.loc['2026-02-22':].label.value_counts().to_dict())
cr = E.index[E.label == 'CRISIS']; print(' CRISIS dates:', [str(d.date()) for d in cr][:40])
pd.set_option('display.width', 200)
print(E.loc['2025-03-28':'2025-05-15'].iloc[::2].round(3).to_string())
print(E.loc['2026-05-25':'2026-06-30'].iloc[::2].round(3).to_string())
E.to_csv(D + 'regime_stdbins.csv')

# ---------- B. Boltzmann occupation test on fixed energy levels --------------------
# levels: z = r/sigma_ref (full-sample sigma); energy E = z^2/2 (harmonic) ; occupation p_i / width_i vs E
sig = r.std(); z = (r / sig).values
edges = np.concatenate([[-12.0, -6.0], np.arange(-4.0, 4.01, 0.5), [6.0, 12.0]])   # full range: wide outer bins hold the April 2025 days
h, _ = np.histogram(z, bins=edges); c = (edges[:-1] + edges[1:]) / 2; width = np.diff(edges)
assert h.sum() == len(z), (h.sum(), len(z))
p = h / (h.sum() * width); m = h > 0
Ez = c ** 2 / 2
slope, intercept, rv, pv, se = stats.linregress(Ez[m & (np.abs(c) <= 2)], np.log(p[m & (np.abs(c) <= 2)]))
T_eff_core = -1 / slope
slope2, intercept2, rv2, _, _ = stats.linregress(Ez[m], np.log(p[m]))
print('\n[Boltzmann occupation] fit ln p = a - E/T_eff on |z|<=2: T_eff = %.3f (Gaussian => 1.0), R2 = %.3f' % (T_eff_core, rv ** 2))
tail_m = m & (np.abs(c) >= 2.5)
print('  full range: T_eff = %.3f, R2 = %.3f ; tail bins |z|>=2.5 (centre, count, observed/Boltzmann): %s' % (-1 / slope2, rv2 ** 2,
      [(float(cc), int(hh), round(float(pp / np.exp(intercept - ee / T_eff_core)), 1)) for cc, hh, pp, ee in zip(c[tail_m], h[tail_m], p[tail_m], Ez[tail_m])]))
print('  observations beyond |z|=4: %d (z = %s)' % ((np.abs(z) > 4).sum(), np.round(np.sort(z[np.abs(z) > 4]), 1).tolist()))
occ = pd.DataFrame(dict(z=c, E=Ez, count=h, density=p)); occ.to_csv(D + 'occupation.csv', index=False)
# Laplace energy: E = |z| ; fit on |z|<=2
slopeL, intL, rL, _, _ = stats.linregress(np.abs(c[m & (np.abs(c) <= 2)]), np.log(p[m & (np.abs(c) <= 2)]))
print('  linear-energy (Laplace) fit ln p = a - |z|/theta on |z|<=2: theta = %.3f, R2 = %.3f' % (-1 / slopeL, rL ** 2))

# ---------- C. Density fits: Gaussian, Laplace, Student-t, Boltzmann-Pareto ---------
x = r.values
fits = {}
mu, sd = stats.norm.fit(x); ll = stats.norm.logpdf(x, mu, sd).sum(); fits['Gaussian'] = (ll, 2, dict(mu=mu, sigma=sd))
loc, b = stats.laplace.fit(x); ll = stats.laplace.logpdf(x, loc, b).sum(); fits['Laplace'] = (ll, 2, dict(mu=loc, b=b))
nu, loc, s = stats.t.fit(x); ll = stats.t.logpdf(x, nu, loc, s).sum(); fits['Student-t'] = (ll, 3, dict(nu=nu, mu=loc, s=s))
def lp_logpdf(x, mu, sigma, r0, alpha):
    """Laplace core for |u|<=r0, Pareto tail (r0/|u|)^(1+alpha) beyond, continuous at r0, normalised in closed form.
    Z = 2 * [ sigma (1 - e^{-r0/sigma}) + e^{-r0/sigma} r0 / alpha ]."""
    u = np.abs(x - mu)
    core = -u / sigma
    tail = -r0 / sigma - (1 + alpha) * np.log(u / r0)
    Z = 2 * (sigma * (1 - np.exp(-r0 / sigma)) + np.exp(-r0 / sigma) * r0 / alpha)
    return np.where(u <= r0, core, tail) - np.log(Z)
def lp_nll(th):
    mu, ls, lr0, la = th; sigma, r0, alpha = np.exp(ls), np.exp(lr0), np.exp(la)
    if not (1e-4 < sigma < 0.2 and 1e-4 < r0 < 0.2 and 0.2 < alpha < 20): return 1e9
    return -lp_logpdf(x, mu, sigma, r0, alpha).sum()
best = None
for s0 in (0.005, 0.008, 0.012):
    for r00 in (0.01, 0.02, 0.03):
        for a0 in (2.0, 3.0, 5.0):
            res = optimize.minimize(lp_nll, [x.mean(), np.log(s0), np.log(r00), np.log(a0)], method='Nelder-Mead', options=dict(maxiter=6000, xatol=1e-8, fatol=1e-8))
            if best is None or res.fun < best.fun: best = res
mu, sigma, r0, alpha = best.x[0], np.exp(best.x[1]), np.exp(best.x[2]), np.exp(best.x[3])
fits['Laplace core + Pareto tail'] = (-best.fun, 4, dict(mu=mu, sigma=sigma, r0=r0, alpha=alpha, r0_in_sd=r0 / x.std()))
# the tempered form of Version 2 (exponential x power), for the record: it is exponentially tailed
def bp_logpdf(x, mu, sigma, r0, alpha):
    f = lambda u: np.exp(-np.abs(u) / sigma) * (1 + np.abs(u) / r0) ** (-alpha)
    Z, _ = integrate.quad(f, -np.inf, np.inf, limit=200)
    return -np.abs(x - mu) / sigma - alpha * np.log1p(np.abs(x - mu) / r0) - np.log(Z)
def bp_nll(th):
    mu, ls, lr0, la = th; sigma, r0, alpha = np.exp(ls), np.exp(lr0), np.exp(la)
    if sigma > 1 or r0 > 1: return 1e9
    return -bp_logpdf(x, mu, sigma, r0, alpha).sum()
bestb = None
for s0 in (0.006, 0.01, 0.02):
    for r00 in (0.003, 0.01):
        for a0 in (0.5, 2.0):
            res = optimize.minimize(bp_nll, [x.mean(), np.log(s0), np.log(r00), np.log(a0)], method='Nelder-Mead', options=dict(maxiter=4000, xatol=1e-7, fatol=1e-7))
            if bestb is None or res.fun < bestb.fun: bestb = res
fits['Tempered (V2 form)'] = (-bestb.fun, 4, dict(mu=bestb.x[0], sigma=np.exp(bestb.x[1]), r0=np.exp(bestb.x[2]), alpha=np.exp(bestb.x[3])))
print('\n[density fits on %d daily log returns]' % len(x))
for k, (ll, npar, par) in fits.items():
    print(f'  {k:18s} logL={ll:9.2f}  AIC={2*npar-2*ll:9.2f}  params={ {a: round(float(v),5) for a,v in par.items()} }')
# KS distances
ks = {}
ks['Gaussian'] = stats.kstest(x, stats.norm(fits['Gaussian'][2]['mu'], fits['Gaussian'][2]['sigma']).cdf).statistic
ks['Laplace'] = stats.kstest(x, stats.laplace(fits['Laplace'][2]['mu'], fits['Laplace'][2]['b']).cdf).statistic
ks['Student-t'] = stats.kstest(x, stats.t(fits['Student-t'][2]['nu'], fits['Student-t'][2]['mu'], fits['Student-t'][2]['s']).cdf).statistic
# Hill tail-index estimator on |r| (top 10%)
a = np.sort(np.abs(x - x.mean()))[::-1]; kk = int(0.10 * len(a)); hill = kk / np.sum(np.log(a[:kk] / a[kk]))
kk2 = int(0.05 * len(a)); hill2 = kk2 / np.sum(np.log(a[:kk2] / a[kk2]))
print('  Hill tail index alpha: top10%% = %.2f (k=%d), top5%% = %.2f (k=%d)' % (hill, kk, hill2, kk2))
print('  KS distances:', {k: round(float(v), 4) for k, v in ks.items()})
# tail exceedance comparison: P(|r|>3 sd)
thr = 3 * sd
emp = np.mean(np.abs(x - x.mean()) > thr)
print('  P(|r-mu|>3sd): empirical %.4f, Gaussian %.4f, Laplace %.4f, t %.4f' % (emp, 2 * stats.norm.sf(3), 2 * stats.laplace.sf(thr, 0, fits['Laplace'][2]['b']), 2 * stats.t.sf(thr / fits['Student-t'][2]['s'], fits['Student-t'][2]['nu'])))
# ---------- D. Exact discrete power-law MLE for ticker mention counts (x_min = 2 and 3) -----------
import sqlite3, collections
con = sqlite3.connect('file:' + os.path.join(REPO, 'redhood.db') + '?mode=ro', uri=True)
cnt = collections.Counter(t for (t,) in con.execute('select ticker from narrative_tickers'))
freq = np.array(sorted(cnt.values(), reverse=True))
from scipy.special import zeta
def discrete_mle(data, xmin):
    d = data[data >= xmin]; n = len(d); logs = np.log(d).sum()
    nll = lambda a: n * np.log(zeta(a, xmin)) + a * logs
    r = optimize.minimize_scalar(nll, bounds=(1.01, 6), method='bounded'); a = r.x
    # standard error from the observed information (numerical second derivative)
    h = 1e-3; se = 1 / np.sqrt((nll(a + h) - 2 * nll(a) + nll(a - h)) / h ** 2)
    return float(a), float(se), int(n)
pl = {xm: discrete_mle(freq, xm) for xm in (1, 2, 3)}
print('\n[ticker mention counts] exact discrete power-law MLE:', {k: (round(v[0], 2), round(v[1], 2), v[2]) for k, v in pl.items()})
json.dump(dict(powerlaw_mle={str(k): dict(alpha=v[0], se=v[1], n=v[2]) for k, v in pl.items()}, std_entropy=dict(corrTS=float(np.corrcoef(E['T'], E.S)[0, 1]), S_hi=S_hi, S_eq=S_eq, labels=E.label.value_counts().to_dict(), labels_2026=E.loc['2026-02-22':].label.value_counts().to_dict(), crisis_dates=[str(d.date()) for d in cr]),
               boltzmann=dict(T_eff_core=float(T_eff_core), R2_core=float(rv ** 2), T_eff_full=float(-1 / slope2), R2_full=float(rv2 ** 2), theta_laplace=float(-1 / slopeL), R2_laplace=float(rL ** 2)),
               fits={k: dict(logL=float(v[0]), npar=v[1], AIC=float(2 * v[1] - 2 * v[0]), params={a: float(b) for a, b in v[2].items()}) for k, v in fits.items()},
               ks={k: float(v) for k, v in ks.items()}, tail=dict(empirical=float(emp), hill10=float(hill), hill5=float(hill2)), moments=dict(n=int(len(r)), mean=float(r.mean()), sd=float(r.std()), skew=float(stats.skew(r)), exkurt=float(stats.kurtosis(r)))),
          open(D + 'entropy_boltzmann_summary.json', 'w'), indent=1)
