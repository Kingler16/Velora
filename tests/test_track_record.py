"""Tests für das Messfundament (src/analysis/track_record.py).

Die DB liegt in tmp_path, Kurse kommen aus einer Fake-Historie — kein Netz,
keine echten memory/-Dateien.
"""

from datetime import date, datetime, timedelta

import pytest

from src.analysis import track_record as tr


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(tr, "DB_PATH", tmp_path / "track.db")
    monkeypatch.setattr(tr, "SNAPSHOT_DIR", tmp_path / "inputs")


def _bars(start: date, closes, lows=None, highs=None):
    out = []
    for i, c in enumerate(closes):
        d = start + timedelta(days=i)
        out.append({"date": d.isoformat(), "open": c,
                    "high": (highs or closes)[i], "low": (lows or closes)[i], "close": c})
    return out


def _fetcher(series: dict):
    """series: ticker -> Bars. Benchmark/FX ohne Angabe: konstant."""
    def fetch(ticker, start):
        if ticker in series:
            return series[ticker]
        return _bars(start, [100.0] * 400)
    return fetch


def _md(ticker, price, currency="EUR"):
    return {"positions": {ticker: {"price": {"current_price": price, "currency": currency}}},
            "indices": {tr.BENCHMARK_NAME: {"value": 100.0}, "EUR/USD": {"value": 1.0}}}


T0 = datetime(2026, 1, 5, 7, 0)


def test_watch_limit_never_touched_expires_and_is_no_hit():
    tr.record_briefing([{"ticker": "AAA", "action": "watch", "entry_price": 90, "target_price": 120,
                         "stop_loss": 80, "reasoning": "x" * 25}], [], _md("AAA", 100), now=T0)
    bars = _bars(T0.date(), [100.0] * 40, lows=[95.0] * 40)
    tr.evaluate_open(today=T0.date() + timedelta(days=35), fetch=_fetcher({"AAA": bars}))
    s = tr.compute_summary()
    assert s["closed_n"] == 0
    assert s["expired_n"] == 1


def test_target_hit_intraday_between_briefings_is_detected():
    tr.record_briefing([{"ticker": "AAA", "action": "buy", "shares": 1, "target_price": 110,
                         "stop_loss": 90, "reasoning": "x" * 25}], [], _md("AAA", 100), now=T0)
    closes = [100.0, 101.0, 102.0, 103.0, 101.0]
    highs = [100.0, 101.0, 111.0, 103.0, 101.0]   # Ziel nur im Tageshoch, Schluss darunter
    tr.evaluate_open(today=T0.date() + timedelta(days=5),
                     fetch=_fetcher({"AAA": _bars(T0.date(), closes, highs=highs)}))
    s = tr.compute_summary()
    assert s["closed_n"] == 1 and s["wins"] == 1
    assert s["by_exit"]["target_hit"] == 1
    assert s["avg_return_pct"] == pytest.approx(10.0)
    assert s["avg_alpha_pct"] == pytest.approx(10.0)   # Benchmark konstant


def test_gap_below_stop_exits_at_open_not_stop_level():
    tr.record_briefing([{"ticker": "AAA", "action": "buy", "shares": 1, "stop_loss": 90,
                         "reasoning": "x" * 25}], [], _md("AAA", 100), now=T0)
    bars = _bars(T0.date(), [100.0, 85.0])
    bars[1]["open"] = 85.0
    tr.evaluate_open(today=T0.date() + timedelta(days=2), fetch=_fetcher({"AAA": bars}))
    s = tr.compute_summary()
    assert s["by_exit"]["stop_hit"] == 1
    assert s["avg_return_pct"] == pytest.approx(-15.0)


def test_new_rec_supersedes_old_instead_of_overwriting():
    tr.record_briefing([{"ticker": "AAA", "action": "buy", "shares": 1, "reasoning": "x" * 25}],
                       [], _md("AAA", 100), now=T0)
    t1 = T0 + timedelta(days=10)
    tr.record_briefing([{"ticker": "AAA", "action": "buy", "shares": 2, "reasoning": "y" * 25}],
                       [], _md("AAA", 120), now=t1)
    closes = [100.0 + 2 * i for i in range(15)]   # Tag 9 schließt bei 118
    tr.evaluate_open(today=t1.date() + timedelta(days=3), fetch=_fetcher({"AAA": _bars(T0.date(), closes)}))
    s = tr.compute_summary()
    assert s["by_exit"]["superseded"] == 1
    assert s["avg_return_pct"] == pytest.approx(18.0)
    assert s["open_n"] == 1                        # die neue läuft weiter


def test_sell_is_right_when_price_falls():
    tr.record_briefing([{"ticker": "AAA", "action": "sell", "sell_pct": 50, "target_price": 80,
                         "stop_loss": 120, "reasoning": "x" * 25}], [], _md("AAA", 100), now=T0)
    tr.evaluate_open(today=T0.date() + timedelta(days=3),
                     fetch=_fetcher({"AAA": _bars(T0.date(), [100.0, 90.0, 79.0])}))
    s = tr.compute_summary()
    assert s["by_exit"]["target_hit"] == 1
    # Kurslücke unter das Ziel: Ausstieg zum Eröffnungskurs 79, nicht zum Ziel 80
    assert s["avg_return_pct"] == pytest.approx(21.0)


def test_hold_is_not_counted_and_post_stop_cost_is_measured():
    tr.record_briefing([{"ticker": "AAA", "action": "hold", "stop_loss": 95, "reasoning": "x" * 25}],
                       [], _md("AAA", 100), now=T0)
    closes = [100.0, 94.0] + [110.0] * 100        # Stop gerissen, danach Erholung
    tr.evaluate_open(today=T0.date() + timedelta(days=100),
                     fetch=_fetcher({"AAA": _bars(T0.date(), closes)}))
    s = tr.compute_summary()
    assert s["closed_n"] == 0                       # nicht in der Trefferquote
    assert s["stops_triggered_n"] == 1
    assert s["after_stop_pct"][90] > 0              # Stop hat Rendite gekostet


def test_usd_returns_are_converted_to_eur():
    tr.record_briefing([{"ticker": "US1", "action": "buy", "shares": 1, "target_price": 110,
                         "reasoning": "x" * 25}], [], _md("US1", 100, "USD"), now=T0)
    fx = _bars(T0.date(), [1.0, 1.0, 1.1])           # Dollar verliert 10 %
    tr.evaluate_open(today=T0.date() + timedelta(days=3),
                     fetch=_fetcher({"US1": _bars(T0.date(), [100.0, 100.0, 110.0]), "EURUSD=X": fx}))
    s = tr.compute_summary()
    assert s["avg_return_pct"] == pytest.approx(0.0, abs=0.01)


def test_rejected_candidates_are_tracked_once_and_not_if_recommended():
    md = _md("HELD", 50)
    md["watchlist"] = {"WL": {"price": {"current_price": 10.0, "currency": "EUR"}}}
    cands = [{"ticker": "SCR", "price": {"current_price": 20.0, "currency": "EUR"}},
             {"ticker": "PICK", "price": {"current_price": 30.0, "currency": "EUR"}}]
    rec = {"ticker": "PICK", "action": "buy", "shares": 1, "reasoning": "x" * 25}
    tr.record_briefing([rec], [], md, candidates=cands, now=T0)
    tr.record_briefing([], [], md, candidates=cands, now=T0 + timedelta(days=3))
    with tr._db() as conn:
        rows = sorted(r["ticker"] for r in conn.execute("SELECT ticker FROM candidates"))
    assert rows == ["SCR", "WL"]                   # PICK empfohlen, HELD im Depot, keine Dubletten


def test_nav_twr_ignores_cash_flows():
    def ov(shares, price, cash):
        return {"positions": [{"ticker": "AAA", "shares": shares, "current_price_eur": price,
                               "has_live_price": True}],
                "holdings_value_eur": shares * price, "cash_total": cash, "total_value_eur": shares * price + cash}
    tr.record_nav(ov(10, 100.0, 1000), bench_level=100.0, day=date(2026, 1, 5))
    # Zukauf von 10 Stück (Wert verdoppelt sich), Kurs selbst +10 %
    tr.record_nav(ov(20, 110.0, 0), bench_level=105.0, day=date(2026, 1, 6))
    perf = tr.nav_performance()
    assert perf["twr_pct"] == pytest.approx(10.0)
    assert perf["bench_pct"] == pytest.approx(5.0)
    assert perf["excess_pct"] == pytest.approx(5.0)


def test_wilson_interval_is_wide_for_small_samples():
    lo, hi = tr.wilson_interval(6, 10)
    assert lo < 35 and hi > 80
    assert tr.wilson_interval(0, 0) is None


def test_prompt_warns_below_min_sample():
    tr.record_briefing([{"ticker": "AAA", "action": "buy", "shares": 1, "target_price": 105,
                         "reasoning": "x" * 25}], [], _md("AAA", 100), now=T0)
    tr.evaluate_open(today=T0.date() + timedelta(days=3),
                     fetch=_fetcher({"AAA": _bars(T0.date(), [100.0, 106.0])}))
    text = tr.format_for_prompt()
    assert "Rauschen" in text
    assert "95-%-Intervall" in text


def test_backfill_runs_once():
    recs = [{"ticker": "AAA", "action": "buy", "shares": 1, "date": "2026-01-05T07:00:00",
             "entry_price": 100, "reasoning": "x" * 25}]
    fetch = _fetcher({"AAA": _bars(date(2025, 12, 20), [100.0] * 30)})
    assert tr.ensure_backfilled(recs, fetch) == 1
    assert tr.ensure_backfilled(recs, fetch) == 0


def test_input_snapshot_written(tmp_path):
    path = tr.save_input_snapshot("sys", "prompt", "antwort", now=T0)
    assert path and path.endswith(".json.gz")


def test_superseded_stop_without_trigger_is_done():
    tr.record_briefing([{"ticker": "AAA", "action": "hold", "stop_loss": 90, "reasoning": "x" * 25}],
                       [], _md("AAA", 100), now=T0)
    tr.record_briefing([{"ticker": "AAA", "action": "hold", "stop_loss": 95, "reasoning": "y" * 25}],
                       [], _md("AAA", 100), now=T0 + timedelta(days=5))
    # Kurs fällt erst NACH der neuen Empfehlung unter 90 → zählt für die neue, nicht die alte
    closes = [100.0] * 8 + [89.0] * 5
    tr.evaluate_open(today=T0.date() + timedelta(days=12), fetch=_fetcher({"AAA": _bars(T0.date(), closes)}))
    with tr._db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT stop_loss, status FROM recommendations ORDER BY id")]
    assert rows[0]["status"] == "done"
    assert rows[1]["status"] == "stop_triggered"
