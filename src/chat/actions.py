"""Executor für pending_actions aus dem Web-Chat.

Führt nach User-Bestätigung die tatsächliche Mutation am Portfolio / Watchlist /
Empfehlungen durch. Nutzt existierende Funktionen aus src.delivery.telegram.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.chat import db

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def execute_pending_action(action_id: str) -> dict:
    """Führt die pending_action aus und gibt Ergebnis zurück.

    Returns: {"success": bool, "message": str, "details": dict}
    """
    action = db.get_pending_action(action_id)
    if not action:
        return {"success": False, "message": f"Action {action_id} nicht gefunden"}
    if action["status"] != "pending":
        return {"success": False, "message": f"Action bereits {action['status']}"}

    tool = action["tool_name"]
    params = action["params"] if isinstance(action["params"], dict) else {}

    try:
        if tool == "log_trade":
            result = _execute_log_trade(params)
        elif tool == "update_watchlist":
            result = _execute_update_watchlist(params)
        elif tool == "close_recommendation":
            result = _execute_close_recommendation(params)
        else:
            return {"success": False, "message": f"Unbekanntes Tool: {tool}"}

        db.resolve_pending_action(action_id, "executed", result)

        # Push bei erfolgreichem Write — Kategorie je nach Tool
        try:
            from src.delivery.push_sender import send_push_safe
            if tool == "log_trade" and not result.get("error"):
                send_push_safe(
                    category="trade_confirmed",
                    title=f"Trade geloggt: {params.get('ticker', '?')}",
                    body=str(result.get("message", "")),
                    url="/portfolio",
                    tag=f"trade-{params.get('ticker', '')}",
                    data={"via": "chat", "tool": tool, "params": params},
                )
            elif tool == "close_recommendation" and not result.get("error"):
                send_push_safe(
                    category="recommendation_closed",
                    title=f"Empfehlung {params.get('ticker', '?')} geschlossen",
                    body=str(result.get("message", "")),
                    url="/recommendations",
                    tag=f"rec-{params.get('ticker', '')}",
                )
        except Exception:
            logger.exception("Push nach execute_pending_action fehlgeschlagen")

        return {"success": True, "message": result.get("message", "Erledigt."), "details": result}

    except Exception as e:
        logger.exception("Action-Executor-Fehler für %s", action_id)
        db.resolve_pending_action(action_id, "failed", {"error": str(e)})
        return {"success": False, "message": f"Fehler: {e}"}


def reject_pending_action(action_id: str) -> dict:
    action = db.get_pending_action(action_id)
    if not action:
        return {"success": False, "message": "Nicht gefunden"}
    if action["status"] != "pending":
        return {"success": False, "message": f"Action bereits {action['status']}"}
    db.resolve_pending_action(action_id, "rejected", {"rejected_by": "user"})
    return {"success": True, "message": "Abgebrochen."}


# ── Einzelne Executor-Funktionen ─────────────────────────────

def _execute_log_trade(params: dict) -> dict:
    from src.delivery.telegram import update_portfolio_position, close_recommendation_on_trade

    action = params.get("action")
    ticker = params.get("ticker")
    shares = params.get("shares")
    price = params.get("price")

    updated = update_portfolio_position(action, ticker, shares, price)
    if not updated:
        # Fall: neue Position bei Kauf → manuell hinzufügen
        if action == "buy":
            ok, err = _add_new_position(ticker, shares, price, params.get("account"))
            if not ok and err:
                # Klarer Fehler (z.B. USD-Kauf ohne EUR/USD-Kurs) statt generisch "nicht gefunden"
                return {"message": err, "error": True}
            updated = ok
    if updated:
        try:
            close_recommendation_on_trade(ticker, action)
        except Exception as e:
            logger.warning("close_recommendation_on_trade Fehler: %s", e)
        return {
            "message": f"Trade geloggt: {action} {shares} × {ticker} @ {price}",
            "ticker": ticker, "action": action, "shares": shares, "price": price,
        }
    else:
        return {"message": f"Position {ticker} nicht gefunden (weder vorhanden noch neu angelegt).", "error": True}


def _add_new_position(ticker: str, shares: float, price: float, account: str | None) -> tuple[bool, str | None]:
    """Legt eine komplett neue Position im angegebenen Depot an. Mit File-Lock + atomic write.

    Returns (ok, error_message). buy_in_eur wird zum Kaufzeitpunkt FIXIERT (analog
    portfolio_io.add_new_position) — kein None mehr für USD-Käufe, das verfälschte
    später jede EUR-Bewertung. Bei USD-Kauf ohne gültigen EUR/USD-Kurs wird der
    Vorgang abgelehnt statt einen falschen Buy-In zu persistieren."""
    from datetime import datetime
    from src.delivery.portfolio_io import portfolio_write_lock
    from src.delivery.telegram import update_cash_on_trade
    from src.data.fx import get_eur_usd
    from src.web.services.cache_service import get_market_data

    market_data = get_market_data()

    # Echte Quote-Währung bevorzugen (positions/watchlist), sonst Heuristik.
    currency = None
    for bucket in ("positions", "watchlist"):
        entry = (market_data.get(bucket) or {}).get(ticker)
        if entry:
            currency = (entry.get("price") or {}).get("currency")
            if currency:
                break
    if not currency:
        currency = "USD" if not any(c in ticker for c in [".", "AT0"]) else "EUR"

    # buy_in_eur zum Kaufzeitpunkt fixieren.
    if currency == "EUR":
        buy_in_eur = float(price)
    else:
        eur_usd = get_eur_usd(market_data)
        if eur_usd is None:
            return False, (
                f"{currency}-Kauf von {ticker} abgelehnt: EUR/USD-Kurs nicht verfügbar — "
                "bitte Daten aktualisieren und erneut versuchen."
            )
        buy_in_eur = float(price) / eur_usd

    # Cash-Tracking läuft in EUR — bei Nicht-EUR den umgerechneten Wert nutzen.
    price_eur = float(price) if currency == "EUR" else buy_in_eur
    added = False

    with portfolio_write_lock() as portfolio:
        acc_key = account or next(iter(portfolio.get("accounts", {}).keys()), None)
        if not acc_key or acc_key not in portfolio.get("accounts", {}):
            logger.error("Konto %s nicht in portfolio.json", acc_key)
            return False, f"Konto {acc_key} nicht gefunden."

        new_pos = {
            "ticker": ticker,
            "name": ticker.split(".")[0],
            "isin": "",
            "shares": float(shares),
            "buy_in": float(price),
            "buy_in_eur": float(buy_in_eur),
            "currency": currency,
        }
        portfolio["accounts"][acc_key]["positions"].append(new_pos)
        try:
            update_cash_on_trade(portfolio, acc_key, "buy", shares, price_eur)
        except Exception as e:
            logger.warning("Cash-Update fehlgeschlagen: %s", e)
        portfolio["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        added = True

    if added:
        try:
            from src.web.services.portfolio_service import update_region_on_trade
            update_region_on_trade("buy", ticker)
        except Exception:
            pass
    return added, None


def _execute_update_watchlist(params: dict) -> dict:
    from src.delivery.telegram import update_watchlist
    update_watchlist(params.get("action"), params.get("ticker"), params.get("name"))
    return {"message": f"Watchlist aktualisiert: {params.get('action')} {params.get('ticker')}"}


def _execute_close_recommendation(params: dict) -> dict:
    ticker = params.get("ticker")
    outcome = params.get("outcome", "manuell geschlossen")
    recs_path = Path(__file__).parent.parent.parent / "memory" / "recommendations.json"
    if not recs_path.exists():
        return {"message": "Keine Empfehlungen vorhanden.", "error": True}

    with open(recs_path) as f:
        recs = json.load(f)

    # Unterstütze beide Formate: [items] oder {"recommendations": [items]}
    container = recs if isinstance(recs, list) else recs.get("recommendations", [])
    closed = 0
    for rec in container:
        if rec.get("status") != "open":
            continue
        rec_ticker = rec.get("ticker", "")
        if rec_ticker == ticker or rec_ticker.split(".")[0] == ticker or ticker.split(".")[0] == rec_ticker:
            rec["status"] = "executed"
            rec["outcome"] = outcome
            closed += 1

    if closed == 0:
        return {"message": f"Keine offene Empfehlung für {ticker} gefunden.", "error": True}

    with open(recs_path, "w") as f:
        json.dump(recs, f, indent=2, ensure_ascii=False)
    return {"message": f"{closed} Empfehlung(en) für {ticker} geschlossen ({outcome})."}
