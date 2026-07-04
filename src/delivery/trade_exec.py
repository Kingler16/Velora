"""Gemeinsamer Trade-Ausführungspfad.

Kapselt die Portfolio-Schreiblogik, die früher inline im /api/trade-Endpoint lag,
damit sowohl der Web-Endpoint als auch das Order-Fill (src.analysis.orders.fill_order)
exakt denselben Weg nehmen: USD→EUR-Konvertierung, bestehende-vs-neue Position,
Cash-Update, Trade-Gedächtnis, Empfehlungs-Abschluss, Region-Update.

Rückgabe immer ein Dict: {"ok": bool, "message"|"error": str, "status_code": int, ...}.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def book_trade(action, ticker, account, shares, price, trade_currency="EUR",
               *, close_rec=True, push=True) -> dict:
    """Bucht einen Kauf/Verkauf ins Portfolio. `price` = Preis pro Stück in `trade_currency`.

    close_rec: offene Empfehlung zum Ticker automatisch auf 'executed' setzen.
    push:      Push-Benachrichtigung senden.
    """
    from src.delivery.telegram import update_portfolio_position, close_recommendation_on_trade
    from src.delivery.portfolio_io import load_portfolio

    action = (action or "").strip().lower()
    ticker = (ticker or "").strip().upper()
    trade_currency = (trade_currency or "EUR").upper()

    try:
        shares = float(shares)
        price = float(price)
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares und price müssen Zahlen sein", "status_code": 400}

    if action not in ("buy", "sell"):
        return {"ok": False, "error": "action muss 'buy' oder 'sell' sein", "status_code": 400}
    if not ticker:
        return {"ok": False, "error": "Ticker fehlt", "status_code": 400}
    if shares <= 0 or price <= 0:
        return {"ok": False, "error": "shares und price müssen > 0 sein", "status_code": 400}

    # USD → EUR umrechnen für buy_in_eur und Cash-Tracking. Bei fehlendem/unplausiblem
    # EUR/USD-Kurs den USD-Trade ABLEHNEN statt 1:1 falsch als EUR zu verbuchen.
    price_eur = price
    if trade_currency == "USD":
        from src.web.services.cache_service import get_market_data
        from src.data.fx import get_eur_usd
        eur_usd = get_eur_usd(get_market_data())
        if eur_usd is None:
            return {"ok": False,
                    "error": "EUR/USD-Kurs nicht verfügbar — USD-Trade abgelehnt, bitte Daten aktualisieren",
                    "status_code": 400}
        price_eur = price / eur_usd

    portfolio = load_portfolio()
    if account not in portfolio.get("accounts", {}):
        return {"ok": False, "error": f"Account '{account}' nicht gefunden", "status_code": 404}

    currency_sym = '€' if trade_currency == 'EUR' else '$'

    # 1) Bestehende Position aktualisieren (macht Cash + Trade-Gedächtnis + Region intern)
    success = update_portfolio_position(action, ticker, shares, price_eur)
    if success:
        if close_rec:
            close_recommendation_on_trade(ticker, action)
        if push:
            _push_trade(action, ticker, shares, price, account, currency_sym, new_position=False)
        verb = 'gekauft' if action == 'buy' else 'verkauft'
        return {"ok": True, "message": f"{shares}x {ticker} {verb} @ {price}{currency_sym}",
                "status_code": 200, "new_position": False}

    # 2) Nicht gefunden → bei Kauf neue Position anlegen
    if action == "buy":
        from src.delivery.portfolio_io import add_new_position
        from src.data.market import fetch_price_data
        # Ticker gegen yfinance validieren — None = ungültiger Ticker (Tippfehler).
        price_data = fetch_price_data(ticker)
        if price_data is None:
            return {"ok": False,
                    "error": f"Ticker '{ticker}' nicht gefunden — Tippfehler? Keine Position angelegt",
                    "status_code": 404}
        pos_currency = price_data.get("currency") or trade_currency
        created = add_new_position(ticker, shares, price_eur, account, trade_currency=pos_currency)
        if created:
            # Trade-Gedächtnis auch für neue Positionen (add_new_position macht das nicht selbst)
            try:
                from src.analysis.memory import record_trade
                record_trade(action, ticker, shares, price_eur, account, shares_before=0, shares_after=shares)
            except Exception as e:
                logger.warning("record_trade (neue Position) fehlgeschlagen: %s", e)
            if close_rec:
                close_recommendation_on_trade(ticker, action)
            try:
                from src.web.services.portfolio_service import update_region_on_trade
                update_region_on_trade("buy", ticker)
            except Exception:
                pass
            if push:
                _push_trade(action, ticker, shares, price, account, currency_sym, new_position=True)
            return {"ok": True,
                    "message": f"Neue Position: {shares}x {ticker} @ {price}{currency_sym} in {account}",
                    "status_code": 200, "new_position": True}

    return {"ok": False, "error": f"Ticker {ticker} nicht gefunden in {account}", "status_code": 404}


def _push_trade(action, ticker, shares, price, account, currency_sym, new_position):
    """Best-effort Push — darf den Trade nie gefährden."""
    try:
        from src.delivery.push_sender import send_push_safe
        action_label = 'Kauf' if action == 'buy' else 'Verkauf'
        title = f"Neue Position: {ticker}" if new_position else f"{action_label}: {ticker}"
        send_push_safe(
            category="trade_confirmed",
            title=title,
            body=f"{shares} × @ {price}{currency_sym} auf {account}",
            url="/portfolio",
            tag=f"trade-{ticker}",
            data={"ticker": ticker, "action": action, "shares": shares, "price": price,
                  "new_position": new_position},
        )
    except Exception:
        logger.warning("Push für trade_confirmed fehlgeschlagen")
