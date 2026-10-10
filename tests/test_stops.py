"""Stop-Übersicht: Stops in Broker-Währung (EUR-Stop auf US-Aktie bei Trade Republic)."""

from src.analysis.stops import compute_stop_overview, format_stop_overview

MD = {"indices": {"EUR/USD": {"value": 1.25}}, "positions": {
    "AVGO": {"price": {"current_price": 400.0, "currency": "USD", "atr_14": 10.0}},
    "NVDA": {"price": {"current_price": 250.0, "currency": "USD", "atr_14": 8.0}},
}}


def _overview(**pos_fields):
    portfolio = {"accounts": {"tr": {"positions": [
        {"ticker": "AVGO", "name": "Broadcom", "shares": 5, "currency": "EUR", **pos_fields},
    ]}}}
    return compute_stop_overview(portfolio, MD)["positions"][0]


def test_eur_stop_is_converted_to_quote_currency():
    p = _overview(stop_loss=304.0, stop_currency="EUR")
    assert p["ist_stop_broker"] == 304.0
    assert p["stop_currency"] == "EUR"
    assert p["ist_stop"] == 380.0                # 304 € × 1,25
    assert p["status"] == "ok"                   # 2×ATR unter Kurs
    assert p["ist_stop_eur"] == 304.0
    assert p["current_price_eur"] == 320.0


def test_stop_without_currency_means_quote_currency():
    p = _overview(stop_loss=380.0)
    assert p["ist_stop"] == 380.0
    assert p["stop_currency"] == "USD"


def test_eur_stop_read_as_dollar_would_be_wrong():
    # Ohne Währungsfeld hiesse 304 "304 $" → viel zu weit weg; mit EUR stimmt der Abstand.
    assert _overview(stop_loss=304.0)["status"] == "zu_weit"
    assert _overview(stop_loss=304.0, stop_currency="EUR")["status"] == "ok"


def test_prompt_mentions_broker_value():
    portfolio = {"accounts": {"tr": {"positions": [
        {"ticker": "AVGO", "name": "Broadcom", "shares": 5, "stop_loss": 304.0, "stop_currency": "EUR"},
    ]}}}
    text = format_stop_overview(compute_stop_overview(portfolio, MD))
    assert "beim Broker als 304.0 EUR" in text
