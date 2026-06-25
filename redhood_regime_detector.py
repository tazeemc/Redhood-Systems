"""
redhood_regime_detector.py
RedHood Systems — Thermodynamic Regime Detection Module
Author: Tazeem Chowdhury / Redhood Capital

Plug this into your signal aggregation pipeline as a pre-filter layer.
Each incoming signal is gated and sized based on the current market regime.

Usage:
    from redhood_regime_detector import RegimeDetector, SignalGate

    detector = RegimeDetector(base_temp=0.15, base_entropy=2.5)
    detector.update(prices)          # pd.Series of close prices

    regime = detector.current_regime()
    print(regime)
    # RegimeState(label='TRENDING', temperature=0.11, entropy=1.8,
    #             heat_budget=0.85, kl_divergence=0.03, signal_multiplier=1.4)

    gate = SignalGate(detector)
    sized = gate.process(raw_signals)  # list of Signal objects
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Regime taxonomy (Section 6 of the paper)
# ---------------------------------------------------------------------------

class Regime(Enum):
    TRENDING    = "TRENDING"      # Low T, Low S  → amplify signals
    CHOPPY      = "CHOPPY"        # High T, Low S → reduce size
    CRISIS      = "CRISIS"        # High T, High S → halt new entries
    TRANSITION  = "TRANSITION"    # Low T, High S  → neutral, watch closely


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    label:             Regime
    temperature:       float   # annualised vol (market "T")
    entropy:           float   # Shannon entropy of return distribution
    heat_budget:       float   # fraction of max heat remaining [0, 1]
    kl_divergence:     float   # KL(empirical || Boltzmann reference)
    signal_multiplier: float   # size scalar to apply to incoming signals
    warning:           bool    # True when KL divergence exceeds alert threshold


@dataclass
class Signal:
    source:     str            # e.g. "substack:xyz", "twitter:@abc"
    ticker:     str
    direction:  int            # +1 long, -1 short
    raw_score:  float          # original conviction score [0, 1]
    sized_score: float = 0.0   # after regime adjustment


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------

class RegimeDetector:
    """
    Computes market temperature, entropy, KL divergence, and classifies
    the current regime. Call update() on each new bar.
    """

    def __init__(
        self,
        base_temp:      float = 0.15,   # annualised vol at "normal" conditions
        base_entropy:   float = 2.5,    # entropy at "normal" conditions
        window:         int   = 20,     # rolling window for vol / entropy
        kl_alert:       float = 0.25,   # KL divergence early-warning threshold
        max_heat:       float = 1.0,    # max portfolio heat (normalised)
    ):
        self.base_temp    = base_temp
        self.base_entropy = base_entropy
        self.window       = window
        self.kl_alert     = kl_alert
        self.max_heat     = max_heat

        self._returns:     pd.Series = pd.Series(dtype=float)
        self._current_heat: float    = 0.0
        self._state:       RegimeState | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, prices: pd.Series) -> RegimeState:
        """
        Ingest latest price series and recompute regime state.
        prices: pd.Series of close prices (any length >= window)
        """
        self._returns = np.log(prices / prices.shift(1)).dropna()
        self._state   = self._compute_state()
        return self._state

    def current_regime(self) -> RegimeState | None:
        return self._state

    def set_current_heat(self, heat: float):
        """Inform the detector of current portfolio heat (sum of abs positions)."""
        self._current_heat = min(heat, self.max_heat)

    # ------------------------------------------------------------------
    # Temperature  (Appendix B.1)
    # ------------------------------------------------------------------

    def _temperature(self) -> float:
        recent = self._returns.iloc[-self.window:]
        return float(recent.std() * np.sqrt(252))

    # ------------------------------------------------------------------
    # Entropy  (Appendix B.2)
    # ------------------------------------------------------------------

    def _entropy(self) -> float:
        recent = self._returns.iloc[-self.window:]
        hist, _ = np.histogram(recent, bins=10, density=True)
        prob = hist / (hist.sum() + 1e-12)
        prob = prob[prob > 0]
        return float(-np.sum(prob * np.log(prob)))

    # ------------------------------------------------------------------
    # KL Divergence: empirical vs Boltzmann reference  (Gibbs Lemma proof)
    # ------------------------------------------------------------------

    def _kl_divergence(self, T: float) -> float:
        """
        D_KL(empirical || Boltzmann).
        Large values signal regime drift — early warning trigger.
        """
        recent = self._returns.iloc[-self.window:]
        hist, edges = np.histogram(recent, bins=15, density=True)
        centres = (edges[:-1] + edges[1:]) / 2
        emp  = hist / (hist.sum() + 1e-12)

        # Boltzmann reference: P(r) ∝ exp(-|r|/σ)
        sigma = T / np.sqrt(252)
        boltz = np.exp(-np.abs(centres) / (sigma + 1e-12))
        boltz /= boltz.sum() + 1e-12

        mask = emp > 0
        return float(np.sum(emp[mask] * np.log(emp[mask] / (boltz[mask] + 1e-12))))

    # ------------------------------------------------------------------
    # Signal multiplier (temperature-adjusted, Section 5.1)
    # ------------------------------------------------------------------

    def _signal_multiplier(self, T: float, S: float) -> float:
        """
        Scales incoming signal conviction scores.
        - TRENDING:   boost up to (T_base/T)^2
        - CHOPPY:     dampen
        - CRISIS:     zero (block)
        - TRANSITION: neutral
        """
        temp_ratio    = self.base_temp / (T + 1e-9)
        entropy_factor = np.exp(-(S - self.base_entropy) / 2) if self.base_entropy < S else 1.0
        heat_factor   = 1.0 - (self._current_heat / self.max_heat)
        raw = float(temp_ratio ** 2 * entropy_factor * heat_factor)
        return round(min(max(raw, 0.0), 2.5), 4)   # cap at 2.5×

    # ------------------------------------------------------------------
    # Regime classification (Section 6)
    # ------------------------------------------------------------------

    def _classify(self, T: float, S: float) -> Regime:
        hi_T = self.base_temp < T
        hi_S = self.base_entropy < S
        if   not hi_T and not hi_S: return Regime.TRENDING
        elif     hi_T and not hi_S: return Regime.CHOPPY
        elif     hi_T and     hi_S: return Regime.CRISIS
        else:                       return Regime.TRANSITION

    # ------------------------------------------------------------------
    # Internal: assemble state
    # ------------------------------------------------------------------

    def _compute_state(self) -> RegimeState:
        T   = self._temperature()
        S   = self._entropy()
        kl  = self._kl_divergence(T)
        mul = self._signal_multiplier(T, S)
        reg = self._classify(T, S)

        # Override multiplier to 0 in CRISIS
        if reg == Regime.CRISIS:
            mul = 0.0

        heat_budget = 1.0 - (self._current_heat / self.max_heat)

        return RegimeState(
            label             = reg,
            temperature       = round(T, 4),
            entropy           = round(S, 4),
            heat_budget       = round(heat_budget, 4),
            kl_divergence     = round(kl, 4),
            signal_multiplier = mul,
            warning           = kl > self.kl_alert,
        )


# ---------------------------------------------------------------------------
# Signal gate — wraps the detector and applies it to your signal stream
# ---------------------------------------------------------------------------

class SignalGate:
    """
    Sits between your signal aggregator and execution layer.
    Filters and sizes signals based on current regime.

    Example pipeline:
        raw_signals = aggregator.get_signals()   # your existing code
        gated       = SignalGate(detector).process(raw_signals)
        executor.submit(gated)
    """

    # Regime → allowed directions
    DIRECTION_FILTER = {
        Regime.TRENDING:   {1, -1},   # both long and short OK
        Regime.CHOPPY:     {1, -1},   # both OK but sized down
        Regime.CRISIS:     set(),      # block all new entries
        Regime.TRANSITION: {1, -1},   # neutral — pass through at 1×
    }

    def __init__(self, detector: RegimeDetector):
        self.detector = detector

    def process(self, signals: list[Signal]) -> list[Signal]:
        state   = self.detector.current_regime()
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
        np.random.seed(42)
        n = 126
        returns = np.random.normal(0.0004, 0.012, n)
        prices = pd.Series(100 * np.exp(np.cumsum(returns)),
                           index=pd.date_range("2024-01-01", periods=n, freq="B"))
        print("(Using synthetic prices — install yfinance for live data)\n")

    detector = RegimeDetector(base_temp=0.15, base_entropy=2.5, window=20)
    state    = detector.update(prices)

    print(f"Regime        : {state.label.value}")
    print(f"Temperature   : {state.temperature:.2%}  (base: 15%)")
    print(f"Entropy       : {state.entropy:.3f}     (base: 2.50)")
    print(f"KL Divergence : {state.kl_divergence:.4f}" +
          ("  ⚠ REGIME DRIFT ALERT" if state.warning else ""))
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
