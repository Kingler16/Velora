"""Velora MCP-Server — stellt Tools für den Web-Chat bereit.

Läuft als Subprocess via stdio-Transport. Wird von Claude Code CLI gestartet
(siehe mcp_config.json).

Tools:
  - get_portfolio            (Portfolio-Übersicht)
  - get_position_detail      (einzelne Position mit Marktdaten)
  - get_live_quote           (Live-Kurs via yfinance, bypasst Cache)
  - get_macro_data           (Fed, EZB, CPI, VIX, Yield Curve, …)
  - fetch_news               (Brave Search)
  - get_briefings            (letzte N Briefings)
  - get_recommendations      (offene/geschlossene Empfehlungen)
  - get_calendar             (Earnings + Makro-Events)
  - get_watchlist            (Watchlist)
  - search_memory            (Volltext-Suche Briefings + Notes + Messages)
  - pin_memory               (Sticky-Memory anlegen)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Pfade korrekt setzen, damit src.* Imports gehen — egal von wo der Server gestartet wird
_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from mcp.server.fastmcp import FastMCP  # noqa: E402

logger = logging.getLogger("velora.mcp")

CONFIG_DIR = _BASE / "config"
MEMORY_DIR = _BASE / "memory"

mcp = FastMCP("velora")


# ── Helpers ───────────────────────────────────────────────────

def _load_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.error("Cannot load %s: %s", path, e)
        return {}


def _load_settings() -> dict:
    from src.config_loader import load_settings
    return load_settings()


def _load_portfolio() -> dict:
    return _load_json(CONFIG_DIR / "portfolio.json") or {"accounts": {}, "bank_accounts": {}}


# ── Portfolio-Tools ──────────────────────────────────────────

@mcp.tool()
def get_portfolio() -> dict:
    """Gibt die aktuelle Portfolio-Übersicht zurück: Gesamtvermögen, Top-Positionen,
    Cash, P/L, Sektor-/Region-Breakdown. Nutze dies, wenn der User nach seinem Portfolio,
    Wert, P/L, Positionen, Allocation fragt."""
    from src.web.services.portfolio_service import compute_portfolio_overview
    from src.web.services.cache_service import get_market_data

    portfolio = _load_portfolio()
    market_data = get_market_data()
    overview = compute_portfolio_overview(portfolio, market_data)

    # Minimal-Projection, um Tokens zu sparen
    positions = []
    for p in overview.get("positions", []):
        positions.append({
            "ticker": p.get("ticker"),
            "name": p.get("name"),
            "account": p.get("account"),
            "shares": p.get("shares"),
            "current_price_eur": p.get("current_price_eur"),
            "value_eur": p.get("value_eur"),
            "pnl_eur": p.get("pnl_eur"),
            "pnl_pct": p.get("pnl_pct"),
            "weight_pct": p.get("weight_pct"),
            "currency": p.get("currency"),
            "sector": p.get("sector"),
        })

    bank_accounts = []
    for name, acc in portfolio.get("bank_accounts", {}).items():
        bank_accounts.append({
            "name": name,
            "value_eur": acc.get("value"),
            "interest_pct": acc.get("interest"),
            "is_depot_cash": acc.get("is_depot_cash", False),
        })

    return {
        "total_value_eur": overview.get("total_value_eur"),
        "holdings_value_eur": overview.get("holdings_value_eur"),
        "cash_total_eur": overview.get("cash_total"),
        "total_pnl_eur": overview.get("total_pnl_eur"),
        "total_pnl_pct": overview.get("total_pnl_pct"),
        "positions": positions,
        "bank_accounts": bank_accounts,
        "region_exposure": overview.get("region_exposure"),
        "sector_breakdown": overview.get("sector_breakdown"),
        "as_of": datetime.now().isoformat(timespec="seconds"),
    }


@mcp.tool()
def get_position_detail(ticker: str) -> dict:
    """Detailansicht einer einzelnen Position: Fundamentals, Insider-Transaktionen,
    52W-High/Low, KGV, Beta, Dividende, News. Nimmt den Ticker (z.B. 'ASML.AS' oder 'AAPL')."""
    from src.web.services.cache_service import get_market_data, get_news_data
    portfolio = _load_portfolio()
    market = get_market_data() or {}
    news = get_news_data() or {}

    pos_info = None
    for account_name, account in portfolio.get("accounts", {}).items():
        for pos in account.get("positions", []):
            if (pos.get("ticker") or "").upper() == ticker.upper():
                pos_info = {**pos, "account": account_name}
                break
        if pos_info:
            break

    ticker_key = next(
        (k for k in market.get("positions", {}) if k.upper() == ticker.upper()),
        ticker,
    )
    market_entry = market.get("positions", {}).get(ticker_key, {})

    position_news = news.get("position_news", {}).get(ticker_key, [])

    return {
        "ticker": ticker_key,
        "in_portfolio": pos_info is not None,
        "position_info": pos_info,
        "price_data": market_entry.get("price"),
        "insiders": market_entry.get("insiders", []),
        "news": position_news[:8],
    }


@mcp.tool()
def get_live_quote(ticker: str) -> dict:
    """Live-Kurs für einen Ticker via yfinance (bypasst Cache, holt frisch).
    Nutze dies, wenn der User den aktuellen Kurs wissen will oder die Cache-Daten
    möglicherweise veraltet sind (älter als 10 Minuten)."""
    from src.data.market import fetch_price_data
    data = fetch_price_data(ticker)
    if not data:
        return {"ticker": ticker, "error": "Keine Daten gefunden"}
    return {
        "ticker": ticker,
        "current_price": data.get("current_price"),
        "change_pct": data.get("change_pct"),
        "currency": data.get("currency"),
        "52w_high": data.get("52w_high"),
        "52w_low": data.get("52w_low"),
        "pe_ratio": data.get("pe_ratio"),
        "forward_pe": data.get("forward_pe"),
        "dividend_yield": data.get("dividend_yield"),
        "beta": data.get("beta"),
        "sector": data.get("sector"),
        "source": data.get("source"),
        "timestamp": data.get("timestamp"),
    }


# ── Makro / Markt ────────────────────────────────────────────

@mcp.tool()
def get_macro_data() -> dict:
    """Aktuelle Makro-Daten: Fed Funds Rate, EZB-Zins, CPI, HICP, Yield Curve,
    Credit Spreads, VIX, Fear & Greed. Aus Cache."""
    from src.web.services.cache_service import get_macro_data as _gmd
    return _gmd()


@mcp.tool()
def get_indices() -> dict:
    """Aktuelle Index-Stände: S&P 500, NASDAQ, DAX, ATX, Euro Stoxx 50, Gold, VIX, EUR/USD, BTC/USD."""
    from src.web.services.cache_service import get_market_data
    return (get_market_data() or {}).get("indices", {})


@mcp.tool()
def get_calendar(days_ahead: int = 30) -> dict:
    """Earnings-Kalender und Makro-Events der nächsten N Tage."""
    from src.web.services.cache_service import get_calendar_data
    data = get_calendar_data() or {}
    return {
        "earnings": data.get("earnings", [])[:20],
        "macro_events": data.get("macro_events", [])[:20],
        "days_ahead": days_ahead,
    }


# ── News ─────────────────────────────────────────────────────

@mcp.tool()
def fetch_news(query: str, count: int = 5, freshness: str = "pw") -> list[dict]:
    """Sucht aktuelle News via Brave Search.
    freshness: 'pd'=letzter Tag, 'pw'=letzte Woche, 'pm'=letzter Monat, 'py'=letztes Jahr."""
    from src.data.news import search_brave
    settings = _load_settings()
    api_key = settings.get("brave_search", {}).get("api_key", "")
    if not api_key:
        return [{"error": "Brave Search API Key nicht konfiguriert"}]
    return search_brave(query, api_key, count=count, freshness=freshness)


# ── Briefings / Empfehlungen ─────────────────────────────────

@mcp.tool()
def get_briefings(limit: int = 5) -> list[dict]:
    """Gibt die letzten N Briefing-Zusammenfassungen zurück (Datum, Summary, Markt-Regime)."""
    briefings = _load_json(MEMORY_DIR / "briefings.json") or []
    if not isinstance(briefings, list):
        return []
    # Neueste zuerst
    sorted_b = sorted(briefings, key=lambda b: b.get("date", ""), reverse=True)
    return [{
        "date": b.get("date"),
        "summary": b.get("summary"),
        "market_regime": b.get("market_regime"),
        "recommendation_count": b.get("recommendation_count"),
        "had_actions": b.get("had_actions"),
    } for b in sorted_b[:limit]]


@mcp.tool()
def get_briefing_full(date_prefix: str) -> dict:
    """Volltext eines spezifischen Briefings. date_prefix ist YYYY-MM-DD (erster Treffer wird zurückgegeben)."""
    briefings = _load_json(MEMORY_DIR / "briefings.json") or []
    if not isinstance(briefings, list):
        return {"error": "Keine Briefings"}
    for b in briefings:
        if (b.get("date") or "").startswith(date_prefix):
            return {
                "date": b.get("date"),
                "summary": b.get("summary"),
                "full_text": b.get("full_text"),
                "market_regime": b.get("market_regime"),
            }
    return {"error": f"Kein Briefing mit Datum {date_prefix} gefunden"}


@mcp.tool()
def get_recommendations(status: str = "open") -> list[dict]:
    """Gibt Empfehlungen zurück. status: 'open', 'closed' oder 'all'."""
    data = _load_json(MEMORY_DIR / "recommendations.json") or []
    if isinstance(data, dict):
        data = data.get("recommendations", [])
    if not isinstance(data, list):
        return []
    if status != "all":
        data = [r for r in data if (r.get("status") or "open") == status]
    return data[:30]


@mcp.tool()
def get_watchlist() -> dict:
    """Gibt die Watchlist zurück."""
    return _load_json(CONFIG_DIR / "watchlist.json") or {}


# ── Memory-Tools ─────────────────────────────────────────────

@mcp.tool()
def search_memory(query: str, limit: int = 10) -> list[dict]:
    """Volltext-Suche über Briefings, Notes, vergangene Chat-Nachrichten.
    Nutze dies wenn der User nach früheren Diskussionen, Empfehlungen oder Insights fragt
    die in diesem Thread nicht mehr im Kontext sind."""
    from src.chat import db as chat_db
    q = query.lower().strip()
    if not q:
        return []

    results: list[dict] = []

    # Briefings
    briefings = _load_json(MEMORY_DIR / "briefings.json") or []
    if isinstance(briefings, list):
        for b in briefings:
            hay = (b.get("summary") or "") + "\n" + (b.get("full_text") or "")
            if q in hay.lower():
                results.append({
                    "source": "briefing",
                    "date": b.get("date"),
                    "excerpt": (b.get("summary") or "")[:300],
                })

    # Notes (market_regime, key_insights, theses)
    notes = _load_json(MEMORY_DIR / "notes.json") or {}
    if isinstance(notes, dict):
        insights = notes.get("key_insights") or []
        if isinstance(insights, list):
            for ins in insights:
                val = ins.get("value") if isinstance(ins, dict) else str(ins)
                if q in (val or "").lower():
                    results.append({
                        "source": "note.key_insight",
                        "date": ins.get("updated") if isinstance(ins, dict) else None,
                        "excerpt": val,
                    })
        theses = notes.get("position_theses") or {}
        if isinstance(theses, dict):
            for ticker, thesis in theses.items():
                val = thesis.get("thesis") if isinstance(thesis, dict) else str(thesis)
                if q in (ticker.lower() + " " + (val or "").lower()):
                    results.append({
                        "source": "note.thesis",
                        "ticker": ticker,
                        "excerpt": (val or "")[:300],
                    })

    # Chat-Messages (über alle Threads)
    try:
        import sqlite3
        conn = sqlite3.connect(chat_db.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT m.thread_id, m.role, m.content, m.created_at, t.title
               FROM messages m JOIN threads t ON t.id = m.thread_id
               WHERE m.role IN ('user','assistant') AND lower(m.content) LIKE ?
               ORDER BY m.created_at DESC LIMIT ?""",
            (f"%{q}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "source": "chat",
                "thread_title": r["title"],
                "role": r["role"],
                "date": r["created_at"],
                "excerpt": r["content"][:300],
            })
        conn.close()
    except Exception as e:
        logger.warning("Chat-Memory-Search Fehler: %s", e)

    return results[:limit]


@mcp.tool()
def pin_memory(key: str, value: str, scope: str = "global") -> dict:
    """Legt eine Sticky-Memory an, die in allen zukünftigen Chats im Kontext bleibt.
    scope: 'global' (alle Threads) oder 'thread' (nur aktueller Thread — derzeit global).
    Nutze dies sparsam, nur für wichtige persistente Fakten (z.B. User-Präferenzen,
    langfristige Investment-Regeln)."""
    from src.chat import db as chat_db
    pid = chat_db.add_pinned_memory(key=key, value=value, thread_id=None, pinned_by="assistant")
    return {"pinned_id": pid, "key": key, "value": value, "scope": "global"}


# ── Write-Tools (legen pending_actions an — User bestätigt in UI) ─

@mcp.tool()
def log_trade(action: str, ticker: str, shares: float, price: float, account: str) -> dict:
    """Legt einen Trade (Kauf/Verkauf) in die Bestätigungs-Queue. Der User sieht einen
    Dialog im Web-UI und muss manuell bestätigen — erst dann wird portfolio.json aktualisiert.
    Gib dem User im Chat bescheid dass er in der UI bestätigen muss.

    Parameter:
      action: 'buy' oder 'sell'
      ticker: z.B. 'NVDA' oder 'ASML.AS'
      shares: Stückzahl
      price: Preis pro Stück (in der Währung der Position, typisch EUR oder USD)
      account: Konto-Key aus config/portfolio.json (z.B. 'trade_republic', 'erste_bank')
    """
    from src.chat import db as chat_db
    if action not in ("buy", "sell"):
        return {"error": "action muss 'buy' oder 'sell' sein"}
    params = {"action": action, "ticker": ticker.upper(), "shares": float(shares),
              "price": float(price), "account": account}
    summary = f"{'Kauf' if action == 'buy' else 'Verkauf'} {shares} × {ticker.upper()} @ {price} auf {account}"
    action_id = chat_db.create_pending_action(
        tool_name="log_trade", params=params, summary=summary, thread_id=None,
    )
    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "summary": summary,
        "message": "Der Trade wurde in die Bestätigungs-Queue gelegt. "
                   "Der User muss in der Web-UI manuell bestätigen — erst dann wird "
                   "portfolio.json aktualisiert. Sag dem User Bescheid.",
    }


@mcp.tool()
def update_watchlist(action: str, ticker: str, name: Optional[str] = None) -> dict:
    """Fügt einen Ticker zur Watchlist hinzu oder entfernt ihn. Legt eine Confirmation an.

    Parameter:
      action: 'add' oder 'remove'
      ticker: z.B. 'RKLB'
      name: optional, Firmenname (nur bei 'add')
    """
    from src.chat import db as chat_db
    if action not in ("add", "remove"):
        return {"error": "action muss 'add' oder 'remove' sein"}
    params = {"action": action, "ticker": ticker.upper(), "name": name}
    verb = "Hinzufügen zu" if action == "add" else "Entfernen von"
    summary = f"{verb} Watchlist: {ticker.upper()}"
    action_id = chat_db.create_pending_action(
        tool_name="update_watchlist", params=params, summary=summary, thread_id=None,
    )
    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "summary": summary,
        "message": "Watchlist-Änderung wartet auf User-Bestätigung in der UI.",
    }


@mcp.tool()
def close_recommendation(ticker: str, outcome: str) -> dict:
    """Schließt eine offene Empfehlung für einen Ticker und markiert sie als erledigt.

    Parameter:
      ticker: der Ticker, dessen offene Empfehlung geschlossen werden soll
      outcome: kurzer Freitext ('ausgeführt', 'verworfen', 'Stop ausgelöst', 'Ziel erreicht', ...)
    """
    from src.chat import db as chat_db
    params = {"ticker": ticker.upper(), "outcome": outcome}
    summary = f"Empfehlung schließen: {ticker.upper()} → {outcome}"
    action_id = chat_db.create_pending_action(
        tool_name="close_recommendation", params=params, summary=summary, thread_id=None,
    )
    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "summary": summary,
        "message": "Empfehlungs-Schließung wartet auf User-Bestätigung in der UI.",
    }


@mcp.tool()
def propose_mandate(mandate_json: str, change_summary: str) -> dict:
    """Schlägt eine NEUE/aktualisierte Anlage-Strategie ("Mein Mandat") vor. Der User
    bestätigt im Web-UI — erst dann wird config/mandate.json geschrieben. Schreibe NIE direkt.

    So arbeitest du: interviewe den User zu seiner Strategie (Ziel, Horizont, Risiko,
    Tabus, max Einzelposition, Cash-Minimum, Soll-Allokation), formuliere den Vorschlag
    in Prosa. Wenn er zustimmt, ruf dieses Tool mit dem KOMPLETTEN neuen Mandat-JSON auf.

    Parameter:
      mandate_json: vollständiges Mandat als JSON-String. Felder: summary_human, philosophy,
        soft_preferences[], tax_directives[], objective{horizon_years,primary_goal,
        monthly_contribution_eur}, targets{regions{},cash_pct}, hard_rules[{id,type,...,
        rule:"block"|"warn"}]. Erlaubte rule-types: max_position_pct (value), forbidden_instrument
        (match[]), forbidden_ticker (tickers[]), min_cash_pct (value), max_keyword_pct
        (keywords[],value), max_sector_pct (sector,value). Wenn der User nur Teile ändert:
        hol das aktuelle Mandat (get_strategy_drift bzw. lies es dem User vor) und übergib das
        VOLLSTÄNDIGE neue Objekt — das alte wird komplett ersetzt.
      change_summary: kurze Beschreibung der Änderung (z.B. "Cash-Minimum 8→10%, NVDA gesperrt").
    """
    from src.chat import db as chat_db
    from src.analysis.mandate import validate_mandate_schema
    try:
        mandate = json.loads(mandate_json)
    except json.JSONDecodeError as e:
        return {"error": f"mandate_json ist kein gültiges JSON: {e}"}
    ok, err = validate_mandate_schema(mandate)
    if not ok:
        return {"error": f"Mandat ungültig: {err}. Korrigiere und ruf das Tool erneut auf."}
    summary = change_summary or "Mandat aktualisiert"
    action_id = chat_db.create_pending_action(
        tool_name="propose_mandate",
        params={"mandate": mandate, "change_summary": summary},
        summary=f"Strategie ändern: {summary}", thread_id=None,
    )
    return {
        "status": "pending_confirmation", "action_id": action_id, "summary": summary,
        "message": "Der Strategie-Vorschlag wartet auf Bestätigung in der UI. Sag dem User Bescheid.",
    }


@mcp.tool()
def get_strategy_drift() -> dict:
    """Aktuelle Soll-vs-Ist-Abweichung des Portfolios vom Mandat (Strategie-Drift).
    Nutze dies, wenn der User fragt, ob/wie sein Portfolio von seiner Strategie abweicht,
    oder bevor du Mandats-Änderungen vorschlägst (um die aktuelle Lage zu kennen)."""
    from src.analysis.mandate import load_mandate, compute_strategy_drift
    from src.web.services.portfolio_service import compute_portfolio_overview
    from src.web.services.cache_service import get_market_data
    mandate = load_mandate()
    if not mandate:
        return {"error": "Kein Mandat definiert (config/mandate.json fehlt)."}
    overview = compute_portfolio_overview(_load_portfolio(), get_market_data())
    drift = compute_strategy_drift(overview, mandate)
    return drift or {"error": "Drift nicht berechenbar"}


# ── Entry-Point ──────────────────────────────────────────────

def main() -> None:
    """Startet den MCP-Server via stdio-Transport."""
    mcp.run()


if __name__ == "__main__":
    main()
