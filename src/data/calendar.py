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

# Feiertage werden pro Jahr aus Regeln berechnet (fest, Ostern-abhängig, US-Wochentagsregeln).
# Vorher stand hier eine Liste nur für 2026 — ab 2027 wäre jeder Tag als „offen“ gelaufen.


def _easter_sunday(year: int) -> date:
    """Ostersonntag (gregorianisch, Algorithmus nach Gauß/Meeus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-ter Wochentag im Monat (weekday 0=Mo); n=-1 = letzter."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _us_observed(d: date) -> date:
    """NYSE-Regel: Samstag → Freitag davor, Sonntag → Montag danach."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def holidays_for_year(year: int) -> list[tuple[date, str, str]]:
    """Börsenfeiertage (NYSE, XETRA, Wien) eines Jahres als (Datum, Name, Börsen)."""
    easter = _easter_sunday(year)
    out = [
        (date(year, 1, 1), "Neujahr", "XETRA, Wien"),
        (date(year, 1, 6), "Heilige Drei Könige", "Wien"),
        (easter - timedelta(days=2), "Karfreitag", "NYSE, XETRA, Wien"),
        (easter + timedelta(days=1), "Ostermontag", "XETRA, Wien"),
        (date(year, 5, 1), "Tag der Arbeit", "XETRA, Wien"),
        (easter + timedelta(days=50), "Pfingstmontag", "XETRA, Wien"),
        (easter + timedelta(days=60), "Fronleichnam", "Wien"),
        (date(year, 8, 15), "Mariä Himmelfahrt", "Wien"),
        (date(year, 10, 26), "Nationalfeiertag", "Wien"),
        (date(year, 11, 1), "Allerheiligen", "Wien"),
        (date(year, 12, 8), "Mariä Empfängnis", "Wien"),
        (date(year, 12, 24), "Heiligabend", "XETRA, Wien"),
        (date(year, 12, 25), "Weihnachten", "XETRA, Wien"),
        (date(year, 12, 26), "Stefanitag", "XETRA, Wien"),
        (date(year, 12, 31), "Silvester", "XETRA, Wien"),
        # NYSE
        (_nth_weekday(year, 1, 0, 3), "MLK Day", "NYSE"),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day", "NYSE"),
        (_nth_weekday(year, 5, 0, -1), "Memorial Day", "NYSE"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day", "NYSE"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving", "NYSE"),
    ]
    # Fixe US-Feiertage mit Ersatztag. Neujahr an einem Samstag wird NICHT am
    # 31.12. nachgeholt (NYSE-Sonderregel).
    for d, name in ((date(year, 6, 19), "Juneteenth"), (date(year, 7, 4), "Independence Day"),
                    (date(year, 12, 25), "Weihnachten")):
        obs = _us_observed(d)
        out.append((obs, name + (" (beobachtet)" if obs != d else ""), "NYSE"))
    ny = date(year, 1, 1)
    if ny.weekday() != 5:
        obs = _us_observed(ny)
        out.append((obs, "Neujahr" + (" (beobachtet)" if obs != ny else ""), "NYSE"))
    return out


def _holidays_on(d: date) -> list[dict]:
    """Feiertage an einem Tag, Börsen gleichnamiger Einträge zusammengeführt."""
    merged: dict[str, list[str]] = {}
    for hd, name, exchanges in holidays_for_year(d.year):
        if hd == d:
            ex = merged.setdefault(name.replace(" (beobachtet)", ""), [])
            ex.extend(e.strip() for e in exchanges.split(",") if e.strip() not in ex)
    return [{"name": n, "exchanges": ", ".join(ex)} for n, ex in merged.items()]


def get_market_status(today: date = None) -> dict:
    """Prüft ob die wichtigsten Börsen heute offen sind und liefert Kontext."""
    if today is None:
        today = date.today()

    weekday = today.weekday()  # 0=Mo, 6=So
    is_weekend = weekday >= 5

    holidays_today = _holidays_on(today)

    # Nächste Feiertage (kommende 14 Tage)
    upcoming_holidays = []
    for i in range(1, 15):
        future = today + timedelta(days=i)
        for h in _holidays_on(future):
            upcoming_holidays.append({
                "date": future.isoformat(),
                "name": h["name"],
                "exchanges": h["exchanges"],
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

# Zentralbank-Termine lassen sich nicht berechnen — Fed und EZB veröffentlichen sie
# jährlich. Neue Jahre hier ergänzen; fehlt ein Jahr, steht das als Hinweis im Kalender.
CENTRAL_BANK_EVENTS = {
    # Quellen: federalreserve.gov/monetarypolicy/fomccalendars.htm, ecb.europa.eu (Kalender
    # der Governing-Council-Sitzungen). Datum = Entscheidungstag. 2026 war vorher in
    # mehreren Terminen falsch (u. a. FOMC 16.12. statt 9.12., EZB 10.12. statt 17.12.).
    2026: [
        ("2026-01-28", "Fed FOMC Zinsentscheid", "FED"),
        ("2026-03-18", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2026-04-29", "Fed FOMC Zinsentscheid", "FED"),
        ("2026-06-17", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2026-07-29", "Fed FOMC Zinsentscheid", "FED"),
        ("2026-09-16", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2026-10-28", "Fed FOMC Zinsentscheid", "FED"),
        ("2026-12-09", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2026-02-05", "EZB Zinsentscheid", "EZB"),
        ("2026-03-19", "EZB Zinsentscheid", "EZB"),
        ("2026-04-30", "EZB Zinsentscheid", "EZB"),
        ("2026-06-11", "EZB Zinsentscheid", "EZB"),
        ("2026-07-23", "EZB Zinsentscheid", "EZB"),
        ("2026-09-10", "EZB Zinsentscheid", "EZB"),
        ("2026-10-29", "EZB Zinsentscheid", "EZB"),
        ("2026-12-17", "EZB Zinsentscheid", "EZB"),
    ],
    2027: [  # FOMC: vorläufiger Plan (Pressemitteilung 05.09.2025)
        ("2027-01-27", "Fed FOMC Zinsentscheid", "FED"),
        ("2027-03-17", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2027-04-28", "Fed FOMC Zinsentscheid", "FED"),
        ("2027-06-09", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2027-07-28", "Fed FOMC Zinsentscheid", "FED"),
        ("2027-09-15", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2027-10-27", "Fed FOMC Zinsentscheid", "FED"),
        ("2027-12-08", "Fed FOMC Zinsentscheid + Projektionen", "FED"),
        ("2027-02-04", "EZB Zinsentscheid", "EZB"),
        ("2027-03-18", "EZB Zinsentscheid", "EZB"),
        ("2027-04-29", "EZB Zinsentscheid", "EZB"),
        ("2027-06-10", "EZB Zinsentscheid", "EZB"),
        ("2027-07-22", "EZB Zinsentscheid", "EZB"),
        ("2027-09-09", "EZB Zinsentscheid", "EZB"),
        ("2027-10-28", "EZB Zinsentscheid", "EZB"),
        ("2027-12-16", "EZB Zinsentscheid", "EZB"),
    ],
}

# US-Datentermine kommen live aus dem FRED-Release-Kalender (enthält angekündigte
# künftige Termine). FRED-Release-IDs: 10 = CPI, 50 = Employment Situation,
# 53 = GDP, 54 = Personal Income and Outlays (PCE).
FRED_RELEASES = {
    10: "US CPI (Inflation)",
    50: "US Jobs Report (Arbeitsmarkt)",
    53: "US BIP",
    54: "US PCE (Fed-Inflationsmaß)",
}


def _fred_release_dates(api_key: str, start: date, end: date) -> list[dict]:
    events = []
    for release_id, name in FRED_RELEASES.items():
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/release/dates",
                params={
                    "release_id": release_id, "api_key": api_key, "file_type": "json",
                    "realtime_start": start.isoformat(), "realtime_end": "9999-12-31",
                    "include_release_dates_with_no_data": "true",
                    "sort_order": "asc", "limit": 10,
                },
                timeout=10,
            )
            for row in resp.json().get("release_dates", []):
                d = date.fromisoformat(row["date"])
                if start <= d <= end:
                    events.append({"date": d.isoformat(), "name": name, "category": "MACRO"})
        except Exception as e:
            logger.warning(f"FRED-Release-Kalender {release_id} Fehler: {e}")
    return events


def _first_friday_jobs_reports(start: date, end: date) -> list[dict]:
    """Ersatz ohne FRED-Key: Arbeitsmarktbericht meist am ersten Freitag im Monat (Näherung)."""
    events = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        d = _nth_weekday(y, m, 4, 1)
        if start <= d <= end:
            events.append({"date": d.isoformat(), "name": "US Jobs Report (ca., erster Freitag)",
                           "category": "MACRO"})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return events


def get_upcoming_macro_events(days_ahead: int = 30, fred_api_key: str = "",
                              today: date | None = None) -> list[dict]:
    """Holt kommende Makro-Events der nächsten X Tage."""
    today = today or date.today()
    cutoff = today + timedelta(days=days_ahead)
    events = []

    for year in range(today.year, cutoff.year + 1):
        if year not in CENTRAL_BANK_EVENTS:
            logger.warning(f"Zentralbank-Termine für {year} nicht gepflegt (CENTRAL_BANK_EVENTS)")
            events.append({"date": date(year, 1, 1).isoformat() if year > today.year else today.isoformat(),
                           "name": f"Hinweis: Fed-/EZB-Termine {year} nicht hinterlegt",
                           "category": "INFO"})
            continue
        for date_str, name, category in CENTRAL_BANK_EVENTS[year]:
            if today <= date.fromisoformat(date_str) <= cutoff:
                events.append({"date": date_str, "name": name, "category": category})

    if fred_api_key:
        events.extend(_fred_release_dates(fred_api_key, today, cutoff))
    else:
        events.extend(_first_friday_jobs_reports(today, cutoff))

    for e in events:
        e["days_until"] = (date.fromisoformat(e["date"]) - today).days
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
            emoji = {"FED": "🇺🇸", "EZB": "🇪🇺", "MACRO": "📊", "INFO": "ℹ️"}.get(e["category"], "📅")
            lines.append(f"  {e['date']} (in {e['days_until']}d): {emoji} {e['name']}")
    else:
        lines.append("  Keine anstehenden Makro-Events.")

    return "\n".join(lines)
