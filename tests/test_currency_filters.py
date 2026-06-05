"""Tabellen-Tests für die Geld-/Währungs-Filter in src/web/app.py.

Diese Filter sind das Herzstück mehrerer Produktions-Regressionen:
META-560$ wurde als 560€ gerendert (USD/EUR-Verwechslung), BRK.B galt
fälschlich als EUR. Reine Pure-Functions, ideal für Tabellen-Tests.
"""

import pytest

from src.web.app import (
    _ticker_currency,
    format_price,
    format_price_alt,
)


# ---------------------------------------------------------------------------
# _ticker_currency: Ticker/ISIN -> Währungs-CODE (Heuristik)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ticker, expected",
    [
        # US-Aktien (kein Suffix) -> USD
        ("AAPL", "USD"),
        ("META", "USD"),
        # EU-Börsensuffixe -> EUR
        ("ASML.AS", "EUR"),
        ("ALV.DE", "EUR"),
        ("MC.PA", "EUR"),
        # ISIN-artige EU-Präfixe -> EUR
        ("AT0000000001", "EUR"),
        ("DE0007164600", "EUR"),
        # gepunktete US-Share-Classes -> USD (war frueher faelschlich EUR!)
        ("BRK.B", "USD"),
        ("BF.B", "USD"),
        # andere Quote-Waehrungen ueber Suffix
        ("RIO.L", "GBP"),
        ("ABBN.SW", "CHF"),
        ("SHOP.TO", "CAD"),
        # leerer Ticker -> Default USD
        ("", "USD"),
    ],
)
def test_ticker_currency(ticker, expected):
    assert _ticker_currency(ticker) == expected


# ---------------------------------------------------------------------------
# format_price: explizite currency hat Vorrang vor der Ticker-Heuristik
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, ticker, currency, expected",
    [
        # Heuristik-Pfad (currency=None)
        (100, "AAPL", None, "$100,00"),
        (100, "ASML.AS", None, "100,00€"),
        # Explizite currency gewinnt: BRK.B-Heuristik ist USD, hier auch USD -> $
        (100, "BRK.B", "USD", "$100,00"),
        # Explizite currency ueberschreibt die Heuristik komplett
        (100, "X", "GBP", "£100,00"),
        (100, "AAPL", "EUR", "100,00€"),
        (100, "ALV.DE", "USD", "$100,00"),
        # weitere Symbole
        (100, "X", "CHF", "100,00 CHF"),
        (100, "X", "CAD", "C$100,00"),
        # Deutsches Zahlenformat: Komma als Dezimaltrenner, Punkt als Tausender
        (1234.5, "AAPL", "USD", "$1.234,50"),
        (560, "META", None, "$560,00"),  # der META-560$-Regressionsfall
        # None-Wert -> Gedankenstrich
        (None, "AAPL", "USD", "–"),
    ],
)
def test_format_price(value, ticker, currency, expected):
    assert format_price(value, ticker, currency) == expected


def test_format_price_decimal_separator_is_comma():
    """Explizit: Dezimaltrenner muss ein Komma sein (deutsches Format)."""
    out = format_price(99.9, "AAPL", "USD")
    assert "," in out and out == "$99,90"


# ---------------------------------------------------------------------------
# format_price_alt: ≈-Sekundaerumrechnung nur fuer EUR<->USD
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, ticker, eur_usd, currency, expected",
    [
        # USD -> EUR-Wert (value / eur_usd)
        (120, "AAPL", 1.2, "USD", "100,00€"),
        # EUR -> USD-Wert (value * eur_usd)
        (100, "ALV.DE", 1.2, "EUR", "$120,00"),
        # GBP/CHF/CAD: kein Umrechnungskurs vorhanden -> ""
        (100, "RIO.L", 1.2, "GBP", ""),
        (100, "ABBN.SW", 1.2, "CHF", ""),
        (100, "SHOP.TO", 1.2, "CAD", ""),
        # fehlender Kurs -> ""
        (100, "AAPL", None, "USD", ""),
        (100, "AAPL", 0, "USD", ""),
        # None-Wert -> ""
        (None, "AAPL", 1.2, "USD", ""),
    ],
)
def test_format_price_alt(value, ticker, eur_usd, currency, expected):
    assert format_price_alt(value, ticker, eur_usd, currency) == expected
