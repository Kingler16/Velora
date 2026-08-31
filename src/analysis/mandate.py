"""
"Mein Mandat" — die vom User (gemeinsam mit Velora) definierte Anlage-Strategie.

EIN Dokument mit zwei Hälften:
  - NARRATIVE Hälfte (summary_human, philosophy, soft_preferences, tax_directives):
    Freitext, fliesst nur in den Prompt — kein Code prüft das.
  - STRUKTURIERTE Hälfte (hard_rules mit rule="block"|"warn", targets):
    maschinell PRÜFBAR — der Validator prüft jede Empfehlung dagegen.

Das Feature ist OPT-IN: existiert keine config/mandate.json, gibt load_mandate()
None zurück und der gesamte bestehende Code läuft unverändert weiter.

Velora schreibt das Mandat NIE direkt — Änderungen laufen (Phase 3b) über den
Confirmation-Flow. Hier: laden, validieren, in den Prompt rendern, Empfehlungen prüfen.
"""

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
MANDATE_PATH = CONFIG_DIR / "mandate.json"
BACKUP_DIR = Path(__file__).parent.parent.parent / "memory" / "mandate_backups"

# Bekannte Regel-Typen — unbekannte werden beim Speichern abgelehnt (nicht crashen).
KNOWN_RULE_TYPES = {
    "forbidden_ticker", "forbidden_instrument", "max_position_pct",
    "min_cash_pct", "max_keyword_pct", "max_sector_pct",
}

_EUR_SUFFIXES = (".DE", ".AS", ".PA", ".VI", ".MI", ".MC", ".BR", ".LS", ".HE", ".ST", ".OL", ".F", ".DU")
_EUR_ISIN_PREFIXES = ("AT0", "DE0", "FR0", "NL0", "IE0", "ES0", "IT0", "BE0", "FI0", "PT0", "LU0")


# Keywords, die in normaler Analyse-Prosa vorkommen und deshalb NUR gegen
# Ticker/Name geprüft werden — nie gegen das Reasoning:
#   "Risk/Reward 2x", "Stop bei 2x ATR", "operating leverage", "Bruttomargin",
#   "Öl-Futures signalisieren…", "eine Option wäre…"
# Eindeutige Hebel-Begriffe (hebel, cfd, optionsschein, knock-out …) bleiben
# gegen den ganzen Text aktiv, damit "Turbo-Schein auf NVDA" weiter blockt.
_AMBIGUOUS_INSTRUMENT_KW = {"2x", "3x", "option", "margin", "turbo", "futures", "leverage"}


def _kw_hit(kw: str, text: str) -> bool:
    """Keyword-Match mit Wortgrenzen — 'hebel' trifft 'Hebel-ETF', aber nicht mehr
    'Hebelwirkung' im Reasoning. Deutsche Komposita ohne Bindestrich (Optionsschein,
    Hebelprodukt) brauchen dafür ein eigenes Keyword in der Match-Liste."""
    return re.search(r"(?<!\w)" + re.escape(kw.lower()) + r"(?!\w)", text.lower()) is not None


def _ticker_ccy(ticker: str) -> str:
    """Quote-Währung aus Ticker (konsistent mit web/app.py:_ticker_currency).
    Nur EUR/USD werden für die Mandats-Umrechnung exakt behandelt."""
    if not ticker:
        return "USD"
    tk = ticker.upper()
    if tk.endswith(_EUR_SUFFIXES) or tk.startswith(_EUR_ISIN_PREFIXES):
        return "EUR"
    if tk.endswith(".L"):
        return "GBP"
    if tk.endswith((".SW", ".VX")):
        return "CHF"
    if tk.endswith((".TO", ".V")):
        return "CAD"
    return "USD"


# ─── Laden / Speichern ───────────────────────────────────────

def load_mandate() -> dict | None:
    """Lädt config/mandate.json. None wenn Datei fehlt (Feature ist opt-in) oder kaputt."""
    if not MANDATE_PATH.exists():
        return None
    try:
        with open(MANDATE_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.error("mandate.json konnte nicht geladen werden: %s", e)
        return None


def validate_mandate_schema(mandate: dict) -> tuple[bool, str]:
    """Prüft Pflichtfelder + bekannte Regel-Typen. (ok, fehler_text)."""
    if not isinstance(mandate, dict):
        return False, "Mandat ist kein Objekt"
    rules = mandate.get("hard_rules", [])
    if not isinstance(rules, list):
        return False, "hard_rules muss eine Liste sein"
    for r in rules:
        if not isinstance(r, dict):
            return False, "Jede Regel muss ein Objekt sein"
        rtype = r.get("type")
        if rtype not in KNOWN_RULE_TYPES:
            return False, f"Unbekannter Regel-Typ: {rtype!r} (erlaubt: {sorted(KNOWN_RULE_TYPES)})"
        if r.get("rule") not in ("block", "warn"):
            return False, f"Regel {r.get('id', rtype)}: rule muss 'block' oder 'warn' sein"
    return True, ""


def save_mandate(new_mandate: dict, change_summary: str = "") -> dict:
    """Validiert, backupt die alte Version, schreibt atomar, erhöht version + change_log.

    Raises ValueError bei Schema-Verstoss (Caller fängt das ab — niemals roh schreiben)."""
    ok, err = validate_mandate_schema(new_mandate)
    if not ok:
        raise ValueError(f"Mandat-Schema ungültig: {err}")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    old = load_mandate()
    old_version = (old or {}).get("version", 0)
    if old is not None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            with open(BACKUP_DIR / f"mandate.v{old_version}.{ts}.json", "w") as f:
                json.dump(old, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Mandat-Backup fehlgeschlagen: %s", e)

    new_mandate["version"] = old_version + 1
    new_mandate["updated_at"] = datetime.now().isoformat(timespec="seconds")
    log = new_mandate.setdefault("change_log", [])
    log.append({
        "version": new_mandate["version"],
        "at": new_mandate["updated_at"],
        "summary": change_summary or "Mandat aktualisiert",
    })
    new_mandate["change_log"] = log[-20:]

    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".mandate.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(new_mandate, f, indent=2, ensure_ascii=False)
        os.replace(tmp, MANDATE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("Mandat v%s gespeichert: %s", new_mandate["version"], change_summary)
    return new_mandate


# ─── Prompt-Rendering ────────────────────────────────────────

def _rule_text(r: dict) -> str:
    """Eine hard_rule als kurzer deutscher Prompt-Satz."""
    t = r.get("type")
    if t == "forbidden_ticker":
        tks = ", ".join(r.get("tickers", [])) or "—"
        return f"gesperrte Ticker: {tks}"
    if t == "forbidden_instrument":
        kw = ", ".join(r.get("match", [])) or "—"
        return f"verbotene Instrumente (Stichworte): {kw}"
    if t == "max_position_pct":
        txt = f"max {r.get('value')}% je Einzelposition (vom investierten Kapital)"
        exceptions = r.get("exceptions") or {}
        if exceptions:
            txt += f" — Ausnahmen: {', '.join(exceptions)}"
        return txt
    if t == "min_cash_pct":
        return f"min {r.get('value')}% Cash (vom Gesamtvermögen)"
    if t == "max_keyword_pct":
        return f"max {r.get('value')}% in {'/'.join(r.get('keywords', []))} (vom investierten Kapital)"
    if t == "max_sector_pct":
        return f"max {r.get('value')}% im Sektor {r.get('sector')} (vom investierten Kapital)"
    return t or "?"


def build_mandate_block(mandate: dict | None) -> str:
    """Rendert das Mandat als §0-Block für den System-/Briefing-Prompt.
    Gibt "" zurück wenn kein Mandat (opt-in)."""
    if not mandate:
        return ""
    rules = mandate.get("hard_rules", [])
    block = [r for r in rules if r.get("rule") == "block"]
    warn = [r for r in rules if r.get("rule") == "warn"]
    lines = [
        f"=== §0 DEIN ANLAGE-MANDAT v{mandate.get('version', 1)} (oberste Direktive — schlägt alle folgenden Regeln) ===",
    ]
    if mandate.get("summary_human"):
        lines.append(mandate["summary_human"])
    if mandate.get("philosophy"):
        lines.append(f"Philosophie: {mandate['philosophy']}")
    if block:
        lines.append("HARTE REGELN (block, NICHT vorschlagen wenn verletzt): " + " · ".join(_rule_text(r) for r in block))
    if warn:
        lines.append("WEICHE REGELN (warn, nur mit Begründung abweichen): " + " · ".join(_rule_text(r) for r in warn))
    targets = mandate.get("targets") or {}
    if targets.get("regions"):
        reg = ", ".join(f"{k} {v}%" for k, v in targets["regions"].items())
        cash = f" · Cash {targets['cash_pct']}%" if targets.get("cash_pct") is not None else ""
        lines.append(f"SOLL-ALLOKATION (Ziel, nicht hart): {reg}{cash}")
    if mandate.get("single_trade_cap_pct"):
        lines.append(f"ORDER-GRÖSSE: einzelne Order max {mandate['single_trade_cap_pct']}% des Gesamtvermögens")
    frozen = mandate.get("frozen_tickers") or {}
    if frozen:
        items = "; ".join(f"{tk} ({why})" if why else tk for tk, why in frozen.items())
        lines.append(f"EINGEFROREN (halten ok, NICHT aufstocken, KEIN Verkaufsdruck — die bestehende Grösse "
                     f"ist bewusst akzeptiert, schlage weder Zukauf noch erzwungenen Abbau vor): {items}")
    for pref in (mandate.get("soft_preferences") or [])[:6]:
        lines.append(f"  - Präferenz: {pref}")
    for tax in (mandate.get("tax_directives") or [])[:4]:
        lines.append(f"  - Steuer: {tax}")
    lines.append("Verstößt eine Idee gegen eine BLOCK-Regel → schlage sie NICHT vor, erkläre kurz warum. "
                 "Bei WARN-Regeln nur mit expliziter Begründung im reasoning abweichen. "
                 "Die Soll-Allokation ist Orientierung, KEIN Rebalancing-Zwang — eine Abweichung allein "
                 "(z.B. eine hohe Cash-Quote) ist kein Grund für eine Order, solange keine überzeugende "
                 "Einzelidee dahintersteht. Lieber Cash halten als auf Krampf investieren.")
    return "\n".join(lines)


# ─── Validierung von Empfehlungen ────────────────────────────

def _entry_value_eur(rec: dict, overview: dict) -> float | None:
    """EUR-Wert eines (hypothetischen) Kaufs: shares × entry_price, korrekt umgerechnet.
    None wenn nicht berechenbar (fehlende shares/price oder Währung ohne Kurs)."""
    shares = rec.get("shares")
    price = rec.get("entry_price")
    if not shares or not price:
        return None
    ccy = _ticker_ccy(rec.get("ticker", ""))
    if ccy == "EUR":
        return float(shares) * float(price)
    if ccy == "USD":
        eur_usd = overview.get("eur_usd_rate")
        if not eur_usd:
            return None
        return float(shares) * float(price) / eur_usd
    # GBP/CHF/CAD: kein verlässlicher Kurs → nicht berechenbar (lieber nicht blocken)
    return None


def validate_against_mandate(rec: dict, mandate: dict | None, overview: dict | None) -> tuple[str, list[str]]:
    """Prüft EINE Empfehlung gegen das Mandat.

    Returns (verdict, violations) mit verdict ∈ {"pass","warn","block"}.
    - block: Empfehlung NICHT speichern.
    - warn:  speichern, aber rec["mandate_warnings"] setzen.
    sell läuft IMMER durch (Risikoabbau ist nie ein Mandatsverstoss).
    Fehlt Datengrundlage für eine Regel → Regel überspringen (nie fälschlich blocken).

    Bezugsgrössen: Konzentrations-Limits (Position/Sektor/Keyword) rechnen auf das
    INVESTIERTE Kapital — bei hoher Cash-Quote wäre "% vom Gesamtvermögen" trügerisch
    lax (12% von total sind bei 44% Cash real >21% des Depots). Cash-Regeln und der
    single_trade_cap rechnen auf das Gesamtvermögen.
    """
    if not mandate:
        return "pass", []
    action = rec.get("action")
    if action == "sell":
        return "pass", []

    from src.web.services.portfolio_service import _norm_sector

    ticker = (rec.get("ticker") or "").upper()
    name = (rec.get("name") or "")
    reasoning = (rec.get("reasoning") or "")
    haystack = f"{ticker} {name} {reasoning}".lower()
    # Instrument-Haystack OHNE Reasoning: forbidden_instrument prüft, WAS gekauft wird
    # (Ticker/Name), nicht wie die Begründung formuliert ist. Mehrdeutige Keywords wie
    # "2x", "option" oder "margin" sind in Analyse-Prosa Alltag ("Risk/Reward 2x",
    # "Stop bei 2x ATR" — was der Briefing-Prompt sogar selbst verlangt) und haben so
    # nachweislich valide Empfehlungen geblockt (ASML 15.06., GOOGL 06.07. + 23.07.).
    instrument_haystack = f"{ticker} {name}".lower()

    # Eingefrorene Positionen: halten ja, aufstocken nein. buy/watch (= Aufstock- oder
    # Wiedereinstiegs-Order) werden geblockt; hold (halten/Stop nachziehen) und sell
    # (oben schon durch) bleiben erlaubt. Die bestehende Grösse zählt NICHT als Verstoss
    # — der Strategie-Drift überspringt eingefrorene Titel ebenfalls (bewusster Stillstand,
    # kein Rebalancing-Druck). Anders als eine max_position_pct-exception, die Aufstocken
    # erlauben würde.
    frozen = {k.upper(): v for k, v in (mandate.get("frozen_tickers") or {}).items()}
    if ticker in frozen and action in ("buy", "watch"):
        return "block", [f"{ticker} ist eingefroren ({frozen[ticker] or 'halten, nicht aufstocken'})"]

    overview = overview or {}
    total = overview.get("total_value_eur") or 0
    invested = total - (overview.get("cash_total") or 0)
    # Gleicher Ticker kann in mehreren Depots liegen (z.B. AMZN auf TR + Erste Bank):
    # Werte über alle Depots summieren, Metadaten (Sektor) vom ersten Treffer.
    positions = {}
    value_by_ticker = {}
    for p in overview.get("positions", []):
        tk = (p.get("ticker") or "").upper()
        positions.setdefault(tk, p)
        value_by_ticker[tk] = value_by_ticker.get(tk, 0) + (p.get("current_value_eur") or 0)

    block_violations = []
    warn_violations = []

    for r in mandate.get("hard_rules", []):
        t = r.get("type")
        is_block = r.get("rule") == "block"
        bucket = block_violations if is_block else warn_violations

        if t == "forbidden_ticker":
            banned = {x.upper() for x in r.get("tickers", [])}
            base = ticker.split(".")[0]
            if ticker in banned or base in banned:
                bucket.append(f"Ticker {ticker} ist gesperrt")

        elif t == "forbidden_instrument":
            for kw in r.get("match", []):
                # Mehrdeutige Keywords nur gegen Ticker/Name prüfen, eindeutige
                # Hebel-Begriffe weiter gegen den ganzen Text (siehe _AMBIGUOUS_KW).
                hay = instrument_haystack if kw.lower() in _AMBIGUOUS_INSTRUMENT_KW else haystack
                if _kw_hit(kw, hay):
                    bucket.append(f"verbotenes Instrument (Stichwort '{kw}')")
                    break

        elif t == "max_position_pct":
            limit = r.get("value")
            exceptions = r.get("exceptions") or {}
            if limit is None or ticker in {k.upper() for k in exceptions} or not total:
                continue
            added = _entry_value_eur(rec, overview)
            if added is None:
                continue  # nicht berechenbar → nicht blocken
            existing = value_by_ticker.get(ticker, 0)
            base = invested + added
            if base <= 0:
                continue
            new_pct = (existing + added) / base * 100
            if new_pct > limit:
                bucket.append(f"{ticker} wäre {new_pct:.1f}% > max {limit}% je Einzelposition (investiert)")

        elif t == "min_cash_pct":
            limit = r.get("value")
            cash = overview.get("cash_total")
            if limit is None or cash is None or not total:
                continue
            added = _entry_value_eur(rec, overview)
            if added is None:
                continue
            new_cash_pct = (cash - added) / total * 100
            if new_cash_pct < limit:
                bucket.append(f"Cash fiele auf {new_cash_pct:.1f}% < min {limit}%")

        elif t == "max_keyword_pct":
            limit = r.get("value")
            kws = [k.lower() for k in r.get("keywords", [])]
            if limit is None or not total or not kws:
                continue
            added = _entry_value_eur(rec, overview) or 0
            cur = sum(
                (p.get("current_value_eur") or 0)
                for p in overview.get("positions", [])
                if any(_kw_hit(k, f"{(p.get('ticker') or '')} {(p.get('name') or '')}") for k in kws)
            )
            adds_to_bucket = any(_kw_hit(k, haystack) for k in kws)
            base = invested + (added if adds_to_bucket else 0)
            new_pct = (cur + (added if adds_to_bucket else 0)) / base * 100 if base > 0 else 0
            if adds_to_bucket and new_pct > limit:
                bucket.append(f"{'/'.join(kws)} wäre {new_pct:.1f}% > max {limit}% (investiert)")

        elif t == "max_sector_pct":
            limit = r.get("value")
            sector = r.get("sector")
            if limit is None or not sector or not total:
                continue
            # Sektor-Labels kanonisieren: Positionen tragen yfinance-Englisch
            # ("Technology"), der Breakdown nach Fonds-Durchschau deutschen Kanon
            # ("Technologie") — ohne Normierung war diese Regel faktisch tot.
            want = _norm_sector(sector)
            pos = positions.get(ticker)
            rec_sector = _norm_sector((pos or {}).get("sector") or "")
            if rec_sector == "Unbekannt" or rec_sector != want:
                continue  # Sektor der Empfehlung unbekannt/anders → nicht prüfbar
            breakdown = overview.get("sector_breakdown") or {}
            cur = breakdown.get(want)
            if cur is None:
                cur = sum(v for k, v in breakdown.items() if _norm_sector(k) == want)
            added = _entry_value_eur(rec, overview) or 0
            base = invested + added
            if base <= 0:
                continue
            new_pct = (cur + added) / base * 100
            if new_pct > limit:
                bucket.append(f"Sektor {want} wäre {new_pct:.1f}% > max {limit}% (investiert)")

    # Ordergrössen-Deckel (Top-Level-Feld, kein hard_rule-Typ): bremst Klumpen-Orders,
    # ohne sie hart zu verbieten — Verstoss ist immer nur eine Warnung.
    cap = mandate.get("single_trade_cap_pct")
    if cap and total:
        added = _entry_value_eur(rec, overview)
        if added is not None and added / total * 100 > cap:
            warn_violations.append(
                f"Ordergrösse {added:.0f}€ wäre {added / total * 100:.1f}% > max {cap}% je Trade")

    if block_violations:
        return "block", block_violations + warn_violations
    if warn_violations:
        return "warn", warn_violations
    return "pass", []


# ─── Strategie-Drift (Soll vs. Ist) ──────────────────────────

DRIFT_WARN_PP = 5.0    # Abweichung in Prozentpunkten ab der gewarnt wird
DRIFT_BREACH_PP = 10.0  # … ab der es eine echte Abweichung ist


def _severity(dev_pp: float) -> str:
    a = abs(dev_pp)
    if a > DRIFT_BREACH_PP:
        return "breach"
    if a > DRIFT_WARN_PP:
        return "warn"
    return "ok"


def compute_strategy_drift(overview: dict | None, mandate: dict | None) -> dict | None:
    """Deterministische Soll-vs-Ist-Abweichung (kein LLM). None wenn kein Mandat/Overview.

    Vergleicht die Ist-Allokation (aus compute_portfolio_overview) mit den targets +
    max_position_pct des Mandats. Liefert eine Liste von Dimensionen mit severity.
    """
    if not mandate or not overview:
        return None
    total = overview.get("total_value_eur") or 0
    if not total:
        return None

    dims = []
    targets = mandate.get("targets") or {}

    # Region-Drift (Ist = % der investierten Summe; region_exposure sind EUR-Werte)
    soll_regions = targets.get("regions") or {}
    if soll_regions:
        region_vals = overview.get("region_exposure") or {}
        region_total = sum(region_vals.values()) or 0
        if region_total:
            for region, soll in soll_regions.items():
                ist = region_vals.get(region, 0) / region_total * 100
                dev = ist - soll
                dims.append({
                    "name": region, "kind": "region",
                    "soll": round(soll, 1), "ist": round(ist, 1),
                    "abweichung_pp": round(dev, 1), "severity": _severity(dev),
                })
            # Ist-Kategorien ohne Soll (z.B. Rohstoffe, wenn das Mandat sie nicht
            # kennt) mit Soll=0 ausweisen — sonst drücken sie still alle anderen
            # Ist-Quoten und erzeugen Phantom-Untergewichte.
            for region, val in region_vals.items():
                if region in soll_regions or not val:
                    continue
                ist = val / region_total * 100
                dims.append({
                    "name": region, "kind": "region",
                    "soll": 0, "ist": round(ist, 1),
                    "abweichung_pp": round(ist, 1), "severity": _severity(ist),
                })

    # Cash-Drift (Ist = % vom Gesamtvermögen)
    if targets.get("cash_pct") is not None:
        ist_cash = (overview.get("cash_total") or 0) / total * 100
        dev = ist_cash - targets["cash_pct"]
        dims.append({
            "name": "Cash", "kind": "cash",
            "soll": round(targets["cash_pct"], 1), "ist": round(ist_cash, 1),
            "abweichung_pp": round(dev, 1), "severity": _severity(dev),
        })

    # Einzelpositions-Übergewicht vs. max_position_pct — auf das INVESTIERTE Kapital
    # (konsistent mit validate_against_mandate), über Depots aggregiert, und mit
    # denselben Ausnahmen wie der Validator (sonst meldet der Drift ewig den
    # bewusst grossen Welt-Kern als Verstoss). Eingefrorene Titel zählen ebenfalls
    # als akzeptiert: bewusster Stillstand soll keinen Verkaufsdruck erzeugen.
    max_pos_rule = next((r for r in mandate.get("hard_rules", []) if r.get("type") == "max_position_pct"), None)
    invested = total - (overview.get("cash_total") or 0)
    if max_pos_rule and max_pos_rule.get("value") and invested > 0:
        limit = max_pos_rule["value"]
        exceptions = {k.upper() for k in (max_pos_rule.get("exceptions") or {})}
        exceptions |= {k.upper() for k in (mandate.get("frozen_tickers") or {})}
        agg = {}
        for p in overview.get("positions", []):
            tk = (p.get("ticker") or "").upper()
            entry = agg.setdefault(tk, {"name": p.get("name"), "ticker": p.get("ticker"), "value": 0.0})
            entry["value"] += (p.get("current_value_eur") or 0)
        for tk, entry in agg.items():
            if tk in exceptions:
                continue
            pct = entry["value"] / invested * 100
            if pct > limit:
                dims.append({
                    "name": f"{entry['name']} ({entry['ticker']})", "kind": "position",
                    "soll": round(limit, 1), "ist": round(pct, 1),
                    "abweichung_pp": round(pct - limit, 1), "severity": "breach",
                })

    breaches = sum(1 for d in dims if d["severity"] == "breach")
    warnings = sum(1 for d in dims if d["severity"] == "warn")
    status = "breach" if breaches else ("warn" if warnings else "ok")
    return {
        "dimensions": dims,
        "breaches": breaches,
        "warnings": warnings,
        "status": status,
    }
