"""Tests für Look-Through/Durchschau (Fonds-Erkennung + Exposure-Zerlegung)."""
from src.data.holdings import needs_lookthrough, compute_lookthrough


def test_needs_lookthrough_detects_funds():
    assert needs_lookthrough("iShares Core MSCI World UCITS ETF", "EUNL.DE", "IE00B4L5Y983")
    assert needs_lookthrough("ERSTE RESPONSIBLE STOCK GLOBAL", "AT0000646799", "AT0000646799")  # ticker==isin
    assert needs_lookthrough("ERSTE LAUFZEITFONDS 2028 IV", "AT0000A36795", "AT0000A36795")
    assert needs_lookthrough("Invesco Physical Gold ETC", "8PSG.DE", "IE00B579F325")


def test_needs_lookthrough_skips_single_stocks():
    assert not needs_lookthrough("Apple", "AAPL", "US0378331005")
    assert not needs_lookthrough("Allianz", "ALV.DE", "DE0008404005")


def test_lookthrough_decomposes_fund_into_titles():
    portfolio = {"accounts": {"d": {"positions": [
        {"name": "Welt ETF", "isin": "IE0001", "ticker": "IE0001", "shares": 10, "currency": "EUR", "buy_in_eur": 100},
        {"name": "Apple", "isin": "US1", "ticker": "AAPL", "shares": 10, "currency": "EUR", "buy_in_eur": 50},
    ]}}, "bank_accounts": {}}
    research = {"IE0001": {"asset_class": "equity",
                           "top_holdings": [{"name": "Apple", "weight_pct": 30}, {"name": "Microsoft", "weight_pct": 20}]}}
    lt = compute_lookthrough(portfolio, {}, research)
    titles = {t["name"]: t["value_eur"] for t in lt["top_titles"]}
    # Fonds 1000€: Apple 30%=300 + 500 direkt = 800; Microsoft 200; Rest 50%=500
    assert round(titles["Apple"]) == 800
    assert round(titles["Microsoft"]) == 200
    assert lt["researched_funds"] == 1


def test_lookthrough_asset_classes_and_cash():
    portfolio = {"accounts": {"d": {"positions": [
        {"name": "Apple", "isin": "US1", "ticker": "AAPL", "shares": 10, "currency": "EUR", "buy_in_eur": 100},
    ]}}, "bank_accounts": {"giro": {"value": 1000}}}
    lt = compute_lookthrough(portfolio, {}, {})
    ac = {a["name"]: a["pct"] for a in lt["asset_class"]}
    assert ac["equity"] == 50.0 and ac["cash"] == 50.0  # 1000 Aktie / 1000 Cash
