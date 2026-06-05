"""Tests für compute_portfolio_overview in src/web/services/portfolio_service.py.

Assertions gegen HAND-berechnete Werte. Mini-Portfolio mit:
  - 1x EUR-Aktie (live price vorhanden)
  - 1x USD-Aktie (live price vorhanden, FX-Umrechnung)
  - 1x Bankkonto
Plus separater Fallback-Test: Ticker fehlt in market_data -> Einstand, P/L=0.
"""

from src.web.services.portfolio_service import compute_portfolio_overview


EUR_USD = 1.2


def _market_data(include_aapl=True):
    """market_data mit festem EUR/USD-Kurs und optionalen Live-Preisen."""
    positions = {
        "ALV.DE": {"price": {"current_price": 300.0}},  # EUR-Aktie, +50/Stk
    }
    if include_aapl:
        # USD-Aktie: aktueller Kurs 120 USD -> 100 EUR bei eur_usd=1.2
        positions["AAPL"] = {"price": {"current_price": 120.0}}
    return {
        "indices": {"EUR/USD": {"value": EUR_USD}},
        "positions": positions,
    }


def _portfolio():
    return {
        "accounts": {
            "scalable": {
                "positions": [
                    {
                        # EUR-Aktie: buy_in_eur fehlt, currency EUR -> buy_in_eur = buy_in
                        "ticker": "ALV.DE",
                        "name": "Allianz",
                        "shares": 10,
                        "buy_in": 250.0,
                        "currency": "EUR",
                    },
                    {
                        # USD-Aktie mit gespeichertem historischem buy_in_eur=90
                        "ticker": "AAPL",
                        "name": "Apple",
                        "shares": 5,
                        "buy_in": 100.0,
                        "buy_in_eur": 90.0,
                        "currency": "USD",
                    },
                ]
            }
        },
        "bank_accounts": {
            "Tagesgeld": {"value": 1000.0, "bank": "Erste", "is_depot_cash": False},
        },
    }


def test_portfolio_totals_with_live_prices():
    ov = compute_portfolio_overview(_portfolio(), _market_data(include_aapl=True))

    # ---- Handrechnung ----
    # ALV.DE: invested = 10 * 250 = 2500; value = 10 * 300 = 3000; pnl = +500
    # AAPL:   invested = 5 * 90  = 450 ; price_eur = 120/1.2 = 100;
    #         value = 5 * 100 = 500; pnl = +50
    # holdings = 3000 + 500 = 3500
    # cash = 1000
    # total_value = 3500 + 1000 = 4500
    # total_invested = 2500 + 450 = 2950
    # total_pnl = total_value - invested - cash = 4500 - 2950 - 1000 = 550
    assert ov["holdings_value_eur"] == 3500.0
    assert ov["cash_total"] == 1000.0
    assert ov["total_value_eur"] == 4500.0
    assert ov["total_invested_eur"] == 2950.0
    assert ov["total_pnl_eur"] == 550.0
    assert ov["position_count"] == 2
    assert ov["eur_usd_rate"] == EUR_USD

    # Pro-Position-Werte (Positionen sind nach Wert absteigend sortiert -> ALV.DE zuerst)
    by_ticker = {p["ticker"]: p for p in ov["positions"]}
    assert by_ticker["ALV.DE"]["current_value_eur"] == 3000.0
    assert by_ticker["ALV.DE"]["pnl_eur"] == 500.0
    assert by_ticker["ALV.DE"]["has_live_price"] is True
    assert by_ticker["AAPL"]["current_price_eur"] == 100.0
    assert by_ticker["AAPL"]["current_value_eur"] == 500.0
    assert by_ticker["AAPL"]["pnl_eur"] == 50.0
    assert by_ticker["AAPL"]["has_live_price"] is True


def test_portfolio_fallback_no_live_price():
    """AAPL fehlt in market_data['positions'] -> Wert = Einstand, P/L = 0."""
    ov = compute_portfolio_overview(_portfolio(), _market_data(include_aapl=False))

    by_ticker = {p["ticker"]: p for p in ov["positions"]}
    aapl = by_ticker["AAPL"]
    assert aapl["has_live_price"] is False
    # Fallback: current_value = invested = 5 * 90 = 450, pnl = 0
    assert aapl["invested_eur"] == 450.0
    assert aapl["current_value_eur"] == 450.0
    assert aapl["pnl_eur"] == 0.0
    assert aapl["pnl_pct"] == 0.0
    assert aapl["current_price_eur"] == aapl["buy_in_eur"] == 90.0

    # ALV.DE hat weiter Live-Preis -> Gesamtwerte:
    # holdings = ALV value (3000) + AAPL fallback value (450) = 3450
    # total = 3450 + 1000 cash = 4450
    # invested = 2500 + 450 = 2950
    # total_pnl = 4450 - 2950 - 1000 = 500 (nur ALV-Gewinn)
    assert ov["holdings_value_eur"] == 3450.0
    assert ov["total_value_eur"] == 4450.0
    assert ov["total_invested_eur"] == 2950.0
    assert ov["total_pnl_eur"] == 500.0
