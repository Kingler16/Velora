"""Offene Orders — der fehlende Zwischenzustand zwischen Empfehlung und Depot.

Kernidee: Eine platzierte (Limit-)Order ist NOCH KEINE Position. Sie landet hier
als 'pending' und verändert das Depot NICHT. Erst beim tatsächlichen Ausführen
(fill_order) mit dem ECHTEN Fill-Preis wird die Position ins Portfolio geschrieben
(über den regulären Trade-Pfad in src.delivery.trade_exec) und die Order auf
'filled' gesetzt. Das verhindert, dass Velora-Depot und Broker auseinanderdriften,
nur weil eine Order platziert (aber vielleicht nie ausgeführt) wurde.

Lebenszyklus einer Empfehlung:
    open ──place_order──▶ order_placed ──fill_order──▶ executed
                              └────────cancel_order──▶ open (wieder handelbar)

Speicher: memory/orders.json (gitignored → bleibt geräte-lokal).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
ORDERS_PATH = MEMORY_DIR / "orders.json"
RECS_PATH = MEMORY_DIR / "recommendations.json"


# ─── Persistenz ──────────────────────────────────────────────

def load_orders() -> list[dict]:
    if not ORDERS_PATH.exists():
        return []
    try:
        with open(ORDERS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.error("orders.json konnte nicht gelesen werden: %s", e)
        return []


def _save_orders(orders: list[dict]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ORDERS_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(orders, f, indent=2, ensure_ascii=False)
    tmp.replace(ORDERS_PATH)


def get_open_orders() -> list[dict]:
    """Alle noch offenen (pending) Orders, neueste zuerst."""
    pending = [o for o in load_orders() if o.get("status") == "pending"]
    pending.sort(key=lambda o: o.get("placed_date", ""), reverse=True)
    return pending


def _new_id(ticker: str, now: datetime) -> str:
    return f"ord_{(ticker or 'x').replace('.', '_')}_{now.strftime('%Y%m%d%H%M%S')}"


def _set_rec_status(ticker: str, status: str, outcome: str | None = None,
                    from_statuses: tuple[str, ...] = ("open",)) -> None:
    """Setzt den Status passender Empfehlungen (Ticker-Match mit/ohne Exchange-Suffix)."""
    if not RECS_PATH.exists() or not ticker:
        return
    try:
        with open(RECS_PATH) as f:
            recs = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    t = ticker.upper()
    changed = False
    for r in recs:
        if r.get("status") not in from_statuses:
            continue
        rt = (r.get("ticker") or "").upper()
        if rt == t or rt.split(".")[0] == t or t.split(".")[0] == rt:
            r["status"] = status
            if outcome is not None:
                r["outcome"] = outcome
            changed = True
    if changed:
        with open(RECS_PATH, "w") as f:
            json.dump(recs, f, indent=2, ensure_ascii=False)


# ─── Lebenszyklus ────────────────────────────────────────────

def place_order(ticker: str, action: str, shares, limit_price, account: str,
                currency: str = "EUR", rec_ticker: str | None = None,
                note: str | None = None) -> dict:
    """Legt eine offene Order an. Verändert das Depot NICHT."""
    action = (action or "").strip().lower()
    ticker = (ticker or "").strip().upper()
    if action not in ("buy", "sell"):
        return {"ok": False, "error": "action muss 'buy' oder 'sell' sein", "status_code": 400}
    if not ticker:
        return {"ok": False, "error": "Ticker fehlt", "status_code": 400}
    try:
        shares = float(shares) if shares not in (None, "") else None
        limit_price = float(limit_price) if limit_price not in (None, "") else None
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares und Limit müssen Zahlen sein", "status_code": 400}
    if not shares or shares <= 0:
        return {"ok": False, "error": "shares muss > 0 sein", "status_code": 400}

    now = datetime.now()
    order = {
        "id": _new_id(ticker, now),
        "ticker": ticker,
        "action": action,
        "shares": shares,
        "limit_price": limit_price,
        "currency": (currency or "EUR").upper(),
        "account": account or "",
        "status": "pending",
        "placed_date": now.isoformat(),
        "rec_ticker": (rec_ticker or ticker).upper(),
        "fill_price": None,
        "fill_date": None,
        "note": note,
    }
    orders = load_orders()
    orders.append(order)
    _save_orders(orders)
    _set_rec_status(order["rec_ticker"], "order_placed", f"Order platziert ({action})")
    logger.info("Order platziert: %s %s %s @ %s in %s", action, shares, ticker, limit_price, account)
    return {"ok": True, "message": f"Order platziert: {action} {shares}x {ticker}", "order": order, "status_code": 200}


def fill_order(order_id: str, fill_price=None, fill_date: str | None = None,
               account: str | None = None) -> dict:
    """Führt eine offene Order aus → schreibt jetzt erst die Position ins Depot."""
    orders = load_orders()
    order = next((o for o in orders if o.get("id") == order_id), None)
    if order is None:
        return {"ok": False, "error": "Order nicht gefunden", "status_code": 404}
    if order.get("status") != "pending":
        return {"ok": False, "error": "Order ist nicht mehr offen", "status_code": 400}

    action = order.get("action")
    ticker = order.get("ticker")
    shares = order.get("shares")
    acct = account or order.get("account")
    currency = order.get("currency", "EUR")
    try:
        price = float(fill_price) if fill_price not in (None, "") else order.get("limit_price")
    except (TypeError, ValueError):
        return {"ok": False, "error": "Fill-Preis muss eine Zahl sein", "status_code": 400}
    if price is None or price <= 0 or not shares:
        return {"ok": False, "error": "Fill-Preis und Stückzahl erforderlich", "status_code": 400}

    # Portfolio über den regulären Trade-Pfad schreiben (Cash + Trade-Gedächtnis inklusive).
    from src.delivery.trade_exec import book_trade
    result = book_trade(action, ticker, acct, shares, price, trade_currency=currency, close_rec=False)
    if not result.get("ok"):
        # Depot nicht verändert → Order bleibt pending, damit nichts verloren geht.
        return result

    now = datetime.now()
    order["status"] = "filled"
    order["fill_price"] = price
    order["fill_date"] = fill_date or now.isoformat()
    order["account"] = acct
    _save_orders(orders)

    _set_rec_status(order.get("rec_ticker") or ticker, "executed",
                    f"Order ausgeführt bei {price} {currency}",
                    from_statuses=("order_placed", "open"))
    logger.info("Order ausgeführt: %s @ %s (%s)", ticker, price, order_id)
    return {"ok": True, "message": result.get("message"), "status_code": 200}


def cancel_order(order_id: str, reopen_rec: bool = True) -> dict:
    """Storniert eine offene Order. Depot unberührt. Empfehlung wird wieder handelbar."""
    orders = load_orders()
    order = next((o for o in orders if o.get("id") == order_id), None)
    if order is None:
        return {"ok": False, "error": "Order nicht gefunden", "status_code": 404}
    if order.get("status") != "pending":
        return {"ok": False, "error": "Order ist nicht mehr offen", "status_code": 400}

    order["status"] = "cancelled"
    order["cancelled_date"] = datetime.now().isoformat()
    _save_orders(orders)
    if reopen_rec:
        _set_rec_status(order.get("rec_ticker") or order.get("ticker"), "open",
                        None, from_statuses=("order_placed",))
    logger.info("Order storniert: %s (%s)", order.get("ticker"), order_id)
    return {"ok": True, "message": "Order storniert", "status_code": 200}
