"""JSON-API für die native iOS-App.

Ein Endpoint pro Bildschirm, jeweils mit genau den Daten, die auch die
gleichnamige HTML-Seite rendert — die App braucht so pro Ansicht nur eine
Rundreise (mobil über Tailscale spürbar). Rein lesend: Schreibaktionen
(Trades, Orders, Positionen, Chat) laufen über die bestehenden /api-Routen.

Die Seiten-Helfer liegen in src.web.app; sie werden erst im Handler
importiert, weil app.py diesen Router selbst einbindet.
"""

from __future__ import annotations

import html
import importlib

from fastapi import APIRouter

from src.web.services.portfolio_service import (
    load_portfolio,
    compute_portfolio_overview,
    compute_index_data,
)
from src.web.services.cache_service import (
    get_market_data,
    get_macro_data,
    get_news_data,
    get_calendar_data,
    get_cache_status,
    get_monthly_snapshots,
    get_briefings,
    get_recommendations,
    get_notes,
)
from src.analysis.performance import compute_benchmark_data, compute_tax_loss_data
from src.data.fx import safe_eur_usd

router = APIRouter(prefix="/api/app", tags=["app"])


def _web():
    return importlib.import_module("src.web.app")


def _status() -> dict:
    return {"cache": get_cache_status(), "refresh_running": _web()._refresh_running}


@router.get("/dashboard")
async def dashboard():
    web = _web()
    market_data = get_market_data()
    return {
        "overview": compute_portfolio_overview(load_portfolio(), market_data),
        "indices": compute_index_data(market_data),
        "snapshots": get_monthly_snapshots(),
        "benchmarks": compute_benchmark_data(market_data),
        "actionable": web._actionable_recommendations(),
        "latest_briefing": web._latest_briefing(),
        "status": _status(),
    }


@router.get("/portfolio")
async def portfolio():
    from src.analysis.orders import get_open_orders
    web = _web()
    portfolio = load_portfolio()
    market_data = get_market_data()
    user = web._load_settings().get("user", {})
    return {
        "overview": compute_portfolio_overview(portfolio, market_data),
        "snapshots": get_monthly_snapshots(),
        "benchmarks": compute_benchmark_data(market_data),
        "tax_loss": compute_tax_loss_data(portfolio, market_data) if market_data.get("positions") else None,
        "kest_mode": user.get("kest_mode", "per_account"),
        "default_currency": user.get("default_currency", "EUR"),
        "stops": web._stop_overview_safe(portfolio, market_data),
        "stop_labels": web._STOP_LABELS,
        "open_orders": get_open_orders(),
        "accounts": list(portfolio.get("accounts", {}).keys()),
        "status": _status(),
    }


def _unescape_news(items: list) -> list:
    # Brave liefert Titel/Beschreibungen HTML-escaped (&#x27; usw.)
    out = []
    for item in items or []:
        if isinstance(item, dict):
            item = {**item, **{k: html.unescape(item[k]) for k in ("title", "description")
                               if isinstance(item.get(k), str)}}
        out.append(item)
    return out


@router.get("/market")
async def market():
    market_data = get_market_data()
    news = get_news_data() or {}
    return {
        "indices": compute_index_data(market_data),
        "macro": get_macro_data(),
        "calendar": get_calendar_data(),
        "sector_heatmap": _web()._sector_heatmap(market_data),
        "news": {
            "position_news": {t: _unescape_news(n) for t, n in (news.get("position_news") or {}).items()},
            "bloomberg_headlines": _unescape_news(news.get("bloomberg_headlines")),
            "macro_news": _unescape_news(news.get("macro_news")),
            "opportunities": _unescape_news(news.get("opportunities")),
            "sentiment": news.get("sentiment") or {},
        },
        "status": _status(),
    }


@router.get("/briefings")
async def briefings():
    items = sorted(get_briefings() or [], key=lambda b: b.get("date", ""), reverse=True)
    return {"briefings": items, "notes": get_notes()}


@router.get("/recommendations")
async def recommendations():
    from src.analysis.orders import get_open_orders
    web = _web()
    md = get_market_data()
    recs = []
    for rec in get_recommendations():
        if isinstance(rec, dict):
            recs.append({**rec, "currency": web._resolve_ticker_currency(rec.get("ticker", ""), md)})
    return {
        "recommendations": recs,
        "actionable_count": len(web._actionable_recommendations()),
        "eur_usd": safe_eur_usd(md),
        "open_orders": get_open_orders(),
        "accounts": list(load_portfolio().get("accounts", {}).keys()),
        "theses": get_notes().get("position_theses", {}),
    }


@router.get("/strategy")
async def strategy():
    from src.analysis.mandate import load_mandate, compute_strategy_drift
    mandate = load_mandate()
    drift = None
    if mandate:
        overview = compute_portfolio_overview(load_portfolio(), get_market_data())
        drift = compute_strategy_drift(overview, mandate)
    return {"mandate": mandate, "drift": drift}


@router.get("/holdings")
async def holdings():
    from src.data.holdings import load_holdings_research, compute_lookthrough
    web = _web()
    portfolio = load_portfolio()
    research = load_holdings_research()
    return {
        "funds": web._lookthrough_funds(portfolio, research),
        "lookthrough": compute_lookthrough(portfolio, get_market_data(), research),
        "research_running": web._holdings_research_running,
    }
