"""Tests für den Cash-Einsatzplan (src/analysis/cash_plan.py) und die Mandats-Policy."""

from datetime import date

import pytest

from src.analysis import cash_plan as cp
from src.analysis.mandate import build_mandate_block, compute_strategy_drift, lint_mandate, validate_mandate_schema


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "STATE_PATH", tmp_path / "cash_plan.json")


def _ov(total, cash, interest=2.0):
    return {"total_value_eur": total, "cash_total": cash, "positions": [],
            "bank_accounts": [{"value": cash, "interest": interest}]}


MANDATE = {"objective": {"horizon_years": 10, "primary_goal": "max_growth"},
           "targets": {"cash_pct": 20},
           "policy": {"cash": {"min": 15, "target": 20, "max": 25}, "deployment": {"months": 4}}}


def test_without_band_plan_is_off():
    assert cp.compute_cash_plan(_ov(100_000, 50_000), {"targets": {"cash_pct": 20}}) is None
    assert cp.format_cash_plan(None) == ""


def test_plan_splits_excess_into_tranches():
    plan = cp.compute_cash_plan(_ov(100_000, 45_000), MANDATE, today=date(2026, 11, 3))
    assert plan["excess_eur"] == 20_000
    assert plan["tranche_eur"] == 5_000
    assert plan["budget_eur"] == 5_000 and plan["month"] == 1
    # 20.000 € × (7 % − 2 %) = 1.000 €/Jahr
    assert plan["drag_eur_per_year"] == 1_000
    text = cp.format_cash_plan(plan)
    assert "BUDGET DIESEN MONAT: 5.000 €" in text
    assert "Market-Timing" in text


def test_executed_buys_reduce_budget_and_missed_tranches_are_not_carried():
    cp.compute_cash_plan(_ov(100_000, 45_000), MANDATE, today=date(2026, 11, 3))
    # Im November 3.000 € investiert → Restbudget 2.000 €
    mid = cp.compute_cash_plan(_ov(100_000, 42_000), MANDATE, today=date(2026, 11, 20))
    assert mid["budget_eur"] == 2_000
    # Dezember: Soll-Überschuss Monatsende 10.000 €, Ist 17.000 € → Budget gedeckelt auf 5.000 €
    dec = cp.compute_cash_plan(_ov(100_000, 42_000), MANDATE, today=date(2026, 12, 1))
    assert dec["month"] == 2
    assert dec["budget_eur"] == 5_000
    assert dec["backlog_eur"] == 2_000


def test_plan_ends_in_band_and_restarts_after_last_month():
    cp.compute_cash_plan(_ov(100_000, 45_000), MANDATE, today=date(2026, 11, 3))
    done = cp.compute_cash_plan(_ov(100_000, 24_000), MANDATE, today=date(2026, 12, 3))
    assert not done["active"]
    assert "im Band" in cp.format_cash_plan(done)
    again = cp.compute_cash_plan(_ov(100_000, 35_000), MANDATE, today=date(2027, 1, 5))
    assert again["month"] == 1 and again["total_excess_eur"] == 10_000


def test_display_does_not_start_plan():
    cp.compute_cash_plan(_ov(100_000, 45_000), MANDATE, today=date(2026, 11, 3), persist=False)
    assert not cp.STATE_PATH.exists()


def test_below_min_blocks_buys_from_cash():
    plan = cp.compute_cash_plan(_ov(100_000, 10_000), MANDATE, today=date(2026, 11, 3))
    assert plan["below_min"]
    assert "UNTER dem Minimum" in cp.format_cash_plan(plan)


def test_policy_validation():
    assert validate_mandate_schema(MANDATE)[0]
    assert not validate_mandate_schema({"policy": {"cash": {"min": 30, "max": 20}}})[0]
    assert not validate_mandate_schema({"policy": {"deployment": {"months": 12}}})[0]
    assert not validate_mandate_schema({"policy": {"deployment": {"parking": "etf"}}})[0]


def test_mandate_block_switches_cash_wording_with_band():
    with_band = build_mandate_block(MANDATE)
    assert "CASH-BAND" in with_band and "CASH-EINSATZPLAN" in with_band
    assert "auf Krampf" not in with_band
    without = build_mandate_block({"targets": {"cash_pct": 20}})
    assert "auf Krampf" in without


def test_lint_flags_missing_cap_and_brake_text():
    assert any("Obergrenze" in h for h in lint_mandate({"targets": {"cash_pct": 20}}))
    braked = {**MANDATE, "soft_preferences": ["Eine hohe Cash-Quote ist kein Handlungsdruck"]}
    assert any("bremst" in h for h in lint_mandate(braked))
    assert lint_mandate(MANDATE) == []


def test_drift_cash_inside_band_is_ok():
    drift = compute_strategy_drift(_ov(100_000, 24_000), MANDATE)
    cash = next(d for d in drift["dimensions"] if d["kind"] == "cash")
    assert cash["severity"] == "ok" and cash["band"]["max"] == 25
    drift = compute_strategy_drift(_ov(100_000, 45_000), MANDATE)
    assert next(d for d in drift["dimensions"] if d["kind"] == "cash")["severity"] == "breach"
