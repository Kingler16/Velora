"""Regressionstests für Datenfehler, die das LLM falsch informiert haben."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analysis import memory


# ─── Archiv-Kürzung behält die NEUESTEN Abschlüsse ───────────

def test_truncation_keeps_newest_closed(monkeypatch):
    old_closed = [{"ticker": f"OLD{i}", "status": "target_hit", "date": f"2026-04-{i + 1:02d}T07:00:00",
                   "closed_date": f"2026-04-{i + 1:02d}T07:00:00"} for i in range(memory.CLOSED_KEEP)]
    # Frisch geschlossen, steht aber (wie im echten Ablauf) VOR den alten in der Liste
    fresh = {"ticker": "NEW", "status": "stop_hit", "date": "2026-10-01T07:00:00",
             "closed_date": "2026-10-20T07:00:00"}
    store = {"recommendations.json": [fresh] + old_closed}
    monkeypatch.setattr(memory, "_load_json", lambda f, d: store.get(f, d))
    monkeypatch.setattr(memory, "_save_json", lambda f, data: store.__setitem__(f, data))
    monkeypatch.setattr("src.analysis.mandate.load_mandate", lambda: None)

    memory.save_recommendations([{"ticker": "X", "action": "buy", "shares": 1, "reasoning": "r" * 25}])

    tickers = [r["ticker"] for r in store["recommendations.json"]]
    assert "NEW" in tickers
    assert "OLD0" not in tickers


def test_save_recommendations_reports_dropped(monkeypatch):
    store = {}
    monkeypatch.setattr(memory, "_load_json", lambda f, d: store.get(f, d))
    monkeypatch.setattr(memory, "_save_json", lambda f, data: store.__setitem__(f, data))
    monkeypatch.setattr("src.analysis.mandate.load_mandate", lambda: None)
    res = memory.save_recommendations([
        {"ticker": "A", "action": "buy", "shares": 1, "reasoning": "r" * 25},
        {"ticker": "B", "action": "watch", "reasoning": "r" * 25},
    ])
    assert [r["ticker"] for r in res["accepted"]] == ["A"]
    assert res["dropped"][0]["ticker"] == "B"


# ─── Prompt-Formatierung ─────────────────────────────────────

def test_sentiment_percent_not_multiplied(monkeypatch):
    from src.analysis import prompt
    monkeypatch.setattr(prompt, "load_mandate", lambda: None)
    news = {"sentiment": {"MSFT": {"bullish": 65.0, "bearish": 5.0, "buzz_volume": 40,
                                   "source": "yfinance-analysts"}}}
    md = {"positions": {}, "watchlist": {}, "indices": {}}
    text = prompt.build_briefing_prompt({"accounts": {}}, md, {}, news, "")
    assert "65% bullish" in text
    assert "6500" not in text
    assert "40 Analysten" in text


def test_index_line_labels_day_and_five_day_change():
    from src.analysis.prompt import format_index_data
    line = format_index_data({"DAX": {"value": 20000, "change_pct": 0.5, "change_5d_pct": -2.0,
                                      "source": "yfinance", "timestamp": "2026-11-02T07:00:00"}})
    assert "heute +0.50%" in line and "5 Tage -2.00%" in line


def test_benchmark_uses_five_day_change():
    from src.analysis.performance import compute_benchmark_data
    data = compute_benchmark_data({"indices": {"DAX": {"change_pct": 0.5, "change_5d_pct": -2.0}}})
    assert data[0]["change_pct"] == -2.0


def test_cpi_requested_as_yoy(monkeypatch):
    from src.data import macro
    seen = {}

    class Resp:
        def json(self):
            return {"observations": [{"value": "3.1", "date": "2026-09-01"}]}

    def fake_get(url, params=None, timeout=None):
        seen[params["series_id"]] = params.get("units")
        return Resp()

    monkeypatch.setattr(macro.requests, "get", fake_get)
    out = macro.fetch_fred_data("key")
    assert seen["CPIAUCSL"] == "pc1"
    assert seen["FEDFUNDS"] == "lin"
    assert out["us_cpi_yoy"]["value"] == 3.1


def test_mandate_block_states_objective():
    from src.analysis.mandate import build_mandate_block
    block = build_mandate_block({"objective": {"primary_goal": "max_growth", "horizon_years": 10}})
    assert "ZIEL: maximales langfristiges Wachstum" in block
    assert "10 Jahre" in block


def test_system_prompt_has_no_blanket_conservatism():
    from src.analysis.prompt import build_system_prompt
    text = build_system_prompt({}, {})
    assert "KONSERVATIV" not in text
    assert "5-10%" not in text


# ─── Kalender ────────────────────────────────────────────────

@pytest.mark.parametrize("year,easter", [(2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
                                         (2030, date(2030, 4, 21))])
def test_easter(year, easter):
    from src.data.calendar import _easter_sunday
    assert _easter_sunday(year) == easter


def test_holidays_beyond_2026():
    from src.data.calendar import get_market_status
    assert not get_market_status(date(2027, 3, 26))["nyse_open"]       # Karfreitag 2027
    assert not get_market_status(date(2027, 11, 25))["nyse_open"]      # Thanksgiving 2027
    assert get_market_status(date(2027, 11, 25))["wien_open"]
    assert not get_market_status(date(2027, 7, 5))["nyse_open"]        # 4. Juli fällt auf So
    assert get_market_status(date(2027, 7, 5))["xetra_open"]


def test_macro_events_without_fred_key_have_fallback():
    from src.data.calendar import get_upcoming_macro_events
    events = get_upcoming_macro_events(40, "", today=date(2027, 1, 10))
    names = [e["name"] for e in events]
    assert any("FOMC" in n for n in names)                              # 27.01.2027
    assert any("Jobs Report" in n for n in names)


def test_missing_central_bank_year_is_flagged():
    from src.data.calendar import get_upcoming_macro_events
    events = get_upcoming_macro_events(30, "", today=date(2031, 3, 1))
    assert any(e["category"] == "INFO" for e in events)


# ─── Korrelation nach Datum ──────────────────────────────────

def test_correlation_aligns_by_date():
    from src.analysis.performance import compute_correlation_data
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2026-01-01", periods=120)
    base = rng.normal(0, 0.01, len(days))
    # B ist A, aber mit einem fehlenden Tag mitten drin (Feiertag) — positional
    # verschoben würde die Korrelation zusammenbrechen.
    keep = np.ones(len(days), dtype=bool)
    keep[30] = False
    a = {"price": {"returns": list(base), "return_dates": [d.strftime("%Y-%m-%d") for d in days],
                   "current_price": 1}}
    b = {"price": {"returns": list(base[keep]), "return_dates": [d.strftime("%Y-%m-%d") for d in days[keep]],
                   "current_price": 1}}
    res = compute_correlation_data({"positions": {"A": a, "B": b}})
    assert res["avg_correlation"] == pytest.approx(1.0, abs=0.01)
