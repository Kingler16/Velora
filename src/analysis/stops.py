"""
Stop-Loss-Überblick: Ist-Stops (beim Broker gesetzt) gegen Soll-Stops (ATR-basiert).

Hintergrund: Bei Trade Republic und der Erste Bank lässt sich zu einer Limit-Kauf-
order kein Stop im Voraus hinterlegen — den kann man erst setzen, wenn die Position
wirklich im Depot liegt. Genau dort ging es bisher unter: gekauft, Stop vergessen,
und nichts im System hat je nachgehakt. Velora kannte Stops ausschliesslich als
Empfehlungswert, nie als Zustand des Depots.

Dieses Modul führt beides zusammen:
  - Ist-Stop:  pro Position gepflegtes Feld ``stop_loss`` (Quote-Währung des Tickers)
  - Soll-Stop: Kurs − 2×ATR14, dieselbe Regel, die der Briefing-Prompt für
               Empfehlungen verlangt ("Stop ≈ Kurs − 1,5–2×ATR")

Die Bewertung ist bewusst mechanisch und erklärt sich aus Zahlen. Velora bekommt
das Ergebnis im Briefing und darf begründet abweichen (z.B. Earnings in zwei Tagen,
oder ein charttechnischer Halt unter dem ATR-Wert).
"""

import logging

logger = logging.getLogger(__name__)

# Vielfache des ATR, gemessen am Abstand Kurs → Stop.
_ATR_TARGET = 2.0    # Soll-Abstand
_ATR_MIN = 1.0       # darunter: Rauschen stoppt dich aus
_ATR_MAX = 3.5       # darüber: unnötig viel Verlust zugelassen

# Ab dieser Abweichung gilt ein gesetzter Stop als nachziehbar (in ATR).
_TRAIL_TRIGGER = 1.0

# Unterhalb dieser Tagesschwankung ist ein Stop sinnlos: bei einem Laufzeitfonds
# mit ATR 0,03 läge der 2×ATR-Stop 0,1% unter dem Kurs und würde vom normalen
# Handelsrauschen sofort ausgelöst. Solche Papiere sichert man nicht mit Stops.
_MIN_ATR_PCT = 1.0


def _pct(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 1) if b else None


def compute_stop_overview(portfolio: dict, market_data: dict) -> dict:
    """Stellt für jede Depot-Position Ist- und Soll-Stop gegenüber.

    Returns:
        {
          "positions": [ {ticker, name, account, status, ist_stop, soll_stop,
                          current_price, currency, risiko_eur, ...}, ... ],
          "ohne_stop": int, "mit_stop": int, "nicht_bewertbar": int,
          "risiko_eur_gesamt": float,     # Summe Verlust bei Auslösung aller Ist-Stops
          "ungesichert_eur": float,       # Depotwert ohne jeden Stop
        }
    """
    from src.data.fx import safe_eur_usd, resolve_quote_currency

    eur_usd = safe_eur_usd(market_data)
    positionen: list[dict] = []
    ohne_stop = mit_stop = nicht_bewertbar = 0
    risiko_eur_gesamt = 0.0
    ungesichert_eur = 0.0

    for account_name, account in (portfolio.get("accounts") or {}).items():
        for pos in account.get("positions") or []:
            ticker = pos.get("ticker")
            shares = float(pos.get("shares") or 0)
            name = pos.get("name") or ticker or "?"
            ist_stop = pos.get("stop_loss")
            ist_stop = float(ist_stop) if ist_stop not in (None, "") else None

            md = (market_data.get("positions") or {}).get(ticker) or {}
            price = md.get("price") or {}
            kurs = price.get("current_price")
            atr = price.get("atr_14")

            # Fonds ohne Live-Kurs (oder ohne Ticker) lassen sich nicht bewerten —
            # ehrlich ausweisen statt still übergehen.
            if not kurs or not shares:
                nicht_bewertbar += 1
                positionen.append({
                    "ticker": ticker, "name": name, "account": account_name,
                    "status": "nicht_bewertbar", "ist_stop": ist_stop,
                    "soll_stop": None, "current_price": kurs, "currency": None,
                    "hinweis": "kein Live-Kurs — Stop nicht berechenbar",
                })
                continue

            quote_ccy = resolve_quote_currency(price, pos.get("currency", "EUR"))
            in_eur = 1.0 if quote_ccy == "EUR" else 1.0 / eur_usd
            wert_eur = shares * kurs * in_eur

            # Zu ruhige Papiere (Laufzeitfonds, Geldmarkt) sinnvoll ausklammern,
            # statt einen Stop vorzuschlagen, der sofort auslösen würde.
            atr_pct = price.get("atr_pct")
            if atr_pct is None and atr and kurs:
                atr_pct = atr / kurs * 100
            zu_ruhig = atr is not None and atr_pct is not None and atr_pct < _MIN_ATR_PCT

            if zu_ruhig and ist_stop is None:
                nicht_bewertbar += 1
                positionen.append({
                    "ticker": ticker, "name": name, "account": account_name,
                    "status": "kein_stop_noetig", "ist_stop": None, "soll_stop": None,
                    "current_price": round(kurs, 2), "currency": quote_ccy,
                    "wert_eur": round(wert_eur, 2),
                    "hinweis": f"Tagesschwankung nur {atr_pct:.2f}% — Stop wäre Rauschen, nicht Schutz",
                })
                continue

            soll_stop = round(kurs - _ATR_TARGET * atr, 2) if (atr and not zu_ruhig) else None

            # Abstand des gesetzten Stops in ATR-Einheiten — die eigentliche Bewertung.
            abstand_atr = round((kurs - ist_stop) / atr, 2) if (ist_stop and atr) else None

            if ist_stop is None:
                status = "kein_stop"
                ohne_stop += 1
                ungesichert_eur += wert_eur
            elif ist_stop >= kurs:
                # Stop über dem Kurs löst sofort aus — fast immer ein Tippfehler.
                status = "ungueltig"
                mit_stop += 1
            elif atr is None:
                status = "gesetzt"
                mit_stop += 1
            elif abstand_atr < _ATR_MIN:
                status = "zu_eng"
                mit_stop += 1
            elif abstand_atr > _ATR_MAX:
                status = "zu_weit"
                mit_stop += 1
            elif soll_stop and (soll_stop - ist_stop) > _TRAIL_TRIGGER * atr:
                # Kurs ist gelaufen, der Stop steht noch weit darunter.
                status = "nachziehbar"
                mit_stop += 1
            else:
                status = "ok"
                mit_stop += 1

            if ist_stop and ist_stop < kurs:
                risiko_eur_gesamt += (kurs - ist_stop) * shares * in_eur

            positionen.append({
                "ticker": ticker,
                "name": name,
                "account": account_name,
                "status": status,
                "ist_stop": ist_stop,
                "soll_stop": soll_stop,
                "current_price": round(kurs, 2),
                "currency": quote_ccy,
                "atr": atr,
                "abstand_atr": abstand_atr,
                "abstand_pct": _pct(ist_stop, kurs) if ist_stop else None,
                "soll_abstand_pct": _pct(soll_stop, kurs) if soll_stop else None,
                "wert_eur": round(wert_eur, 2),
                # Was ein Auslösen kosten würde (Ist-Stop), bzw. beim Soll-Stop kosten dürfte.
                "risiko_eur": round((kurs - ist_stop) * shares * in_eur, 2) if (ist_stop and ist_stop < kurs) else None,
                "risiko_soll_eur": round((kurs - soll_stop) * shares * in_eur, 2) if soll_stop else None,
            })

    # Ungesicherte zuerst, dann die auffälligen, dann nach Positionsgrösse.
    rang = {"kein_stop": 0, "ungueltig": 1, "zu_weit": 2, "zu_eng": 3,
            "nachziehbar": 4, "gesetzt": 5, "ok": 6, "kein_stop_noetig": 7, "nicht_bewertbar": 8}
    positionen.sort(key=lambda p: (rang.get(p["status"], 9), -(p.get("wert_eur") or 0)))

    return {
        "positions": positionen,
        "ohne_stop": ohne_stop,
        "mit_stop": mit_stop,
        "nicht_bewertbar": nicht_bewertbar,
        "risiko_eur_gesamt": round(risiko_eur_gesamt, 2),
        "ungesichert_eur": round(ungesichert_eur, 2),
    }


_STATUS_TEXT = {
    "kein_stop": "KEIN STOP",
    "ungueltig": "UNGÜLTIG (Stop ≥ Kurs)",
    "zu_eng": "zu eng",
    "zu_weit": "zu weit",
    "nachziehbar": "nachziehbar",
    "gesetzt": "gesetzt",
    "ok": "ok",
    "nicht_bewertbar": "nicht bewertbar",
    "kein_stop_noetig": "Stop nicht sinnvoll",
}


def format_stop_overview(overview: dict | None) -> str:
    """Rendert die Stop-Lage für den Briefing-Prompt.
    Gibt "" zurück, wenn es nichts zu berichten gibt."""
    if not overview or not overview.get("positions"):
        return ""

    lines = [
        f"Positionen mit Stop: {overview['mit_stop']} | OHNE Stop: {overview['ohne_stop']}"
        + (f" | nicht bewertbar: {overview['nicht_bewertbar']}" if overview.get("nicht_bewertbar") else "")
    ]
    if overview.get("ungesichert_eur"):
        lines.append(f"Ungesicherter Depotwert (Positionen ohne Stop): {overview['ungesichert_eur']:.0f}€")
    if overview.get("risiko_eur_gesamt"):
        lines.append(f"Rechnerischer Verlust, wenn alle gesetzten Stops auslösen: {overview['risiko_eur_gesamt']:.0f}€")

    for p in overview["positions"]:
        konto = f" [{p['account']}]"
        if p["status"] in ("nicht_bewertbar", "kein_stop_noetig"):
            lines.append(f"  [{_STATUS_TEXT.get(p['status'], p['status'])}] {p['name']} ({p['ticker']}){konto}: {p.get('hinweis')}")
            continue
        c = p["currency"]
        teile = [f"Kurs {p['current_price']} {c}"]
        if p["ist_stop"] is not None:
            teile.append(f"Ist-Stop {p['ist_stop']} ({p['abstand_pct']:+.1f}%, {p['abstand_atr']}×ATR)")
        else:
            teile.append("Ist-Stop: KEINER GESETZT")
        if p["soll_stop"] is not None:
            teile.append(f"Soll-Stop {p['soll_stop']} ({p['soll_abstand_pct']:+.1f}%)")
        if p.get("risiko_soll_eur"):
            teile.append(f"Risiko am Soll-Stop {p['risiko_soll_eur']:.0f}€")
        lines.append(f"  [{_STATUS_TEXT.get(p['status'], p['status'])}] {p['name']} ({p['ticker']}){konto}: "
                     + " | ".join(teile))

    lines.append(
        "→ Soll-Stop = Kurs − 2×ATR14 (rein mechanisch). Weiche begründet ab, wenn "
        "Charttechnik, Earnings-Termin oder Positionsgrösse dagegen sprechen. Nenne fehlende "
        "Stops konkret mit Kurs, damit der Nutzer sie beim Broker eintragen kann — er kann "
        "Stops erst NACH dem Kauf setzen, deshalb fehlen sie."
    )
    return "\n".join(lines)
