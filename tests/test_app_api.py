"""Smoke-Tests für die JSON-API der iOS-App: jeder Endpoint antwortet mit den
Schlüsseln, die die App dekodiert — auch ohne Cache-Daten."""

import pytest
from fastapi.testclient import TestClient

from src.web.app import app

client = TestClient(app)


@pytest.mark.parametrize("path,keys", [
    ("/api/app/dashboard", {"overview", "indices", "snapshots", "benchmarks", "actionable", "latest_briefing", "status"}),
    ("/api/app/portfolio", {"overview", "tax_loss", "stops", "stop_labels", "open_orders", "accounts", "status"}),
    ("/api/app/market", {"indices", "macro", "calendar", "sector_heatmap", "news", "status"}),
    ("/api/app/briefings", {"briefings", "notes"}),
    ("/api/app/recommendations", {"recommendations", "actionable_count", "open_orders", "accounts", "theses"}),
    ("/api/app/strategy", {"mandate", "drift"}),
    ("/api/app/holdings", {"funds", "lookthrough", "research_running"}),
])
def test_endpoint_shape(path, keys):
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert keys <= set(r.json())


def test_briefings_newest_first():
    items = client.get("/api/app/briefings").json()["briefings"]
    dates = [b.get("date", "") for b in items]
    assert dates == sorted(dates, reverse=True)


def test_news_unescaped():
    from src.web.routes.app_api import _unescape_news
    out = _unescape_news([{"title": "V&#x27;s target", "description": "S&amp;P", "url": "x"}])
    assert out == [{"title": "V's target", "description": "S&P", "url": "x"}]


def test_nan_becomes_null():
    """Ein NaN aus yfinance darf nie wieder die ganze App-Antwort mit 500 kippen."""
    from src.web.routes.app_api import _AppJSONResponse
    body = _AppJSONResponse({"a": float("nan"), "b": [1.5, float("inf")], "c": {"d": "ö"}}).body
    assert body.decode() == '{"a":null,"b":[1.5,null],"c":{"d":"ö"}}'


def test_recommendation_gets_position_stop():
    from src.web.routes.app_api import _with_position_context
    portfolio = {"accounts": {"trade_republic": {"positions": [
        {"ticker": "AVGO", "name": "Broadcom", "shares": 2, "currency": "EUR",
         "stop_loss": 300.0, "stop_currency": "EUR"},
    ]}}}
    md = {"indices": {"EUR/USD": {"value": 1.2}}, "positions": {"AVGO": {"price": {"current_price": 400.0, "currency": "USD", "atr_14": 10.0}}}}
    recs = _with_position_context([{"ticker": "AVGO", "action": "hold", "stop_loss": 380, "status": "open"}], portfolio, md)
    rec = recs[0]
    assert rec["current_stop_broker"] == 300.0
    assert rec["current_stop_currency"] == "EUR"
    assert rec["current_stop"] == 360.0          # 300 € × 1,2 = 360 $
    assert rec["account"] == "trade_republic"
    assert rec["position_ticker"] == "AVGO"
