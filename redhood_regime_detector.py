"""
redhood_regime_detector.py
RedHood Systems — Thermodynamic Regime Detection, v2
Author: Tazeem Chowdhury / Redhood Capital

Implements the corrected estimators of the paper
"Interpreting Black Swans & Boltzmann with a Thermodynamic Bias" (v3, Oct 2026):

* Temperature  T  — annualised realised volatility (decimal; 0.15 == 15%).
* Occupation entropy  S  — Shannon entropy of FIXED return levels measured in
  units of the base temperature (not range-adaptive histogram bins), with the
  Miller–Madow small-sample correction; eta = S / ln(k) is the disorder ratio.
  Every temperature has an equilibrium entropy S_eq(T / T_base) under a Laplace
  (Boltzmann) law, so "high entropy" means "above the equilibrium band".
* Departure  D  — KL divergence of the observed occupation from the Boltzmann
  occupation at the *current* temperature (bin-integrated Laplace reference,
  scale b = sigma / sqrt(2)).  The alert threshold is the 95th percentile of D
  under the Laplace null, obtained by Monte Carlo — not a fixed constant.
* Regime  = temperature x disorder, with two complementary disorder diagnostics:
      CRISIS      hot  and S above the band that is normal at T_base (occupation has spread)
      CHOPPY      hot  but S within band (a short volatility spike)
      TRANSITION  cool but D above its null quantile (occupation shape drifting)
      TRENDING    cool, equilibrium
* Heat — portfolio heat is an *input* (see redhood_pnl.current_heat); the
  multiplier carries the factor (1 - heat / heat_max).

Why v1 was replaced (all four are documented in the paper, Section 4):
  - v1's base_entropy = 2.5 nats exceeded ln(10) = 2.30, the ceiling for ten
    bins, so CRISIS / TRANSITION were unreachable and the entropy factor was
    identically 1.
  - v1's range-adaptive bins made entropy *fall* in crashes (one tail day
    stretches the bin width); corr(T, S) was -0.51 on SPY 2024-26.
  - v1's KL alert (0.25) sat below the plug-in estimator's own bias with
    k=15 bins on N=20 returns (~0.35), so it fired on every live report.
  - v1 never received a heat value; "heat budget 100%" was a constant.

Backward compatibility: the v1 constructor keywords (base_entropy, max_heat,
kl_alert) are accepted and ignored/mapped, and RegimeState keeps the v1 fields.

Usage:
    from redhood_regime_detector import RegimeDetector, SignalGate

    detector = RegimeDetector(base_temp=0.15)
    detector.set_current_heat(0.021)          # from redhood_pnl.current_heat()
    state = detector.update(prices)           # pd.Series / array of closes (>= 61 preferred)
    print(state.label, state.temperature, state.eta, state.kl_divergence, state.warning)

    gate = SignalGate(detector)
    sized = gate.process(raw_signals)
"""

from __future__ import annotations

import json
import math
import os
import warnings
from dataclasses import dataclass, asdict
from enum import Enum

import numpy as np

try:  # pandas is optional: update() accepts any 1-D sequence of closes
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


DETECTOR_VERSION = "v2"
T_BASE_DEFAULT = 0.15                                   # annualised, decimal
# Fixed energy levels in units of the daily base scale sigma_b = T_base / sqrt(252)
LEVEL_EDGES = np.array([-np.inf, -3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0, np.inf])
N_LEVELS = len(LEVEL_EDGES) - 1
CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'data', 'regime_calibration.json')


# ---------------------------------------------------------------------------
# Regime taxonomy
# ---------------------------------------------------------------------------

class Regime(Enum):
    TRENDING    = "TRENDING"      # cool, equilibrium       -> amplify signals
    CHOPPY      = "CHOPPY"        # hot,  equilibrium       -> reduce size
    CRISIS      = "CRISIS"        # hot,  non-equilibrium   -> halt new entries
    TRANSITION  = "TRANSITION"    # cool, non-equilibrium   -> neutral, watch closely


REGIME_DESCRIPTIONS = {
    "TRENDING":   "Low T, equilibrium occupation",
    "CHOPPY":     "High T, occupation within the base band",
    "CRISIS":     "High T, occupation spread beyond the base band",
    "TRANSITION": "Low T, occupation shape drifting from Boltzmann",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    label:             Regime
    temperature:       float   # annualised vol, decimal (market "T")
    entropy:           float   # occupation entropy S (nats), Miller–Madow corrected
    heat_budget:       float   # fraction of heat capacity remaining [0, 1]
    kl_divergence:     float   # D = KL(observed occupation || Boltzmann at current T)
    signal_multiplier: float   # size scalar to apply to incoming signals
    warning:           bool    # True when D exceeds its calibrated threshold (drift)
    # --- v2 additions -------------------------------------------------------
    eta:               float = 0.0   # S / ln(k)  in [0, 1]
    entropy_eq:        float = 0.0   # equilibrium S at the current T / T_base
    eta_eq:            float = 0.0   # equilibrium eta
    entropy_hi:        float = 0.0   # 95th percentile of S under the null at T_base
    kl_threshold:      float = 0.0   # 95th percentile of D under the Laplace null
    heat:              float = 0.0   # portfolio heat supplied via set_current_heat()
    heat_max:          float = 0.06
    base_temp:         float = T_BASE_DEFAULT
    window:            int = 20
    shape_window:      int = 60
    n_returns:         int = 0
    as_of:             str = ""      # last date in the price series, if available
    detector_version:  str = DETECTOR_VERSION

    @property
    def hot(self) -> bool:
        return self.temperature > self.base_temp

    @property
    def drift(self) -> bool:
        return self.warning

    @property
    def description(self) -> str:
        return REGIME_DESCRIPTIONS[self.label.value]

    def to_dict(self) -> dict:
        d = asdict(self)
        d['label'] = self.label.value
        return d


@dataclass
class Signal:
    source:     str            # e.g. "substack:xyz", "twitter:@abc"
    ticker:     str
    direction:  int            # +1 long, -1 short
    raw_score:  float          # original conviction score [0, 1]
    sized_score: float = 0.0   # after regime adjustment


# ---------------------------------------------------------------------------
# Estimators (pure functions, unit-tested)
# ---------------------------------------------------------------------------

def log_returns(prices) -> np.ndarray:
    """Daily log returns from a sequence of closes (NaNs dropped)."""
    p = np.asarray(prices, dtype=float)
    p = p[~np.isnan(p)]
    if len(p) < 2:
        return np.array([], dtype=float)
    return np.diff(np.log(p))


def temperature(returns: np.ndarray, window: int = 20) -> float:
    """Annualised realised volatility of the last `window` returns (decimal)."""
    r = np.asarray(returns, dtype=float)[-window:]
    if len(r) < 2:
        return float('nan')
    return float(r.std(ddof=1) * math.sqrt(252))


def occupation_entropy(returns: np.ndarray, window: int = 60,
                       base_temp: float = T_BASE_DEFAULT) -> tuple[float, float]:
    """Entropy of the fixed levels (units of T_base), Miller–Madow corrected.

    Returns (S, eta) with S in nats and eta = S / ln(k) in [0, 1].
    """
    r = np.asarray(returns, dtype=float)[-window:]
    n = len(r)
    if n == 0:
        return float('nan'), float('nan')
    z = r / (base_temp / math.sqrt(252))
    h, _ = np.histogram(z, bins=LEVEL_EDGES)
    p = h / h.sum()
    p = p[p > 0]
    s = float(-(p * np.log(p)).sum() + (N_LEVELS - 1) / (2 * n))
    s = min(s, math.log(N_LEVELS))
    return s, s / math.log(N_LEVELS)


def _laplace_cdf(u, b):
    u = np.asarray(u, dtype=float)
    return np.where(u < 0, 0.5 * np.exp(u / b), 1.0 - 0.5 * np.exp(-u / b))


def equilibrium_entropy(temp_ratio: float) -> tuple[float, float]:
    """Entropy of the fixed levels when returns are Laplace with sd = temp_ratio * sigma_b.

    This is the Boltzmann occupation at temperature T = temp_ratio * T_base.
    Returns (S_eq, eta_eq).
    """
    tr = max(float(temp_ratio), 1e-6)
    b = tr / math.sqrt(2)
    cdf = _laplace_cdf(LEVEL_EDGES, b)
    p = np.diff(cdf)
    p = p[p > 0]
    s = float(-(p * np.log(p)).sum())
    return s, s / math.log(N_LEVELS)


def kl_departure(returns: np.ndarray, window: int = 60, bins: int | None = None) -> float:
    """KL(observed occupation || Laplace at the current scale), bin-integrated reference.

    The Laplace scale is sigma / sqrt(2) (v1 used sigma itself, which overstates
    the scale by 41%).  The reference mass is integrated over each bin rather
    than sampled at bin centres.
    """
    x = np.asarray(returns, dtype=float)[-window:]
    n = len(x)
    if n < 8:
        return float('nan')
    k = bins or max(4, int(math.sqrt(n)))
    sd = x.std(ddof=1)
    if sd <= 0:
        return 0.0
    b = sd / math.sqrt(2)
    h, edges = np.histogram(x, bins=k)
    emp = h / h.sum()
    ref = _laplace_cdf(edges[1:], b) - _laplace_cdf(edges[:-1], b)
    ref = ref / ref.sum()
    m = emp > 0
    return float(np.sum(emp[m] * np.log(emp[m] / np.maximum(ref[m], 1e-12))))


# ---------------------------------------------------------------------------
# Calibration — null quantiles by Monte Carlo (cached per (window, bins))
# ---------------------------------------------------------------------------

_CALIBRATION_CACHE: dict[tuple, dict] = {}


def calibrate(shape_window: int = 60, base_temp: float = T_BASE_DEFAULT,
              sims: int = 4000, quantile: float = 0.95, seed: int = 7,
              use_file: bool = True) -> dict:
    """Quantiles of S and D under a Laplace null at T_base.

    Returns {'S_hi', 'S_eq', 'D_hi', 'shape_window', 'bins', 'sims', 'quantile'}.
    Results are cached in memory and (optionally) in data/regime_calibration.json
    so a scheduled run does not pay for the simulation each time.
    """
    bins = max(4, int(math.sqrt(shape_window)))
    key = (shape_window, bins, round(base_temp, 6), sims, quantile, seed)
    if key in _CALIBRATION_CACHE:
        return _CALIBRATION_CACHE[key]
    skey = "|".join(str(k) for k in key)
    if use_file and os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, encoding='utf-8') as fh:
                stored = json.load(fh)
            if skey in stored:
                _CALIBRATION_CACHE[key] = stored[skey]
                return stored[skey]
        except (OSError, ValueError):
            pass
    rng = np.random.default_rng(seed)
    b = base_temp / math.sqrt(252) / math.sqrt(2)
    sample = rng.laplace(0.0, b, size=(sims, shape_window))
    s_vals = np.array([occupation_entropy(x, shape_window, base_temp)[0] for x in sample])
    d_vals = np.array([kl_departure(x, shape_window, bins) for x in sample])
    cal = dict(S_hi=float(np.quantile(s_vals, quantile)), S_eq=float(s_vals.mean()),
               D_hi=float(np.quantile(d_vals, quantile)), D_mean=float(d_vals.mean()),
               shape_window=shape_window, bins=bins, sims=sims, quantile=quantile, seed=seed,
               base_temp=base_temp)
    _CALIBRATION_CACHE[key] = cal
    if use_file:
        try:
            os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
            stored = {}
            if os.path.exists(CALIBRATION_FILE):
                with open(CALIBRATION_FILE, encoding='utf-8') as fh:
                    stored = json.load(fh)
            stored[skey] = cal
            with open(CALIBRATION_FILE, 'w', encoding='utf-8') as fh:
                json.dump(stored, fh, indent=1)
        except (OSError, ValueError):
            pass
    return cal


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------

class RegimeDetector:
    """
    Computes market temperature, occupation entropy, KL departure, and
    classifies the current regime. Call update() on each new price series.
    """

    def __init__(
        self,
        base_temp:      float = T_BASE_DEFAULT,   # annualised vol at "normal" conditions (decimal)
        window:         int   = 20,               # rolling window for temperature
        shape_window:   int   = 60,               # window for entropy / KL (shape statistics)
        heat_max:       float = 0.06,             # heat capacity: fraction of equity at risk at stops
        temp_cap:       float = 2.5,              # cap on (T_base / T)^2
        entropy_lambda: float = 0.5,              # entropy factor scale: exp(-(eta - eta_eq) / lambda)
        calibration_sims: int = 4000,
        calibration:    dict | None = None,       # pre-computed calibrate() dict
        # --- v1 keywords, accepted for backward compatibility ---------------
        base_entropy:   float | None = None,
        kl_alert:       float | None = None,
        max_heat:       float | None = None,
    ):
        if base_temp > 1.5:
            # Someone passed a percentage (e.g. 15 or 25). The v1 PowerShell port
            # did exactly this and pinned every position at its cap.
            warnings.warn(f"base_temp={base_temp} looks like a percentage; using {base_temp / 100:.4f}",
                          stacklevel=2)
            base_temp = base_temp / 100.0
        if base_entropy is not None:
            warnings.warn("base_entropy is ignored in v2: entropy thresholds are calibrated "
                          "from the Laplace null (see calibrate()).", DeprecationWarning, stacklevel=2)
        if kl_alert is not None:
            warnings.warn("kl_alert is ignored in v2: the KL threshold is the calibrated "
                          "95th-percentile null quantile.", DeprecationWarning, stacklevel=2)
        if max_heat is not None:
            # v1 heat was "normalised units" with max 1.0; v2 heat is a fraction of equity.
            heat_max = float(max_heat) if max_heat <= 1.0 else heat_max

        self.base_temp      = float(base_temp)
        self.window         = int(window)
        self.shape_window   = int(shape_window)
        self.heat_max       = float(heat_max)
        self.temp_cap       = float(temp_cap)
        self.entropy_lambda = float(entropy_lambda)
        self._calibration   = calibration or calibrate(self.shape_window, self.base_temp,
                                                       sims=calibration_sims)
        self._returns:      np.ndarray = np.array([], dtype=float)
        self._current_heat: float = 0.0
        self._state:        RegimeState | None = None
        self._as_of:        str = ""

    # v1 attribute names used by callers / reports
    @property
    def max_heat(self) -> float:
        return self.heat_max

    @property
    def calibration(self) -> dict:
        return dict(self._calibration)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, prices) -> RegimeState:
        """
        Ingest latest price series and recompute regime state.
        prices: pd.Series / list / array of close prices (>= window+1; shape
                statistics use the last `shape_window` returns).
        """
        if pd is not None and isinstance(prices, pd.Series):
            try:
                self._as_of = str(prices.index[-1])[:10]
            except (IndexError, TypeError):
                self._as_of = ""
            values = prices.values
        else:
            values = prices
        self._returns = log_returns(values)
        self._state = self._compute_state()
        return self._state

    def current_regime(self) -> RegimeState | None:
        return self._state

    def set_current_heat(self, heat: float):
        """Inform the detector of current portfolio heat (fraction of equity at risk at stops).

        v1 callers may pass "units" up to max_heat=1.0; anything > 1 is treated
        as a percentage and divided by 100.
        """
        h = float(heat)
        if h > 1.0:
            h = h / 100.0
        self._current_heat = max(0.0, h)
        if self._state is not None:
            self._state = self._compute_state()

    # ------------------------------------------------------------------
    # Internal: assemble state
    # ------------------------------------------------------------------

    def _signal_multiplier(self, T: float, eta: float, eta_eq: float, label: Regime) -> float:
        if label == Regime.CRISIS:
            return 0.0
        temp_factor    = min((self.base_temp / max(T, 1e-9)) ** 2, self.temp_cap)
        entropy_factor = math.exp(-(eta - eta_eq) / self.entropy_lambda)
        entropy_factor = min(max(entropy_factor, 0.25), 1.25)
        heat_factor    = max(0.0, 1.0 - self._current_heat / self.heat_max)
        raw = temp_factor * entropy_factor * heat_factor
        if label == Regime.TRANSITION:
            raw = min(raw, 1.0)           # neutral: never amplify while drifting
        return round(min(max(raw, 0.0), self.temp_cap), 4)

    def _compute_state(self) -> RegimeState:
        r = self._returns
        n = len(r)
        T   = temperature(r, self.window)
        S, eta = occupation_entropy(r, self.shape_window, self.base_temp)
        S_eq, eta_eq = equilibrium_entropy(T / self.base_temp) if not math.isnan(T) else (float('nan'), float('nan'))
        D   = kl_departure(r, self.shape_window, self._calibration['bins'])
        cal = self._calibration
        hot    = (not math.isnan(T)) and T > self.base_temp
        spread = (not math.isnan(S)) and S > cal['S_hi']        # occupation beyond the T_base band
        drift  = (not math.isnan(D)) and D > cal['D_hi']        # shape departing from Boltzmann
        # CRISIS   = hot AND the 60-day occupation has spread beyond the band that is
        #            normal at T_base (in practice: T ~ 1.3x T_base sustained over the window)
        # CHOPPY   = hot, occupation still within band (a short vol spike)
        # TRANSITION = cool, but the occupation *shape* is drifting from Boltzmann
        # TRENDING = cool, equilibrium
        if hot and spread:
            label = Regime.CRISIS
        elif hot:
            label = Regime.CHOPPY
        elif drift:
            label = Regime.TRANSITION
        else:
            label = Regime.TRENDING
        mult = self._signal_multiplier(T, eta, eta_eq, label) if not math.isnan(T) else 1.0
        heat_budget = max(0.0, 1.0 - self._current_heat / self.heat_max)
        return RegimeState(
            label             = label,
            temperature       = round(T, 4) if not math.isnan(T) else float('nan'),
            entropy           = round(S, 4) if not math.isnan(S) else float('nan'),
            heat_budget       = round(heat_budget, 4),
            kl_divergence     = round(D, 4) if not math.isnan(D) else float('nan'),
            signal_multiplier = mult,
            warning           = bool(drift),
            eta               = round(eta, 4) if not math.isnan(eta) else float('nan'),
            entropy_eq        = round(S_eq, 4) if not math.isnan(S_eq) else float('nan'),
            eta_eq            = round(eta_eq, 4) if not math.isnan(eta_eq) else float('nan'),
            entropy_hi        = round(cal['S_hi'], 4),
            kl_threshold      = round(cal['D_hi'], 4),
            heat              = round(self._current_heat, 4),
            heat_max          = self.heat_max,
            base_temp         = self.base_temp,
            window            = self.window,
            shape_window      = min(self.shape_window, n),
            n_returns         = n,
            as_of             = self._as_of,
        )


# ---------------------------------------------------------------------------
# Signal gate — wraps the detector and applies it to your signal stream
# ---------------------------------------------------------------------------

class SignalGate:
    """
    Sits between your signal aggregator and execution layer.
    Filters and sizes signals based on current regime.
    """

    # Regime → allowed directions
    DIRECTION_FILTER = {
        Regime.TRENDING:   {1, -1},   # both long and short OK
        Regime.CHOPPY:     {1, -1},   # both OK but sized down
        Regime.CRISIS:     set(),      # block all new entries
        Regime.TRANSITION: {1, -1},   # neutral — pass through, never amplified
    }

    def __init__(self, detector: RegimeDetector):
        self.detector = detector

    def process(self, signals: list[Signal]) -> list[Signal]:
        state = self.detector.current_regime()
        if state is None:
            return signals   # no data yet — pass through unmodified

        allowed = self.DIRECTION_FILTER[state.label]
        out = []
        for sig in signals:
            if sig.direction not in allowed:
                continue   # blocked by regime
            sig.sized_score = round(sig.raw_score * state.signal_multiplier, 4)
            if sig.sized_score > 0.01:   # drop negligible signals
                out.append(sig)
        return out


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        import yfinance as yf
        ticker = "SPY"
        prices = yf.download(ticker, period="6mo", interval="1d", progress=False)["Close"].squeeze()
    except Exception:
        rng = np.random.default_rng(42)
        n = 126
        rets = rng.normal(0.0004, 0.012, n)
        prices = 100 * np.exp(np.cumsum(rets))
        print("(Using synthetic prices — install yfinance for live data)\n")

    detector = RegimeDetector(base_temp=0.15)
    state    = detector.update(prices)

    print(f"Regime        : {state.label.value}  ({state.description})")
    print(f"Temperature   : {state.temperature:.2%}  (base: {state.base_temp:.0%})")
    print(f"Entropy       : {state.entropy:.3f}  eta={state.eta:.3f}  (equilibrium {state.entropy_eq:.3f}, hi {state.entropy_hi:.3f})")
    print(f"KL departure  : {state.kl_divergence:.4f}  (threshold {state.kl_threshold:.4f})" +
          ("  ⚠ DRIFT" if state.warning else ""))
    print(f"Heat Budget   : {state.heat_budget:.0%} remaining")
    print(f"Signal Mult   : {state.signal_multiplier:.2f}×")

    mock_signals = [
        Signal("substack:blockworks", "BTC", +1, 0.75),
        Signal("twitter:@pomp",        "ETH", -1, 0.60),
        Signal("newsletter:alpha",      "QQQ", +1, 0.50),
    ]
    gate  = SignalGate(detector)
    gated = gate.process(mock_signals)

    print(f"\nSignals in: {len(mock_signals)}  →  Signals out: {len(gated)}")
    for s in gated:
        direction = "LONG" if s.direction == 1 else "SHORT"
        print(f"  [{direction}] {s.ticker:5s} | {s.source:30s} | "
              f"raw={s.raw_score:.2f} → sized={s.sized_score:.2f}")
