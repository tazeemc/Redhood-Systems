"""Regime-detector diagnostics on the SPY daily series + Monte Carlo null calibration."""
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')   # paper/ ; the repository root is ROOT/..
REPO = os.path.join(ROOT, '..')
import sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # the DEPLOYED (v1) detector, archived here
from legacy_regime_detector_v1 import RegimeDetector, Regime

D = os.path.join(ROOT, 'data') + '/'
spy = pd.read_csv(D + 'SPY.csv', parse_dates=['date']).set_index('date')['close']
print('SPY rows', len(spy), spy.index.min().date(), spy.index.max().date())

# ---------- 1. Repo detector as implemented, rolling over the series -------------
det = RegimeDetector(base_temp=0.15, base_entropy=2.5, window=20)
recs = []
for i in range(21, len(spy) + 1):
    st = det.update(spy.iloc[:i])
    recs.append(dict(date=spy.index[i - 1], T=st.temperature, S=st.entropy, KL=st.kl_divergence,
                     mult=st.signal_multiplier, label=st.label.value, warn=st.warning))
R = pd.DataFrame(recs).set_index('date')
R.to_csv(D + 'regime_repo.csv')
print('\n[repo detector] n =', len(R))
print(' labels:', R.label.value_counts().to_dict())
print(' S: min %.3f max %.3f mean %.3f  (ln 10 = %.3f, base 2.5 unreachable)' % (R.S.min(), R.S.max(), R.S.mean(), math.log(10)))
print(' KL: min %.3f max %.3f mean %.3f; share > 0.25 alert = %.1f%%' % (R.KL.min(), R.KL.max(), R.KL.mean(), 100 * (R.KL > 0.25).mean()))
print(' T: min %.3f max %.3f median %.3f; share T>0.15 = %.1f%%' % (R['T'].min(), R['T'].max(), R['T'].median(), 100 * (R['T'] > 0.15).mean()))
print(' T quantiles:', R['T'].quantile([.1, .25, .5, .75, .9]).round(3).to_dict())
print(' mult: min %.2f max %.2f' % (R['mult'].min(), R['mult'].max()))
# 2026 only (the RedHood operating period)
R26 = R.loc['2026-02-22':]
print(' 2026-02-22 onward: n=%d labels=%s KL>0.25: %.1f%%  max S %.3f' % (len(R26), R26.label.value_counts().to_dict(), 100 * (R26.KL > 0.25).mean(), R26.S.max()))

# ---------- 2. Monte Carlo null for the plug-in estimators -------------------------
rng = np.random.default_rng(7)
def plug_entropy(x, bins):
    h, _ = np.histogram(x, bins=bins, density=True); p = h / (h.sum() + 1e-12); p = p[p > 0]
    return float(-(p * np.log(p)).sum())
def repo_kl(x, bins=15):
    T = x.std(ddof=1) * np.sqrt(252)
    h, e = np.histogram(x, bins=bins, density=True); c = (e[:-1] + e[1:]) / 2; emp = h / (h.sum() + 1e-12)
    sigma = T / np.sqrt(252); b = np.exp(-np.abs(c) / (sigma + 1e-12)); b /= b.sum() + 1e-12
    m = emp > 0; return float(np.sum(emp[m] * np.log(emp[m] / (b[m] + 1e-12))))
def kl_fixed(x, bins=15):
    """Same statistic but reference Laplace with the correct scale b = sigma/sqrt(2) and mass integrated over bins."""
    s = x.std(ddof=1); b = s / np.sqrt(2)
    h, e = np.histogram(x, bins=bins); emp = h / h.sum()
    cdf = lambda r: np.where(r < 0, 0.5 * np.exp(r / b), 1 - 0.5 * np.exp(-r / b))
    ref = cdf(e[1:]) - cdf(e[:-1]); ref /= ref.sum()
    m = emp > 0; return float(np.sum(emp[m] * np.log(emp[m] / ref[m])))

N = 20; sims = 20000
daily_sigma = 0.15 / np.sqrt(252)
lap = rng.laplace(0, daily_sigma / np.sqrt(2), size=(sims, N))
gau = rng.normal(0, daily_sigma, size=(sims, N))
t3 = rng.standard_t(3, size=(sims, N)) * daily_sigma / np.sqrt(3)  # var-matched t(3)
out = {}
for name, X in [('laplace', lap), ('gaussian', gau), ('t3', t3)]:
    S10 = np.array([plug_entropy(x, 10) for x in X]); KLr = np.array([repo_kl(x) for x in X]); KLf = np.array([kl_fixed(x) for x in X])
    out[name] = dict(S10_mean=S10.mean(), S10_p95=np.percentile(S10, 95), S10_max=S10.max(),
                     KLrepo_mean=KLr.mean(), KLrepo_p05=np.percentile(KLr, 5), KLrepo_share_gt025=(KLr > 0.25).mean(),
                     KLfix_mean=KLf.mean(), KLfix_p95=np.percentile(KLf, 95), KLfix_p99=np.percentile(KLf, 99))
    print(f'\n[MC null {name}, N=20] S(10 bins): mean {S10.mean():.3f} p95 {np.percentile(S10,95):.3f} max {S10.max():.3f} | '
          f'KL repo: mean {KLr.mean():.3f} p5 {np.percentile(KLr,5):.3f} share>0.25 {100*(KLr>0.25).mean():.1f}% | '
          f'KL fixed-scale: mean {KLf.mean():.3f} p95 {np.percentile(KLf,95):.3f} p99 {np.percentile(KLf,99):.3f}')
# Miller-Madow bias check for entropy: (k-1)/(2N)
print('\nMiller-Madow bias (k=10,N=20) = %.3f nats; (k=15,N=20) = %.3f' % (9 / 40, 14 / 40))
# Normalised entropy eta = S / ln k under Laplace null, N=20, k=10 (and k=sqrt(N)=4..5)
eta = np.array([plug_entropy(x, 10) for x in lap]) / math.log(10)
print('eta (k=10) under Laplace null: mean %.3f p5 %.3f p95 %.3f' % (eta.mean(), np.percentile(eta, 5), np.percentile(eta, 95)))
# Larger windows: N=60, 120 with k=sqrt(N)
for N2 in (60, 120, 250):
    k = int(math.sqrt(N2)); X = rng.laplace(0, daily_sigma / np.sqrt(2), size=(4000, N2))
    e2 = np.array([plug_entropy(x, k) for x in X]) / math.log(k); kf = np.array([kl_fixed(x, k) for x in X])
    print(f' N={N2}, k={k}: eta mean {e2.mean():.3f} [p5 {np.percentile(e2,5):.3f}, p95 {np.percentile(e2,95):.3f}] ; KL fixed p95 {np.percentile(kf,95):.3f}  bias (k-1)/2N={ (k-1)/(2*N2):.3f}')
# Power: t(3) alternative at N=120,k=10 vs calibrated threshold
N2, k = 120, 10
Xl = rng.laplace(0, daily_sigma / np.sqrt(2), size=(4000, N2)); Xt = rng.standard_t(3, size=(4000, N2)) * daily_sigma / np.sqrt(3)
thr = np.percentile([kl_fixed(x, k) for x in Xl], 95); power = np.mean([kl_fixed(x, k) > thr for x in Xt])
print(f' Calibrated KL threshold (N=120,k=10, Laplace null p95) = {thr:.3f}; power vs t(3) alternative = {100*power:.1f}%')
json.dump(out, open(D + 'mc_null.json', 'w'), indent=1)

# ---------- 3. Shipped v2 detector (repo/redhood_regime_detector.py) over SPY -----------
import importlib.util
spec = importlib.util.spec_from_file_location('rd2', os.path.join(REPO, 'redhood_regime_detector.py'))
rd2 = importlib.util.module_from_spec(spec); sys.modules['rd2'] = rd2; spec.loader.exec_module(rd2)
cal = rd2.calibrate(60, 0.15, sims=4000, seed=7, use_file=False)
print('\n[v2 detector calibration: 4000 Laplace windows, seed 7] S_hi=%.4f S_eq=%.4f D_hi=%.4f (bins=%d)' % (cal['S_hi'], cal['S_eq'], cal['D_hi'], cal['bins']))
cal20k = rd2.calibrate(60, 0.15, sims=20000, seed=7, use_file=False)
print('  20,000-window check: S_hi=%.4f D_hi=%.4f' % (cal20k['S_hi'], cal20k['D_hi']))
det2 = rd2.RegimeDetector(base_temp=0.15, calibration=cal)
V = []
for i in range(61, len(spy) + 1):
    st = det2.update(spy.iloc[:i])
    V.append(dict(date=spy.index[i - 1], T=st.temperature, S=st.entropy, eta=st.eta, S_eq=st.entropy_eq, D=st.kl_divergence, label=st.label.value, warn=st.warning, mult=st.signal_multiplier))
V = pd.DataFrame(V).set_index('date'); V.to_csv(D + 'regime_v2.csv')
print('  labels (n=%d): %s ; drift days %d (%.1f%%)' % (len(V), V.label.value_counts().to_dict(), V.warn.sum(), 100 * V.warn.mean()))
cr = V.index[V.label == 'CRISIS']; print('  CRISIS: %d days %s..%s contiguous=%s' % (len(cr), cr.min().date(), cr.max().date(), (np.diff(V.index.get_indexer(cr)) == 1).all()))
print('  deployed labels on v2-crisis days:', R.loc[cr.intersection(R.index), 'label'].value_counts().to_dict())
tr = V.index[V.label == 'TRANSITION']; print('  TRANSITION days:', [str(d.date()) for d in tr])
V26 = V.loc['2026-02-22':'2026-10-22']; print('  live period (22 Feb-22 Oct 2026):', V26.label.value_counts().to_dict(), '| drift %.1f%%' % (100 * V26.warn.mean()))
print('  corr(T, S_v2) = %.3f ; corr(T, D) = %.3f' % (np.corrcoef(V['T'], V.S)[0, 1], np.corrcoef(V['T'], V.D)[0, 1]))
print('  S_eq crosses S_hi at T/T_base = %.3f' % next(tau for tau in np.arange(1.0, 2.0, 0.001) if rd2.equilibrium_entropy(tau)[0] > cal['S_hi']))
# drift episodes
w = V.warn.values; eps = []; i = 0
while i < len(w):
    if w[i]:
        j = i
        while j + 1 < len(w) and w[j + 1]: j += 1
        eps.append((str(V.index[i].date()), str(V.index[j].date()))); i = j + 1
    else: i += 1
print('  drift episodes:', eps)
# power of the shipped configuration (N=60, k=7) at D_hi against variance-matched t(3) and Gaussian
rng2 = np.random.default_rng(21); ds = 0.15 / np.sqrt(252)
Xt = rng2.standard_t(3, size=(4000, 60)) * ds / np.sqrt(3); Xg = rng2.normal(0, ds, size=(4000, 60))
pt = np.mean([rd2.kl_departure(x, 60, cal['bins']) > cal['D_hi'] for x in Xt]); pg = np.mean([rd2.kl_departure(x, 60, cal['bins']) > cal['D_hi'] for x in Xg])
print('  power at N=60,k=7: t(3) %.1f%%, Gaussian %.1f%%' % (100 * pt, 100 * pg))
json.dump(dict(repo_labels=R.label.value_counts().to_dict(), repo_S_max=float(R.S.max()), repo_S_min=float(R.S.min()), repo_KL_alert_share=float((R.KL > 0.25).mean()),
               repo_T_quantiles=R['T'].quantile([.1, .25, .5, .75, .9]).round(4).to_dict(), repo_T_gt_base=float((R['T'] > 0.15).mean()),
               v2=dict(cal=cal, cal20k=cal20k, labels=V.label.value_counts().to_dict(), n=int(len(V)), drift_share=float(V.warn.mean()), crisis_n=int(len(cr)),
                       crisis_first=str(cr.min().date()), crisis_last=str(cr.max().date()), deployed_on_crisis=R.loc[cr.intersection(R.index), 'label'].value_counts().to_dict(),
                       transition_days=[str(d.date()) for d in tr], live=V26.label.value_counts().to_dict(), live_drift=float(V26.warn.mean()),
                       corrTS=float(np.corrcoef(V['T'], V.S)[0, 1]), corrTD=float(np.corrcoef(V['T'], V.D)[0, 1]), drift_episodes=eps, power_t3=float(pt), power_gauss=float(pg))),
          open(D + 'regime_summary.json', 'w'), indent=1)
