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
