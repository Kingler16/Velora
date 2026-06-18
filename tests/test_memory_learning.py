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


def _setup_recs(tmp_path, monkeypatch, recs):
    import src.analysis.memory as mem
    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    mem._save_json("recommendations.json", recs)
    return mem


def test_outcomes_hold_without_levels_survives(tmp_path, monkeypatch):
    # Regression 2026-06-08: offene hold-Rec ohne target/stop/entry riss das
    # Briefing mit TypeError (float >= None) ab. Muss offen bleiben, kein Crash.
    mem = _setup_recs(tmp_path, monkeypatch, [{
        "ticker": "NVDA", "action": "hold", "status": "open",
        "target_price": None, "stop_loss": None, "entry_price": None,
        "reasoning": "Alt-Daten ohne Levels", "date": "2026-05-25T07:00:00",
    }])
    out = mem.update_recommendation_outcomes(MD)
    assert out[0]["status"] == "open"


def test_outcomes_stop_only_sell_triggers(tmp_path, monkeypatch):
    # sell nur mit Stop (target=None) ist legitim — Stop über Kurs muss weiter auslösen
    mem = _setup_recs(tmp_path, monkeypatch, [{
        "ticker": "NVDA", "action": "sell", "status": "open",
        "target_price": None, "stop_loss": 130.0, "entry_price": None,
        "reasoning": "Stop-only Sell", "date": "2026-05-25T07:00:00",
    }])
    out = mem.update_recommendation_outcomes(MD)  # Kurs 140 >= Stop 130
    assert out[0]["status"] == "stop_hit"


def test_record_trade_appends_and_truncates(tmp_path, monkeypatch):
    import src.analysis.memory as mem
    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    for i in range(mem.TRADE_HISTORY_MAX + 5):
        mem.record_trade("buy", f"T{i}", 1, 10.0)
    hist = mem._load_json("trade_history.json", [])
    assert len(hist) == mem.TRADE_HISTORY_MAX  # älteste fallen raus
    assert hist[-1]["ticker"] == f"T{mem.TRADE_HISTORY_MAX + 4}"


def test_context_includes_recent_trades(tmp_path, monkeypatch):
    # Regression 2026-06-18: nach Teilverkauf hielt das Briefing an alter These fest,
    # weil der Trade nirgends im Prompt-Kontext auftauchte.
    import src.analysis.memory as mem
    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    mem.record_trade("sell", "ASML.AS", 1.0, 1671.0, "trade_republic",
                     shares_before=1.157, shares_after=0.157)
    ctx = mem.get_context_for_prompt()
    assert "VERKAUFT" in ctx and "ASML.AS" in ctx
    assert "1.16 → 0.16 Stk" in ctx  # Positionsänderung sichtbar fürs LLM
