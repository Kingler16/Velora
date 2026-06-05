"""
Finanzkalender: Börsen-Status, Earnings, Makro-Events.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date

import requests
import yfinance as yf

logger = logging.getLogger(__name__)


# ── Börsen-Kalender ──────────────────────────────────────────────

# Wichtige Feiertage (US + EU), manuell gepflegt für 2026
# Format: (Monat, Tag, Name, betroffene Börsen)
HOLIDAYS_2026 = [
    (1, 1, "Neujahr", "NYSE, XETRA, Wien"),
    (1, 6, "Heilige Drei Könige", "Wien"),
    (1, 19, "MLK Day", "NYSE"),
    (2, 16, "Presidents' Day", "NYSE"),
    (4, 3, "Karfreitag", "NYSE, XETRA, Wien"),
    (4, 6, "Ostermontag", "XETRA, Wien"),
    (5, 1, "Tag der Arbeit", "XETRA, Wien"),
    (5, 25, "Memorial Day", "NYSE"),
    (5, 25, "Pfingstmontag", "XETRA, Wien"),
    (6, 4, "Fronleichnam", "Wien"),
    (6, 19, "Juneteenth", "NYSE"),
    (7, 3, "Independence Day (beobachtet)", "NYSE"),
    (8, 15, "Mariä Himmelfahrt", "Wien"),
    (9, 7, "Labor Day", "NYSE"),
    (10, 26, "Nationalfeiertag", "Wien"),
    (11, 1, "Allerheiligen", "Wien"),
    (11, 26, "Thanksgiving", "NYSE"),
    (12, 8, "Mariä Empfängnis", "Wien"),
    (12, 24, "Heiligabend", "XETRA, Wien"),
    (12, 25, "Weihnachten", "NYSE, XETRA, Wien"),
    (12, 26, "Stefanitag", "XETRA, Wien"),
    (12, 31, "Silvester", "XETRA, Wien"),
]


def get_market_status(today: date = None) -> dict:
    """Prüft ob die wichtigsten Börsen heute offen sind und liefert Kontext."""
    if today is None:
        today = date.today()

    weekday = today.weekday()  # 0=Mo, 6=So
    is_weekend = weekday >= 5

    # Feiertage heute
    holidays_today = []
    for month, day, name, exchanges in HOLIDAYS_2026:
        if today.month == month and today.day == day:
            holidays_today.append({"name": name, "exchanges": exchanges})

    # Nächste Feiertage (kommende 14 Tage)
    upcoming_holidays = []
    for i in range(1, 15):
        future = today + timedelta(days=i)
        for month, day, name, exchanges in HOLIDAYS_2026:
            if future.month == month and future.day == day:
                upcoming_holidays.append({
                    "date": future.isoformat(),
                    "name": name,
                    "exchanges": exchanges,
                    "days_until": i,
                })

    nyse_open = not is_weekend and not any("NYSE" in h["exchanges"] for h in holidays_today)
    xetra_open = not is_weekend and not any("XETRA" in h["exchanges"] for h in holidays_today)
    wien_open = not is_weekend and not any("Wien" in h["exchanges"] for h in holidays_today)

    return {
        "date": today.isoformat(),
        "weekday": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][weekday],
        "is_weekend": is_weekend,
        "nyse_open": nyse_open,
        "xetra_open": xetra_open,
        "wien_open": wien_open,
        "holidays_today": holidays_today,
        "upcoming_holidays": upcoming_holidays,
    }


# ── Makro-Event-Kalender ────────────────────────────────────────

# Bekannte Termine 2026 (Fed, EZB, wichtige US-Daten)
MACRO_EVENTS_2026 = [
    # Fed FOMC Meetings (Datum = Entscheidungstag)
    ("2026-01-28", "Fed FOMC Zinsentscheid", "FED"),
    ("2026-03-18", "Fed FOMC Zinsentscheid", "FED"),
    ("2026-05-06", "Fed FOMC Zinsentscheid", "FED"),
    ("2026-06-17", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
    ("2026-07-29", "Fed FOMC Zinsentscheid", "FED"),
    ("2026-09-16", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
    ("2026-10-28", "Fed FOMC Zinsentscheid", "FED"),
    ("2026-12-16", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
    # EZB Sitzungen
    ("2026-01-22", "EZB Zinsentscheid", "EZB"),
    ("2026-03-05", "EZB Zinsentscheid", "EZB"),
    ("2026-04-16", "EZB Zinsentscheid", "EZB"),
    ("2026-06-04", "EZB Zinsentscheid", "EZB"),
    ("2026-07-16", "EZB Zinsentscheid", "EZB"),
    ("2026-09-10", "EZB Zinsentscheid", "EZB"),
    ("2026-10-22", "EZB Zinsentscheid", "EZB"),
    ("2026-12-10", "EZB Zinsentscheid", "EZB"),
    # Wichtige US-Daten (monatlich, approximiert)
    ("2026-04-10", "US CPI (März)", "MACRO"),
    ("2026-05-13", "US CPI (April)", "MACRO"),
    ("2026-06-10", "US CPI (Mai)", "MACRO"),
    ("2026-07-14", "US CPI (Juni)", "MACRO"),
    ("2026-04-04", "US Jobs Report (März)", "MACRO"),
    ("2026-05-08", "US Jobs Report (April)", "MACRO"),
    ("2026-06-05", "US Jobs Report (Mai)", "MACRO"),
]


def get_upcoming_macro_events(days_ahead: int = 30) -> list[dict]:
    """Holt kommende Makro-Events der nächsten X Tage."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    events = []

    for date_str, name, category in MACRO_EVENTS_2026:
        event_date = date.fromisoformat(date_str)
        if today <= event_date <= cutoff:
            events.append({
                "date": date_str,
                "name": name,
                "category": category,
                "days_until": (event_date - today).days,
            })

    events.sort(key=lambda x: x["date"])
    return events


# ── Earnings-Kalender ────────────────────────────────────────────

def fetch_earnings_surprise_history(ticker: str, stock=None) -> dict | None:
    """Holt die Earnings-Surprise-Historie der letzten ~8 Quartale via yfinance.

    Nutzt ``stock.earnings_dates`` (DataFrame). yfinance-Spaltennamen können je
    Version variieren — wir prüfen vorhandene Spalten und nutzen "Surprise(%)"
    wenn vorhanden, sonst rechnen wir aus Estimate/Reported selbst.

    Rückgabe-Felder:
      - quarters: Anzahl ausgewerteter (gemeldeter) Quartale
      - beats: Anzahl Quartale mit Surprise > 0
      - beat_rate: beats/quarters*100 (0 Dezimalstellen)
      - avg_surprise_pct: Ø Surprise (1 Dezimalstelle)
      - last_surprise_pct: jüngste Surprise (1 Dezimalstelle)

    None bei fehlenden Daten / Exception (yfinance-Earnings-Daten sind notorisch lückig).
    """
    if not ticker:
        return None
    try:
        if stock is None:
            stock = yf.Ticker(ticker)
        df = stock.earnings_dates
        if df is None or not hasattr(df, "empty") or df.empty:
            return None

        cols = {str(c).lower().replace(" ", ""): c for c in df.columns}
        est_col = cols.get("epsestimate")
        rep_col = cols.get("reportedeps")
        surp_col = cols.get("surprise(%)") or cols.get("surprise%") or cols.get("surprise")

        # Ohne gemeldete EPS können wir nichts auswerten.
        if rep_col is None:
            return None

        surprises = []
        for _, row in df.iterrows():
            reported = row.get(rep_col)
            # Nur Zeilen mit tatsächlich gemeldeten Werten.
            if reported is None or _is_nan(reported):
                continue

            surprise = None
            if surp_col is not None:
                s = row.get(surp_col)
                if s is not None and not _is_nan(s):
                    surprise = float(s)
            # Fallback / falls Surprise fehlt: aus Estimate + Reported selbst rechnen.
            if surprise is None and est_col is not None:
                est = row.get(est_col)
                if est is not None and not _is_nan(est):
                    est = float(est)
                    if est != 0:
                        surprise = (float(reported) - est) / abs(est) * 100.0
            if surprise is not None:
                surprises.append(surprise)

        # earnings_dates ist absteigend sortiert (neueste zuerst) -> jüngste = surprises[0].
        surprises = surprises[:8]
        quarters = len(surprises)
        if quarters == 0:
            return None

        beats = sum(1 for s in surprises if s > 0)
        avg_surprise = sum(surprises) / quarters
        return {
            "quarters": quarters,
            "beats": beats,
            "beat_rate": round(beats / quarters * 100, 0),
            "avg_surprise_pct": round(avg_surprise, 1),
            "last_surprise_pct": round(surprises[0], 1),
        }
    except Exception as e:
        logger.debug(f"Earnings-Surprise-Historie für {ticker}: {e}")
        return None


def _is_nan(val) -> bool:
    """Robuster NaN-Check (auch für pandas/numpy-Werte)."""
    try:
        return val != val  # NaN ist ungleich sich selbst
    except Exception:
        return False


def _fetch_earnings_single(t: dict) -> list[dict]:
    ticker = t.get("ticker")
    if not ticker:
        return []
    out = []
    try:
        stock = yf.Ticker(ticker)
        # Surprise-Historie über dieselbe yf.Ticker-Instanz holen (kein extra Call-Setup).
        surprise_history = fetch_earnings_surprise_history(ticker, stock=stock)
        cal = stock.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            if isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if earnings_date:
                    date_str = str(earnings_date[0]) if isinstance(earnings_date, list) else str(earnings_date)
                    out.append({
                        "ticker": ticker,
                        "name": t["name"],
                        "event": "Earnings",
                        "date": date_str[:10],
                        "surprise_history": surprise_history,
                    })
            elif hasattr(cal, 'to_dict'):
                cal_dict = cal.to_dict()
                for key in cal_dict:
                    if "earning" in str(key).lower():
                        val = cal_dict[key]
                        if isinstance(val, dict):
                            val = list(val.values())[0] if val else None
                        if val:
                            out.append({
                                "ticker": ticker,
                                "name": t["name"],
                                "event": str(key),
                                "date": str(val)[:10],
                                "surprise_history": surprise_history,
                            })
    except Exception as e:
        logger.debug(f"Earnings für {ticker}: {e}")
    return out


def fetch_earnings_calendar(tickers: list[dict]) -> list[dict]:
    """Holt kommende Earnings-Termine via yfinance (parallel)."""
    if not tickers:
        return []
    events = []
    with ThreadPoolExecutor(max_workers=min(10, len(tickers))) as ex:
        futures = [ex.submit(_fetch_earnings_single, t) for t in tickers]
        for fut in as_completed(futures):
            events.extend(fut.result())
    events.sort(key=lambda x: x.get("date", "9999"))
    return events


def search_earnings_via_brave(tickers: list[dict], brave_api_key: str) -> list[dict]:
    """Ergänzt Earnings-Termine via Brave Search für Ticker ohne yfinance-Daten."""
    if not brave_api_key:
        return []

    events = []
    # Nur für die ersten 5 Ticker ohne Earnings-Daten suchen (API-Limits)
    for t in tickers[:5]:
        try:
            headers = {"X-Subscription-Token": brave_api_key}
            params = {
                "q": f"{t['name']} earnings date 2026",
                "count": 1,
                "freshness": "pm",
            }
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers, params=params, timeout=10,
            )
            data = resp.json()
            results = data.get("web", {}).get("results", [])
            if results:
                events.append({
                    "ticker": t["ticker"],
                    "name": t["name"],
                    "event": "Earnings (aus Web-Recherche)",
                    "date": "siehe News",
                    "source": results[0].get("description", "")[:100],
                })
        except Exception as e:
            logger.debug(f"Brave Earnings-Suche für {t['name']}: {e}")

    return events


# ── Formatierung ─────────────────────────────────────────────────

def format_full_calendar(market_status: dict, earnings: list[dict], macro_events: list[dict]) -> str:
    """Formatiert den kompletten Kalender für den Prompt."""
    lines = []

    # Börsen-Status
    lines.append("=== BÖRSEN-STATUS ===")
    ms = market_status
    lines.append(f"Datum: {ms['date']} ({ms['weekday']})")
    lines.append(f"NYSE: {'OFFEN' if ms['nyse_open'] else 'GESCHLOSSEN'} | "
                 f"XETRA: {'OFFEN' if ms['xetra_open'] else 'GESCHLOSSEN'} | "
                 f"Wien: {'OFFEN' if ms['wien_open'] else 'GESCHLOSSEN'}")

    if ms['holidays_today']:
        for h in ms['holidays_today']:
            lines.append(f"  Feiertag heute: {h['name']} ({h['exchanges']})")

    if ms['upcoming_holidays']:
        lines.append("Kommende Feiertage:")
        for h in ms['upcoming_holidays'][:5]:
            lines.append(f"  {h['date']} ({h['days_until']}d): {h['name']} ({h['exchanges']})")

    # Earnings
    lines.append("\n=== EARNINGS-KALENDER ===")
    if earnings:
        for e in earnings:
            days = ""
            try:
                d = date.fromisoformat(e["date"][:10])
                diff = (d - date.today()).days
                days = f" (in {diff} Tagen)" if diff > 0 else " (HEUTE!)" if diff == 0 else f" (vor {-diff} Tagen)"
            except (ValueError, TypeError):
                pass

            # Surprise-Historie kompakt anhängen, nur wenn vorhanden.
            hist = ""
            sh = e.get("surprise_history")
            if sh:
                parts = [f"Beat-Rate {sh['beat_rate']:.0f}%"]
                avg = sh.get("avg_surprise_pct")
                if avg is not None:
                    parts.append(f"Ø {avg:+.1f}%")
                last = sh.get("last_surprise_pct")
                if last is not None:
                    parts.append(f"zuletzt {last:+.1f}%")
                hist = f" ({', '.join(parts)})"

            lines.append(f"  {e['date']} | {e['name']} ({e['ticker']}): {e['event']}{days}{hist}")
    else:
        lines.append("  Keine Earnings-Termine gefunden.")

    # Makro-Events
    lines.append("\n=== MAKRO-EVENTS ===")
    if macro_events:
        for e in macro_events:
            emoji = {"FED": "🇺🇸", "EZB": "🇪🇺", "MACRO": "📊"}.get(e["category"], "📅")
            lines.append(f"  {e['date']} (in {e['days_until']}d): {emoji} {e['name']}")
    else:
        lines.append("  Keine anstehenden Makro-Events.")

    return "\n".join(lines)
