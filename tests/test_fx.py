"""Tabellen-Tests für die validierte EUR/USD-Umrechnung in src/data/fx.py."""

import pytest

from src.data.fx import get_eur_usd, safe_eur_usd


def _md(value):
    """Baut ein market_data-Dict mit dem gegebenen EUR/USD-value."""
    return {"indices": {"EUR/USD": {"value": value}}}


# ---------------------------------------------------------------------------
# get_eur_usd: gibt float im Korridor (0.7, 1.5) zurueck — sonst None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "market_data, expected",
    [
        # gueltige Kurse
        (_md(1.08), 1.08),
        (_md("1.10"), 1.10),       # numerischer String wird gecastet
        (_md(0.7001), 0.7001),     # knapp innerhalb des Korridors
        (_md(1.4999), 1.4999),
        # market_data komplett fehlt
        (None, None),
        ({}, None),
        # indices fehlt
        ({"foo": "bar"}, None),
        # EUR/USD-Key fehlt
        ({"indices": {}}, None),
        ({"indices": {"S&P 500": {"value": 5000}}}, None),
        # value-Key fehlt
        ({"indices": {"EUR/USD": {}}}, None),
        # value ist None
        (_md(None), None),
        # unplausibel (ausserhalb 0.7..1.5)
        (_md(0.3), None),
        (_md(3.0), None),
        (_md(0.7), None),          # Grenze ist exklusiv (>)
        (_md(1.5), None),          # Grenze ist exklusiv (<)
        # nicht-numerisch
        (_md("abc"), None),
        (_md([1.08]), None),
    ],
)
def test_get_eur_usd(market_data, expected):
    assert get_eur_usd(market_data) == expected


# ---------------------------------------------------------------------------
# safe_eur_usd: wie get_eur_usd, aber None -> default (1.0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "market_data, expected",
    [
        (_md(1.08), 1.08),         # gueltig -> durchgereicht
        (None, 1.0),               # fehlt -> default
        (_md(None), 1.0),          # value None -> default
        (_md(3.0), 1.0),           # unplausibel -> default
        (_md("abc"), 1.0),         # nicht-numerisch -> default
    ],
)
def test_safe_eur_usd_default(market_data, expected):
    assert safe_eur_usd(market_data) == expected


def test_safe_eur_usd_custom_default():
    """Eigener default wird bei ungueltigem Kurs zurueckgegeben."""
    assert safe_eur_usd(None, default=0.9) == 0.9
    assert safe_eur_usd(_md(1.08), default=0.9) == 1.08
