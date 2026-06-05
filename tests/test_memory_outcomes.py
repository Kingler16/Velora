"""Tests für update_recommendation_outcomes in src/analysis/memory.py.

Die Funktion liest/schreibt normalerweise die ECHTE memory/recommendations.json.
Hier wird sie vollständig isoliert: _load_json wird mit den Test-Recs gemockt,
_save_json wird abgefangen. Es wird KEINE echte Datei berührt.

Kern-Assertion: sell-Empfehlungen sind invertiert (Ziel UNTER Kurs = getroffen),
buy-Empfehlungen nicht (Ziel ÜBER Kurs = getroffen).
"""

import pytest

from src.analysis import memory


def _md_price(ticker, price):
    return {"positions": {ticker: {"price": {"current_price": price}}}}


def _patch_io(monkeypatch, recs):
    """Mockt die JSON-IO-Schicht: _load_json liefert recs, _save_json sammelt."""
    saved = {}

    def fake_load(filename, default):
        return recs

    def fake_save(filename, data):
        saved["filename"] = filename
        saved["data"] = data

    monkeypatch.setattr(memory, "_load_json", fake_load)
    monkeypatch.setattr(memory, "_save_json", fake_save)
    return saved


def test_sell_target_below_price_is_hit(monkeypatch):
    """SELL mit target UNTER aktuellem Kurs -> target_hit (Inversion)."""
    recs = [{
        "ticker": "TSLA",
        "action": "sell",
        "status": "open",
        "target_price": 200,   # unter aktuellem Kurs
        "stop_loss": 320,      # ueber aktuellem Kurs
        "reasoning": "x" * 25,
    }]
    saved = _patch_io(monkeypatch, recs)

    result = memory.update_recommendation_outcomes(_md_price("TSLA", 180))

    assert result[0]["status"] == "target_hit"
    assert "180" in result[0]["outcome"]
    # wurde persistiert (gemockt)
    assert saved["data"][0]["status"] == "target_hit"


def test_buy_same_setup_not_hit(monkeypatch):
    """BUY mit gleichem Setup (target unter Kurs) -> NICHT getroffen.

    Fuer buy ist target ein Aufwaerts-Ziel: current >= target waere hit.
    Hier liegt target (200) unter Kurs (180)? Nein -> wir spiegeln das
    sell-Setup: target=200 ueber Kurs 180 ist fuer buy NICHT erreicht,
    stop=320 weit drueber ist auch nicht erreicht (buy-stop ist current<=stop).
    """
    recs = [{
        "ticker": "TSLA",
        "action": "buy",
        "status": "open",
        "target_price": 200,   # buy: braucht current >= 200, haben aber 180
        "stop_loss": 150,      # buy: braucht current <= 150, haben aber 180
        "entry_price": 180,
        "reasoning": "x" * 25,
    }]
    saved = _patch_io(monkeypatch, recs)

    result = memory.update_recommendation_outcomes(_md_price("TSLA", 180))

    assert result[0]["status"] == "open"  # weder target noch stop getroffen
    # unrealized_pct wird gesetzt (entry vorhanden), aber Status bleibt offen
    assert result[0].get("unrealized_pct") == 0.0


def test_buy_target_above_price_is_hit(monkeypatch):
    """BUY mit target erreicht (current >= target) -> target_hit, nicht invertiert."""
    recs = [{
        "ticker": "AAPL",
        "action": "buy",
        "status": "open",
        "target_price": 150,
        "stop_loss": 90,
        "reasoning": "x" * 25,
    }]
    _patch_io(monkeypatch, recs)

    result = memory.update_recommendation_outcomes(_md_price("AAPL", 160))

    assert result[0]["status"] == "target_hit"


def test_sell_unrealized_pct_inverted(monkeypatch):
    """SELL ohne Target-/Stop-Treffer: unrealized_pct ist invertiert.

    Kurs faellt unter entry -> fuer einen Short/Sell ist das ein Gewinn (positiv).
    """
    recs = [{
        "ticker": "DIS",
        "action": "sell",
        "status": "open",
        "target_price": 50,    # nicht erreicht (Kurs 90 > 50)
        "stop_loss": 200,      # nicht erreicht (Kurs 90 < 200)
        "entry_price": 100,
        "reasoning": "x" * 25,
    }]
    _patch_io(monkeypatch, recs)

    result = memory.update_recommendation_outcomes(_md_price("DIS", 90))

    # raw = (90/100 - 1)*100 = -10 ; sell invertiert -> +10
    assert result[0]["status"] == "open"
    assert result[0]["unrealized_pct"] == 10.0
