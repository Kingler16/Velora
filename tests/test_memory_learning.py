"""Tests für den Plausi-Check der Order-Levels (Geld-Guardrail, Phase 5)."""

from src.analysis.memory import _plausi_check

MD = {
    "positions": {"NVDA": {"price": {"current_price": 140.0}}},
    "watchlist": {"XYZ": {"price": {"current_price": 100.0}}},
}


def test_no_marketdata_passes():
    assert _plausi_check({"ticker": "NVDA", "entry_price": 50}, None) == (True, "")


def test_drops_entry_far_from_live():
    ok, reason = _plausi_check({"ticker": "NVDA", "entry_price": 50}, MD)  # 50 vs 140 = -64%
    assert not ok and "weicht" in reason


def test_accepts_entry_near_live():
    ok, _ = _plausi_check({"ticker": "NVDA", "entry_price": 145}, MD)  # ~3.6%
    assert ok


def test_drops_bad_ordering_buy():
    # buy erwartet stop < entry < target; hier stop > entry → drop
    ok, reason = _plausi_check(
        {"ticker": "NVDA", "action": "buy", "entry_price": 140, "stop_loss": 150, "target_price": 160}, MD)
    assert not ok and "unplausibel" in reason


def test_accepts_good_ordering_buy():
    ok, _ = _plausi_check(
        {"ticker": "NVDA", "action": "buy", "entry_price": 140, "stop_loss": 130, "target_price": 160}, MD)
    assert ok


def test_sell_ordering_inverted():
    # sell erwartet target < entry < stop
    ok, _ = _plausi_check(
        {"ticker": "NVDA", "action": "sell", "entry_price": 140, "stop_loss": 150, "target_price": 130}, MD)
    assert ok


def test_unknown_ticker_no_live_check():
    # Ticker nicht in market_data → kein Live-Check, Ordering ok → pass
    ok, _ = _plausi_check({"ticker": "AAA", "entry_price": 99}, MD)
    assert ok


def test_watchlist_ticker_used_for_live_check():
    ok, reason = _plausi_check({"ticker": "XYZ", "entry_price": 200}, MD)  # 200 vs 100 = +100%
    assert not ok and "weicht" in reason
