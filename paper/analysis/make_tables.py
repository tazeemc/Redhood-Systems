"""Build the LaTeX ledger table directly from data/ledger.csv so no number is transcribed by hand."""
import os, math
import pandas as pd
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
L = pd.read_csv(os.path.join(ROOT, 'data', 'ledger.csv'))
def row(df, lab):
    cells = [lab]
    for h in ('h5', 'h20', 'h60', 'todate'):
        xs = (df[h] - df[h + '_spy']).dropna()
        bydate = df.dropna(subset=[h]).assign(ex=lambda d: d[h] - d[h + '_spy']).groupby('run_at').ex.mean()
        t = bydate.mean() / (bydate.std(ddof=1) / math.sqrt(len(bydate))) if len(bydate) > 2 and bydate.std(ddof=1) > 0 else float('nan')
        ts = '--' if math.isnan(t) else f'{t:+.1f}'
        cells.append(f"{100*xs.mean():+.1f} / {100*(xs>0).mean():.0f} / {ts}" if len(xs) else '--')
    cells.append(f"{len(df)} ({df.h60.notna().sum()})")
    return ' & '.join(cells) + ' \\\\'
X = L[~L.cluster.isin(['defense', 'gold'])]
groups = [('All long-side pairs', L), ('\\quad first mention of ticker', L[L['first']]), ('\\quad repeat mention', L[~L['first']]), ('\\quad 4th or later mention', L[L.prior_mentions >= 3]),
          ('\\quad first mention, excl.\\ defence \\& gold', X[X['first']]), ('\\quad repeat mention, excl.\\ defence \\& gold', X[~X['first']]),
          ('Entropy band low (3)', L[L.band == 'low']), ('Entropy band mid (4--7)', L[L.band == 'mid']), ('Entropy band high (8--9)', L[L.band == 'high']),
          ('Bear-case verdict: Pass ($0\\times$)', L[L.conviction == 0.0]), ('Bear-case verdict: Quarter', L[L.conviction == 0.25]), ('Bear-case verdict: Half', L[L.conviction == 0.5]), ('No bear-case pass recorded', L[L.conviction.isna()]),
          ('Regime at run (v2): Trending', L[L.regime_v2 == 'TRENDING']), ('Regime at run (v2): Choppy', L[L.regime_v2 == 'CHOPPY']),
          ('Theme: defence', L[L.cluster == 'defense']), ('Theme: energy', L[L.cluster == 'energy']), ('Theme: gold', L[L.cluster == 'gold']), ('Theme: semiconductors/AI', L[L.cluster == 'semis_ai']), ('Theme: other', L[L.cluster == 'other']),
          ('Entered February 2026', L[L.month == '2026-02']), ('Entered March 2026', L[L.month == '2026-03']), ('Entered April--June 2026', L[L.month.isin(['2026-04', '2026-05', '2026-06'])]),
          ('Entered July--October 2026', L[L.month >= '2026-07'])]
tex = ['\\begin{tabular}{lccccr}', '\\toprule', 'Subset & 5 days & 20 days & 60 days & To 22 Oct 2026 & $n$ (60d) \\\\', '\\midrule'] + [row(d, l) for l, d in groups] + ['\\bottomrule', '\\end{tabular}']
open(os.path.join(ROOT, 'table_ledger.tex'), 'w').write('\n'.join(tex) + '\n')
print('\n'.join(tex))
