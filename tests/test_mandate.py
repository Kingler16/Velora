"""Tests für den Mandats-Validator (Geld-Guardrail) + Schema + Prompt-Block."""

import pytest

from src.analysis.mandate import (
    validate_against_mandate,
    validate_mandate_schema,
    build_mandate_block,
)


def _overview():
    """Mini-Overview: 50.000€ gesamt, NVDA 5.000€ (Technology), 5.000€ Cash (10%)."""
    return {
        "total_value_eur": 50000.0,
        "cash_total": 5000.0,
        "eur_usd_rate": 1.0,  # 1:1 für einfache Handrechnung
        "positions": [
            {"ticker": "NVDA", "name": "Nvidia", "current_value_eur": 5000.0, "sector": "Technology"},
        ],
        "sector_breakdown": {"Technology": 5000.0},
    }


def _mandate():
    return {
        "version": 1,
        "hard_rules": [
            {"id": "max_single_stock", "type": "max_position_pct", "value": 12, "rule": "block"},
            {"id": "no_leverage", "type": "forbidden_instrument",
             "match": ["hebel", "leverage", "3x", "cfd", "option"], "rule": "block"},
            {"id": "ticker_ban", "type": "forbidden_ticker", "tickers": ["GME", "AMC"], "rule": "block"},
            {"id": "min_cash", "type": "min_cash_pct", "value": 8, "rule": "warn"},
            {"id": "max_tech", "type": "max_sector_pct", "sector": "Technology", "value": 38, "rule": "warn"},
        ],
    }


def test_block_max_position():
    # NVDA 5000€ + Kauf 2000€ = 7000/50000 = 14% > 12% -> block
    rec = {"action": "buy", "ticker": "NVDA", "shares": 2000, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "block"
    assert any("Einzelposition" in v for v in viol)


def test_pass_compliant_buy():
    # Kleiner EUR-Kauf 500€: Position 1% (<12), Cash 4500/50000=9% (>8), Sektor unbekannt -> pass
    rec = {"action": "buy", "ticker": "SAP.DE", "shares": 5, "entry_price": 100, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "pass", viol


def test_sell_always_passes_even_if_over_limit():
    rec = {"action": "sell", "ticker": "NVDA", "shares": 9999, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "pass"


def test_block_forbidden_instrument():
    rec = {"action": "buy", "ticker": "TQQQ", "shares": 1, "entry_price": 10,
           "reasoning": "3x leverage long nasdaq etp"}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "block"
    assert any("Instrument" in v for v in viol)


def test_block_forbidden_ticker():
    rec = {"action": "buy", "ticker": "GME", "shares": 1, "entry_price": 10, "reasoning": "meme " * 5}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "block"
    assert any("gesperrt" in v for v in viol)


def test_warn_min_cash():
    # Kauf 2000€ EUR-Ticker: Position 4% (<12, kein Block), aber Cash 5000->3000 = 6% < 8% -> warn
    rec = {"action": "buy", "ticker": "SAP.DE", "shares": 20, "entry_price": 100, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "warn"
    assert any("Cash" in v for v in viol)


def test_no_mandate_passes():
    rec = {"action": "buy", "ticker": "GME", "shares": 1, "entry_price": 10, "reasoning": "x" * 20}
    assert validate_against_mandate(rec, None, _overview()) == ("pass", [])


def test_missing_size_not_blocked():
    # Ohne shares ist die Positionsgrösse nicht berechenbar -> nicht fälschlich blocken
    rec = {"action": "buy", "ticker": "NVDA", "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), _overview())
    assert verdict == "pass"


def test_schema_rejects_unknown_rule_type():
    ok, err = validate_mandate_schema({"hard_rules": [{"type": "frobnicate", "rule": "block"}]})
    assert not ok and "Unbekannt" in err


def test_schema_rejects_bad_rule_keyword():
    ok, err = validate_mandate_schema({"hard_rules": [{"type": "min_cash_pct", "value": 8, "rule": "maybe"}]})
    assert not ok


def test_schema_accepts_valid():
    ok, err = validate_mandate_schema(_mandate())
    assert ok and err == ""


def test_build_block_empty_for_none():
    assert build_mandate_block(None) == ""


def test_build_block_contains_rules():
    block = build_mandate_block({
        "version": 3,
        "summary_human": "Langfristig wachsen.",
        "hard_rules": _mandate()["hard_rules"],
        "targets": {"regions": {"USA": 55}, "cash_pct": 8},
    })
    assert "§0" in block and "v3" in block
    assert "HARTE REGELN" in block and "WEICHE REGELN" in block
    assert "Langfristig wachsen." in block
