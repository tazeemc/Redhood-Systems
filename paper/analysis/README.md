# Paper: Interpreting Black Swans & Boltzmann with a Thermodynamic Bias (v3)

Reproduce the figures and tables from the repository root:

```bash
pip install numpy pandas scipy matplotlib
cd paper/analysis
python regime_analysis.py      # deployed detector vs corrected estimators on SPY; Monte Carlo calibration
python entropy_boltzmann.py    # fixed-lattice entropy, Boltzmann occupation test, density fits
python pnl_analysis.py         # long-side ledger, novelty/cluster breakdowns, portfolio heat
python figures.py              # figures/*.pdf
python make_tables.py          # table_ledger.tex
cd .. && pdflatex main && pdflatex main && pdflatex main
```

Inputs: `../redhood.db` (system records), `data/SPY.csv` and `data/prices.json` (Yahoo Finance daily closes retrieved 23 Oct 2026).
Scripts expect to run with the repository's `redhood_grader.py` and `redhood_regime_detector.py` importable from the repo root.
