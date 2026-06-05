"""Tests fuer Risiko-, Korrelations- & Regime-Analyse in src/analysis/performance.py.

Alle Eingaben sind konstruierte market_data/macro_data-Dicts (kein Netz, kein I/O).
Geprueft werden Groessenordnung der Metriken, defensive Pfade und das Regime-Scoring.
"""

import math

import numpy as np
import pytest

from src.analysis.performance import (
    classify_regime,
    compute_correlation_data,
    compute_risk_metrics,
)


# ---------------------------------------------------------------------------
# Helfer zum Bauen von market_data / macro_data
# ---------------------------------------------------------------------------

def _pos(returns=None, current_price=100.0, shares=None, above_sma200=None):
    price = {"current_price": current_price}
    if returns is not None:
        price["returns"] = [round(float(x), 5) for x in returns]
    if above_sma200 is not None:
        price["above_sma200"] = above_sma200
    pos = {"price": price}
    if shares is not None:
        pos["shares"] = shares
    return pos


def _market(positions=None, vix=None):
    md = {"positions": positions or {}, "indices": {}}
    if vix is not None:
        md["indices"]["VIX"] = {"value": vix}
    return md


def _macro(fed=None, spread=None, fg_value=None, fg_rating=None):
    macro = {"us": {}, "fear_greed": {}}
    if fed is not None:
        macro["us"]["fed_funds_rate"] = {"value": fed}
    if spread is not None:
        macro["us"]["yield_curve_spread"] = {"value": spread}
    if fg_value is not None:
        macro["fear_greed"] = {"value": fg_value, "rating": fg_rating}
    return macro


# ---------------------------------------------------------------------------
# compute_risk_metrics
# ---------------------------------------------------------------------------

def test_risk_metrics_vol_and_sharpe_magnitude():
    """Alternierende +1%/-0.5%-Serie -> bekannte Vol/Sharpe-Groessenordnung."""
    returns = [0.01, -0.005] * 30  # 60 Werte
    md = _market({"AAA": _pos(returns=returns)})
    macro = _macro(fed=4.0)  # rf = 0.04

    result = compute_risk_metrics(md, macro)
    m = result["per_position"]["AAA"]

    # Handgeprueft: std*sqrt(252)*100 ~ 11.9
    assert m["vol_annual"] == pytest.approx(11.9, abs=0.2)
    # mean=0.0025, std=0.0075 -> sharpe ~ 4.96
    assert m["sharpe"] == pytest.approx(4.96, abs=0.05)
    assert result["rf_used"] == pytest.approx(0.04, abs=1e-9)


def test_risk_metrics_max_drawdown_falling_series():
    """Monoton fallende Serie -> Max-Drawdown = gesamter kumulierter Verlust (negativ)."""
    returns = [-0.01] * 50
    md = _market({"DOWN": _pos(returns=returns)})
    macro = _macro(fed=4.5)

    result = compute_risk_metrics(md, macro)
    dd = result["per_position"]["DOWN"]["max_drawdown"]

    expected = (0.99 ** 50 - 1) * 100  # ~ -39.5
    assert dd == pytest.approx(round(expected, 1), abs=0.2)
    assert dd < 0


def test_risk_metrics_rf_fallback_and_skip_short():
    """Fehlende Fed-Rate -> rf-Fallback 0.04; zu kurze returns -> Position ausgelassen."""
    md = _market({
        "OK": _pos(returns=[0.002, -0.001] * 20),  # 40 Werte
        "SHORT": _pos(returns=[0.01] * 5),          # < MIN_RETURNS
        "NORET": _pos(returns=None),                 # gar keine returns
    })
    macro = _macro()  # keine Fed-Rate

    result = compute_risk_metrics(md, macro)
    assert result["rf_used"] == pytest.approx(0.04, abs=1e-9)
    assert "OK" in result["per_position"]
    assert "SHORT" not in result["per_position"]
    assert "NORET" not in result["per_position"]


# ---------------------------------------------------------------------------
# compute_correlation_data
# ---------------------------------------------------------------------------

def test_correlation_identical_series_top_pair():
    """Zwei identische Serien -> corr ~ 1.0 als Top-Pair; effective_positions plausibel."""
    rng = np.random.default_rng(42)
    base = rng.normal(0, 0.01, 80).tolist()
    md = _market({
        "AAA": _pos(returns=base, current_price=100.0, shares=10),
        "BBB": _pos(returns=base, current_price=100.0, shares=10),
    })

    result = compute_correlation_data(md)
    assert len(result["top_pairs"]) == 1
    pair = result["top_pairs"][0]
    assert {pair["a"], pair["b"]} == {"AAA", "BBB"}
    assert pair["corr"] == pytest.approx(1.0, abs=0.01)
    # Zwei gleich grosse Positionen -> HHI 0.5 -> effective_positions ~ 2.0
    assert result["effective_positions"] == pytest.approx(2.0, abs=0.05)
    assert result["avg_correlation"] == pytest.approx(1.0, abs=0.01)


def test_correlation_anticorrelated_pair_and_defensive():
    """Anti-korrelierte Serie taucht als Top-Pair auf (|corr|>0.7, negativ)."""
    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.01, 60).tolist()
    inv = [-x for x in base]
    md = _market({
        "UP": _pos(returns=base),
        "DOWN": _pos(returns=inv),
    })
    result = compute_correlation_data(md)
    assert len(result["top_pairs"]) == 1
    assert result["top_pairs"][0]["corr"] == pytest.approx(-1.0, abs=0.01)

    # Defensiv: < 2 Positionen mit returns -> alles None/leer.
    md_one = _market({"SOLO": _pos(returns=base)})
    empty = compute_correlation_data(md_one)
    assert empty["top_pairs"] == []
    assert empty["effective_positions"] is None
    assert empty["avg_correlation"] is None


# ---------------------------------------------------------------------------
# classify_regime
# ---------------------------------------------------------------------------

def test_regime_risk_off_extreme():
    """VIX 30 + F&G 20 + inverse Kurve + Breadth 20% -> Risk-Off."""
    positions = {
        "A": _pos(above_sma200=True),
        "B": _pos(above_sma200=False),
        "C": _pos(above_sma200=False),
        "D": _pos(above_sma200=False),
        "E": _pos(above_sma200=False),
    }
    md = _market(positions, vix=30)
    macro = _macro(spread=-0.5, fg_value=20, fg_rating="Extreme Fear")

    result = classify_regime(md, macro)
    assert result["label"] == "Risk-Off"
    assert result["score"] == -4
    assert any("VIX" in d for d in result["drivers"])


def test_regime_risk_on_extreme():
    """VIX 12 + F&G 70 + normale Kurve + Breadth 80% -> Risk-On."""
    positions = {
        "A": _pos(above_sma200=True),
        "B": _pos(above_sma200=True),
        "C": _pos(above_sma200=True),
        "D": _pos(above_sma200=True),
        "E": _pos(above_sma200=False),
    }
    md = _market(positions, vix=12)
    macro = _macro(spread=1.2, fg_value=70, fg_rating="Greed")

    result = classify_regime(md, macro)
    assert result["label"] == "Risk-On"
    assert result["score"] == 3


def test_regime_neutral_and_missing_data():
    """Mittelwerte -> Neutral; komplett fehlende Daten crasht nicht."""
    positions = {
        "A": _pos(above_sma200=True),
        "B": _pos(above_sma200=False),
    }
    md = _market(positions, vix=20)
    macro = _macro(spread=0.5, fg_value=50, fg_rating="Neutral")
    result = classify_regime(md, macro)
    assert result["label"] == "Neutral"
    assert result["score"] == 0

    # Alles leer -> Score 0, Label Neutral, keine Exception.
    empty = classify_regime({}, {})
    assert empty["label"] == "Neutral"
    assert empty["score"] == 0
    assert isinstance(empty["drivers"], list)
