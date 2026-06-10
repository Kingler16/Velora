"""Tests für den Mandats-Validator (Geld-Guardrail) + Schema + Prompt-Block."""

import pytest

from src.analysis.mandate import (
    validate_against_mandate,
    validate_mandate_schema,
    build_mandate_block,
    compute_strategy_drift,
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


def test_drift_none_without_mandate():
    assert compute_strategy_drift(_overview(), None) is None
    assert compute_strategy_drift(None, _mandate()) is None


def test_drift_detects_region_and_position_breach():
    mandate = {
        "hard_rules": [{"type": "max_position_pct", "value": 12, "rule": "block"}],
        "targets": {"regions": {"USA": 55, "Europa": 30, "Asien": 15}, "cash_pct": 8},
    }
    ov = {
        "total_value_eur": 50000.0,
        "cash_total": 5000.0,  # 10% -> Abweichung +2pp -> ok
        "region_exposure": {"USA": 40000.0, "Europa": 0.0, "Asien": 0.0},  # USA 100% -> breach
        "positions": [{"ticker": "NVDA", "name": "Nvidia", "current_value_eur": 9000.0}],  # 18% > 12% -> breach
    }
    drift = compute_strategy_drift(ov, mandate)
    assert drift["status"] == "breach"
    # USA stark über Soll -> breach; NVDA-Position über Limit -> breach
    usa = next(d for d in drift["dimensions"] if d["name"] == "USA")
    assert usa["severity"] == "breach"
    assert any(d["kind"] == "position" and d["severity"] == "breach" for d in drift["dimensions"])


def test_sector_rule_fires_despite_label_mix():
    # Regression: Positionen tragen yfinance-Englisch ("Technology"), der Breakdown
    # nach Durchschau deutschen Kanon ("Technologie") — ohne Normierung fand die
    # Regel den Ist-Wert nie (cur=0) und konnte praktisch nicht auslösen.
    ov = _overview()
    ov["positions"][0]["current_value_eur"] = 16000.0
    ov["sector_breakdown"] = {"Technologie": 16000.0}  # deutscher Kanon wie auf dem Pi
    rec = {"action": "buy", "ticker": "NVDA", "shares": 2000, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), ov)
    # (16000+2000)/(45000+2000) = 38.3% > 38 -> Sektor-Warnung (Position 18000/47000=38.3% > 12 -> block)
    assert any("Sektor Technologie" in v for v in viol)


def test_sector_rule_accepts_german_label_in_mandate():
    ov = _overview()
    ov["positions"][0]["current_value_eur"] = 16000.0
    ov["sector_breakdown"] = {"Technologie": 16000.0}
    mandate = _mandate()
    next(r for r in mandate["hard_rules"] if r["type"] == "max_sector_pct")["sector"] = "Technologie"
    rec = {"action": "buy", "ticker": "NVDA", "shares": 2000, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, mandate, ov)
    assert any("Sektor Technologie" in v for v in viol)


def test_position_limit_aggregates_multi_depot():
    # Gleicher Ticker auf zwei Depots (TR + Erste Bank): Limit muss die SUMME sehen.
    ov = _overview()
    ov["positions"] = [
        {"ticker": "AMZN", "name": "Amazon", "current_value_eur": 3000.0, "sector": "Consumer Cyclical"},
        {"ticker": "AMZN", "name": "Amazon", "current_value_eur": 3000.0, "sector": "Consumer Cyclical"},
    ]
    rec = {"action": "buy", "ticker": "AMZN", "shares": 1000, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), ov)
    # (6000+1000)/(45000+1000) = 15.2% > 12 -> block (mit Dedup-Bug wären es 8.7% -> pass)
    assert verdict == "block"
    assert any("AMZN" in v for v in viol)


def test_forbidden_instrument_word_boundaries():
    # "Hebelwirkung" im Reasoning ist operativer Leverage, kein Hebelprodukt -> pass
    ok_rec = {"action": "buy", "ticker": "SAP.DE", "shares": 1, "entry_price": 100,
              "reasoning": "Hohe Hebelwirkung des operativen Geschäfts auf die Marge"}
    verdict, _ = validate_against_mandate(ok_rec, _mandate(), _overview())
    assert verdict == "pass"
    # "Hebel-ETF" ist ein echtes Hebelprodukt -> block (Bindestrich = Wortgrenze)
    bad_rec = {"action": "buy", "ticker": "LQQ.PA", "shares": 1, "entry_price": 100,
               "reasoning": "Hebel-ETF auf den Nasdaq für mehr Schwung"}
    verdict, viol = validate_against_mandate(bad_rec, _mandate(), _overview())
    assert verdict == "block"


def test_single_trade_cap_warns():
    mandate = _mandate()
    mandate["single_trade_cap_pct"] = 8
    # 5000€ Order bei 50000€ Vermögen = 10% > 8% -> warn (nie block)
    rec = {"action": "buy", "ticker": "SAP.DE", "shares": 50, "entry_price": 100, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, mandate, _overview())
    assert verdict == "warn"
    assert any("je Trade" in v for v in viol)


def test_concentration_uses_invested_capital():
    # 50% Cash: 4000€ Position sind 8% vom Gesamtvermögen, aber 16% des Investierten.
    ov = {
        "total_value_eur": 50000.0,
        "cash_total": 25000.0,
        "eur_usd_rate": 1.0,
        "positions": [{"ticker": "NVDA", "name": "Nvidia", "current_value_eur": 4000.0, "sector": "Technology"}],
        "sector_breakdown": {"Technologie": 4000.0},
    }
    rec = {"action": "buy", "ticker": "NVDA", "shares": 100, "entry_price": 1, "reasoning": "x" * 20}
    verdict, viol = validate_against_mandate(rec, _mandate(), ov)
    # (4000+100)/(25000+100) = 16.3% > 12 -> block. Auf Gesamtbasis wären es 8.2% -> pass.
    assert verdict == "block"


def test_drift_shows_unmapped_region():
    mandate = {
        "hard_rules": [],
        "targets": {"regions": {"USA": 60, "Europa": 40}},
    }
    ov = {
        "total_value_eur": 50000.0,
        "cash_total": 0.0,
        "region_exposure": {"USA": 25000.0, "Europa": 15000.0, "Rohstoffe": 10000.0},
        "positions": [],
    }
    drift = compute_strategy_drift(ov, mandate)
    rohstoffe = next(d for d in drift["dimensions"] if d["name"] == "Rohstoffe")
    assert rohstoffe["soll"] == 0 and rohstoffe["ist"] == 20.0
    assert rohstoffe["severity"] == "breach"  # 20pp ohne Soll = sichtbarer Verstoss


def test_drift_aggregates_positions_and_respects_exceptions():
    mandate = {
        "hard_rules": [{"type": "max_position_pct", "value": 12, "rule": "block",
                        "exceptions": {"WELTKERN": "bewusst grosser Kern"}}],
        "targets": {},
    }
    ov = {
        "total_value_eur": 50000.0,
        "cash_total": 5000.0,  # invested 45000
        "positions": [
            {"ticker": "WELTKERN", "name": "Welt-Fonds", "current_value_eur": 20000.0},
            {"ticker": "AMZN", "name": "Amazon", "current_value_eur": 3500.0},
            {"ticker": "AMZN", "name": "Amazon", "current_value_eur": 3000.0},
        ],
    }
    drift = compute_strategy_drift(ov, mandate)
    names = [d["name"] for d in drift["dimensions"] if d["kind"] == "position"]
    # Welt-Kern (44% > 12) ist per Exception ausgenommen; AMZN aggregiert 6500/45000 = 14.4% > 12 -> breach
    assert not any("Welt-Fonds" in n for n in names)
    assert any("Amazon" in n for n in names)


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
