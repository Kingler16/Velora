"""Tests für die ehrlichen Rendite-Metriken in compute_recommendation_data.

compute_recommendation_data liest die ECHTE memory/recommendations.json via
`MEMORY_DIR / "recommendations.json"`. Hier wird MEMORY_DIR per monkeypatch auf
tmp_path umgebogen und dort eine konstruierte JSON abgelegt — die echte Datei
wird NIE berührt.

Abgedeckt:
  - avg_win_pct / avg_loss_pct aus realized_pct.
  - Expectancy-Formel p(win)*avg_win + p(loss)*avg_loss.
  - avg_holding_days aus zwei ISO-Daten (date / closed_date).
  - Defensiver Fallback: fehlendes realized_pct -> Rekonstruktion aus
    entry vs. target_hit/stop_hit-Level (inkl. sell-Inversion).
"""

import json

import pytest

from src.analysis import performance


def _write_recs(monkeypatch, tmp_path, recs):
    """Legt recs als recommendations.json unter tmp_path ab und biegt MEMORY_DIR um."""
    (tmp_path / "recommendations.json").write_text(json.dumps(recs), encoding="utf-8")
    monkeypatch.setattr(performance, "MEMORY_DIR", tmp_path)


def test_avg_win_loss_from_realized_pct(monkeypatch, tmp_path):
    """avg_win_pct / avg_loss_pct mitteln die gespeicherten realized_pct."""
    recs = [
        {"ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 10.0},
        {"ticker": "B", "action": "buy", "status": "target_hit", "realized_pct": 20.0},
        {"ticker": "C", "action": "buy", "status": "stop_hit", "realized_pct": -8.0},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    assert data["avg_win_pct"] == 15.0          # (10 + 20) / 2
    assert data["avg_loss_pct"] == -8.0
    # avg_realized über alle mit Wert: (10 + 20 - 8) / 3 = 7.33 -> 7.3
    assert data["avg_realized_pct"] == 7.3


def test_expectancy_formula(monkeypatch, tmp_path):
    """Expectancy = p(win)*avg_win + p(loss)*avg_loss."""
    recs = [
        {"ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 30.0},
        {"ticker": "B", "action": "buy", "status": "stop_hit", "realized_pct": -10.0},
        {"ticker": "C", "action": "buy", "status": "stop_hit", "realized_pct": -10.0},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    # p_win = 1/3, avg_win = 30, avg_loss = -10
    # 1/3 * 30 + 2/3 * (-10) = 10 - 6.667 = 3.333 -> 3.3
    assert data["hit_rate"] == 33  # 1/3 -> 33%
    assert data["expectancy_pct"] == 3.3


def test_avg_holding_days_from_two_dates(monkeypatch, tmp_path):
    """avg_holding_days aus (closed_date - date), robust gegen Mischformate."""
    recs = [
        {
            "ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 5.0,
            "date": "2026-01-01", "closed_date": "2026-01-11",   # 10 Tage
        },
        {
            "ticker": "B", "action": "buy", "status": "stop_hit", "realized_pct": -3.0,
            "date": "2026-02-01T09:00:00", "closed_date": "2026-02-21T09:00:00",  # 20 Tage
        },
        {
            "ticker": "C", "action": "buy", "status": "target_hit", "realized_pct": 2.0,
            "date": "kaputt", "closed_date": "2026-03-01",        # unparsebar -> übersprungen
        },
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    assert data["avg_holding_days"] == 15.0  # (10 + 20) / 2, dritte Rec übersprungen


def test_fallback_realized_pct_from_levels(monkeypatch, tmp_path):
    """Ohne realized_pct: Rekonstruktion aus entry vs. Exit-Level, sell invertiert."""
    recs = [
        # buy target_hit: (120/100 - 1)*100 = +20
        {"ticker": "A", "action": "buy", "status": "target_hit",
         "entry_price": 100, "target_price": 120, "stop_loss": 90},
        # buy stop_hit: (90/100 - 1)*100 = -10
        {"ticker": "B", "action": "buy", "status": "stop_hit",
         "entry_price": 100, "target_price": 130, "stop_loss": 90},
        # sell target_hit: roh (80/100-1)*100 = -20, sell invertiert -> +20
        {"ticker": "C", "action": "sell", "status": "target_hit",
         "entry_price": 100, "target_price": 80, "stop_loss": 110},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    # Wins: A (+20), C (+20) -> avg 20 ; Loss: B (-10)
    assert data["avg_win_pct"] == 20.0
    assert data["avg_loss_pct"] == -10.0


def test_realized_pct_preferred_over_levels(monkeypatch, tmp_path):
    """Gespeichertes realized_pct hat Vorrang vor der Level-Rekonstruktion."""
    recs = [
        # Levels würden +20 ergeben, aber realized_pct=12 ist gespeichert -> 12 gewinnt.
        {"ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 12.0,
         "entry_price": 100, "target_price": 120, "stop_loss": 90},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    assert data["avg_win_pct"] == 12.0


def test_missing_metrics_keys_present_when_empty(monkeypatch, tmp_path):
    """Leerfall: alle neuen Keys existieren (None), Render-Funktion crasht nicht."""
    _write_recs(monkeypatch, tmp_path, [])

    data = performance.compute_recommendation_data({})

    for key in ("avg_win_pct", "avg_loss_pct", "avg_realized_pct",
                "expectancy_pct", "avg_holding_days"):
        assert key in data and data[key] is None

    # track_recommendation_performance darf hier nicht auf fehlende Keys zugreifen.
    assert performance.track_recommendation_performance({}) == "Noch keine Empfehlungen zum Tracken."


def test_no_realized_value_excluded_from_returns_but_counts_hit_rate(monkeypatch, tmp_path):
    """Rec ohne realized_pct UND ohne entry/Level: aus Rendite raus, Hit-Rate bleibt."""
    recs = [
        {"ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 10.0},
        # Win ohne jede Renditebasis -> zählt in Hit-Rate, nicht in avg_win_pct.
        {"ticker": "B", "action": "buy", "status": "target_hit"},
        {"ticker": "C", "action": "buy", "status": "stop_hit", "realized_pct": -5.0},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    data = performance.compute_recommendation_data({})

    assert data["total_closed"] == 3
    assert data["hit_rate"] == 67          # 2 wins / 3 -> 66.7 -> 67
    assert data["avg_win_pct"] == 10.0     # nur A, B ausgelassen
    assert data["avg_loss_pct"] == -5.0


def test_render_includes_metric_lines(monkeypatch, tmp_path):
    """track_recommendation_performance nimmt die neuen Zeilen auf, alte bleiben."""
    recs = [
        {"ticker": "A", "action": "buy", "status": "target_hit", "realized_pct": 20.0,
         "date": "2026-01-01", "closed_date": "2026-01-11"},
        {"ticker": "B", "action": "buy", "status": "stop_hit", "realized_pct": -10.0,
         "date": "2026-01-01", "closed_date": "2026-01-21"},
    ]
    _write_recs(monkeypatch, tmp_path, recs)

    out = performance.track_recommendation_performance({})

    assert "EMPFEHLUNGS-BILANZ:" in out          # alte Zeile unverändert da
    assert "Expectancy" in out
    assert "Ø Haltedauer" in out
