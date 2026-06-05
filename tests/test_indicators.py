"""Tabellen-Tests für die technischen Indikatoren + Insider-Aggregation in
src/data/market.py — konstruierte, handprüfbare Inputs, kein Netz/yfinance.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.data.market import aggregate_insiders, compute_indicators


# ---------------------------------------------------------------------------
# Hilfen: hist_1y-DataFrames im yfinance-Format (Open/High/Low/Close/Volume)
# ---------------------------------------------------------------------------

def _hist(closes, *, volume=None, high=None, low=None):
    """Baut ein OHLCV-DataFrame aus einer Close-Reihe.

    High/Low default auf Close +-1, Volume default konstant 1000.
    """
    n = len(closes)
    closes = list(map(float, closes))
    if high is None:
        high = [c + 1.0 for c in closes]
    if low is None:
        low = [c - 1.0 for c in closes]
    if volume is None:
        volume = [1000.0] * n
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": list(map(float, high)),
            "Low": list(map(float, low)),
            "Close": closes,
            "Volume": list(map(float, volume)),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# compute_indicators
# ---------------------------------------------------------------------------

def test_monotone_rising_series():
    """Monoton steigend → RSI nahe 100, über SMA200, positive Distanz, golden cross."""
    closes = list(range(100, 350))  # 250 Tage, +1/Tag
    ind = compute_indicators(_hist(closes))

    assert ind["rsi_14"] == 100.0  # nur Gewinne → loss=0 → RSI 100
    assert ind["above_sma200"] is True
    assert ind["dist_to_sma200_pct"] > 0
    assert ind["sma_50"] is not None and ind["sma_200"] is not None
    assert ind["sma_50"] > ind["sma_200"]  # schnellerer Schnitt über langsamerem
    assert ind["golden_cross"] is True


def test_constant_series_zero_vol():
    """Konstante Reihe → realized_vol ≈ 0, dist_to_sma200 ≈ 0, kein Cross."""
    closes = [200.0] * 250
    ind = compute_indicators(_hist(closes))

    assert ind["realized_vol_30d"] == 0.0
    assert ind["dist_to_sma200_pct"] == 0.0
    assert ind["above_sma200"] is False  # 200 > 200 ist False
    assert ind["golden_cross"] is False
    assert ind["cross_signal"] is None


def test_atr_constant_true_range():
    """High=Close+1, Low=Close-1 bei konstantem Close → TR konstant 2 → ATR=2."""
    closes = [200.0] * 250
    ind = compute_indicators(_hist(closes))
    assert ind["atr_14"] == 2.0
    # atr_pct = 2 / 200 * 100 = 1.0
    assert ind["atr_pct"] == 1.0


def test_volume_ratio_elevated():
    """Letzte 5 Tage doppeltes Volumen → avg_volume_ratio > 1."""
    n = 100
    vol = [1000.0] * (n - 5) + [3000.0] * 5
    ind = compute_indicators(_hist([200.0] * n, volume=vol))
    assert ind["avg_volume_ratio"] is not None
    assert ind["avg_volume_ratio"] > 1.0


def test_golden_cross_signal_detected():
    """Lange Seitwärtsphase, dann scharfer Anstieg → SMA50 kreuzt SMA200 in den
    letzten ~10 Tagen von unten nach oben → cross_signal 'golden'."""
    base = [200.0] * 255
    rising = list(np.linspace(202, 600, 5))  # 5 Tage scharf rauf
    ind = compute_indicators(_hist(base + rising))
    assert ind["cross_signal"] == "golden"
    assert ind["golden_cross"] is True


def test_too_short_history_is_none():
    """Zu kurze History → alle Indikatoren None, kein Crash."""
    ind = compute_indicators(_hist([100.0, 101.0, 102.0]))
    assert ind["rsi_14"] is None
    assert ind["sma_50"] is None
    assert ind["sma_200"] is None
    assert ind["atr_14"] is None
    assert ind["realized_vol_30d"] is None


def test_empty_and_none_history():
    """Leeres DataFrame / None → vollständiges None-Dict ohne Crash."""
    for bad in (None, pd.DataFrame()):
        ind = compute_indicators(bad)
        assert ind["rsi_14"] is None
        assert ind["sma_200"] is None
        assert ind["avg_volume_ratio"] is None


# ---------------------------------------------------------------------------
# aggregate_insiders
# ---------------------------------------------------------------------------

def _d(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_cluster_buy_detected():
    """3 verschiedene Käufer innerhalb 30 Tagen → cluster_buy True."""
    txs = [
        {"insider": "Alice", "transaction": "Buy", "value": 10000, "date": _d(5)},
        {"insider": "Bob", "transaction": "Purchase", "value": 5000, "date": _d(10)},
        {"insider": "Carol", "transaction": "Buy", "value": 7000, "date": _d(20)},
    ]
    summ = aggregate_insiders(txs)
    assert summ["cluster_buy"] is True
    assert summ["distinct_buyers_90d"] == 3
    assert summ["distinct_sellers_90d"] == 0
    assert summ["net_value_90d"] == 22000.0


def test_option_exercise_and_gift_filtered():
    """Option Exercise / Gift / Conversion werden ignoriert."""
    txs = [
        {"insider": "Alice", "transaction": "Option Exercise", "value": 50000, "date": _d(3)},
        {"insider": "Bob", "transaction": "Gift", "value": 9000, "date": _d(4)},
        {"insider": "Carol", "transaction": "Stock Conversion", "value": 8000, "date": _d(5)},
        {"insider": "Dave", "transaction": "Buy", "value": 1000, "date": _d(6)},
    ]
    summ = aggregate_insiders(txs)
    assert summ["distinct_buyers_90d"] == 1  # nur Dave
    assert summ["net_value_90d"] == 1000.0
    assert summ["cluster_buy"] is False


def test_90d_cutoff_drops_old():
    """Transaktion älter als 90 Tage fällt komplett raus."""
    txs = [
        {"insider": "Alice", "transaction": "Buy", "value": 10000, "date": _d(120)},  # zu alt
        {"insider": "Bob", "transaction": "Buy", "value": 4000, "date": _d(10)},
    ]
    summ = aggregate_insiders(txs)
    assert summ["distinct_buyers_90d"] == 1  # nur Bob
    assert summ["net_value_90d"] == 4000.0


def test_net_value_buy_minus_sell():
    """net_value = Σ Buy − Σ Sell."""
    txs = [
        {"insider": "Alice", "transaction": "Buy", "value": 10000, "date": _d(5)},
        {"insider": "Bob", "transaction": "Sale", "value": 4000, "date": _d(8)},
        {"insider": "Carol", "transaction": "Sell", "value": 1000, "date": _d(9)},
    ]
    summ = aggregate_insiders(txs)
    assert summ["net_value_90d"] == 5000.0  # 10000 - 4000 - 1000
    assert summ["distinct_buyers_90d"] == 1
    assert summ["distinct_sellers_90d"] == 2
    assert summ["cluster_buy"] is False  # nur 1 Käufer


def test_empty_and_bad_dates():
    """Leere Liste → Nullsummary; kaputtes Datum wird übersprungen, kein Crash."""
    assert aggregate_insiders([]) == {
        "net_value_90d": 0.0,
        "distinct_buyers_90d": 0,
        "distinct_sellers_90d": 0,
        "cluster_buy": False,
    }
    txs = [
        {"insider": "Alice", "transaction": "Buy", "value": 1000, "date": "not-a-date"},
        {"insider": "Bob", "transaction": "Buy", "value": 2000, "date": None},
        {"insider": "Carol", "transaction": "Buy", "value": 3000, "date": _d(5)},
    ]
    summ = aggregate_insiders(txs)
    assert summ["distinct_buyers_90d"] == 1  # nur Carol mit gültigem Datum
    assert summ["net_value_90d"] == 3000.0
