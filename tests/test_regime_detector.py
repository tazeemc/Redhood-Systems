"""Tests for redhood_regime_detector v2: reachable regimes, calibrated thresholds, units."""

import math
import warnings

import pytest

np = pytest.importorskip("numpy")

import redhood_regime_detector as rd  # noqa: E402


@pytest.fixture(scope="module")
def cal():
    # Small simulation keeps the suite fast; thresholds are still quantiles of the null.
    return rd.calibrate(shape_window=60, base_temp=0.15, sims=600, seed=1, use_file=False)


def _prices_from_returns(rets):
    return 100.0 * np.exp(np.cumsum(rets))


def test_entropy_ceiling_and_equilibrium_values():
    # Ten levels: S <= ln 10, and the equilibrium curve rises with temperature.
    s1, eta1 = rd.equilibrium_entropy(1.0)
    s2, _ = rd.equilibrium_entropy(2.0)
    s_half, _ = rd.equilibrium_entropy(0.5)
    assert s_half < s1 < s2 <= math.log(10)
    assert abs(s1 - 1.896) < 0.01           # value quoted in the paper
    assert 0 < eta1 < 1


def test_calibration_quantiles_are_sane(cal):
    assert 1.9 < cal["S_hi"] < 2.2            # below the ln(10) ceiling, above the null mean
    assert cal["S_eq"] < cal["S_hi"]
    assert 0.05 < cal["D_hi"] < 0.3           # far below v1's uninformative 0.25 bias floor? (0.25 > bias at N=60)
    assert cal["bins"] == 7


def test_calm_market_is_trending(cal):
    rng = np.random.default_rng(0)
    rets = rng.laplace(0.0003, 0.10 / math.sqrt(252) / math.sqrt(2), 200)   # 10% vol, Laplace
    det = rd.RegimeDetector(base_temp=0.15, calibration=cal)
    st = det.update(_prices_from_returns(rets))
    assert st.label == rd.Regime.TRENDING
    assert st.temperature < 0.15
    assert not st.warning
    assert st.signal_multiplier > 1.0


def test_sustained_hot_market_reaches_crisis(cal):
    # 60 sessions at ~45% vol: the occupation spreads beyond the base band -> CRISIS is reachable.
    rng = np.random.default_rng(1)
    calm = rng.normal(0.0, 0.10 / math.sqrt(252), 120)
    hot = rng.normal(0.0, 0.45 / math.sqrt(252), 60)
    det = rd.RegimeDetector(base_temp=0.15, calibration=cal)
    st = det.update(_prices_from_returns(np.concatenate([calm, hot])))
    assert st.label == rd.Regime.CRISIS
    assert st.signal_multiplier == 0.0
    assert st.entropy > st.entropy_hi


def test_single_spike_is_choppy_not_crisis(cal):
    # A short burst of volatility raises the 20-day T but not the 60-day occupation: CHOPPY.
    rng = np.random.default_rng(2)
    calm = rng.normal(0.0, 0.10 / math.sqrt(252), 150)
    spike = rng.normal(0.0, 0.30 / math.sqrt(252), 12)
    det = rd.RegimeDetector(base_temp=0.15, calibration=cal)
    st = det.update(_prices_from_returns(np.concatenate([calm, spike])))
    assert st.temperature > 0.15
    assert st.label in (rd.Regime.CHOPPY, rd.Regime.CRISIS)
    assert st.label == rd.Regime.CHOPPY


def test_heat_reduces_multiplier_and_budget(cal):
    rng = np.random.default_rng(3)
    rets = rng.laplace(0.0, 0.10 / math.sqrt(252) / math.sqrt(2), 150)
    det = rd.RegimeDetector(base_temp=0.15, calibration=cal, heat_max=0.06)
    base = det.update(_prices_from_returns(rets))
    det.set_current_heat(0.03)                    # half the capacity used
    half = det.current_regime()
    assert half.heat_budget == pytest.approx(0.5, abs=1e-6)
    assert half.signal_multiplier < base.signal_multiplier
    det.set_current_heat(0.06)
    assert det.current_regime().signal_multiplier == 0.0


def test_percentage_base_temp_is_corrected(cal):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        det = rd.RegimeDetector(base_temp=25.0, calibration=cal)   # the v1 PowerShell mistake
    assert det.base_temp == pytest.approx(0.25)
    assert any("percentage" in str(x.message) for x in w)


def test_v1_keywords_accepted(cal):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        det = rd.RegimeDetector(base_temp=0.15, base_entropy=2.5, window=20, kl_alert=0.25, calibration=cal)
    rng = np.random.default_rng(4)
    st = det.update(_prices_from_returns(rng.normal(0, 0.01, 100)))
    assert isinstance(st, rd.RegimeState)
    d = st.to_dict()
    assert d["label"] in {"TRENDING", "CHOPPY", "CRISIS", "TRANSITION"}
    assert "kl_threshold" in d and "eta_eq" in d


def test_kl_departure_uses_laplace_scale():
    # Pure Laplace data should sit near the null mean, far below v1's 0.25 floor.
    rng = np.random.default_rng(5)
    vals = [rd.kl_departure(rng.laplace(0, 0.004, 60), 60) for _ in range(200)]
    assert np.mean(vals) < 0.12


def test_signal_gate_blocks_in_crisis(cal):
    rng = np.random.default_rng(6)
    hot = rng.normal(0.0, 0.5 / math.sqrt(252), 80)
    det = rd.RegimeDetector(base_temp=0.15, calibration=cal)
    det.update(_prices_from_returns(hot))
    gate = rd.SignalGate(det)
    out = gate.process([rd.Signal("x", "AAPL", +1, 0.9), rd.Signal("y", "MSFT", -1, 0.9)])
    assert out == []
