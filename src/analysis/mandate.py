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
        return f"max {r.get('value')}% je Einzelposition (vom Gesamtvermögen)"
    if t == "min_cash_pct":
        return f"min {r.get('value')}% Cash"
    if t == "max_keyword_pct":
        return f"max {r.get('value')}% in {'/'.join(r.get('keywords', []))}"
    if t == "max_sector_pct":
        return f"max {r.get('value')}% im Sektor {r.get('sector')}"
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
    for pref in (mandate.get("soft_preferences") or [])[:6]:
        lines.append(f"  - Präferenz: {pref}")
    for tax in (mandate.get("tax_directives") or [])[:4]:
        lines.append(f"  - Steuer: {tax}")
    lines.append("Verstößt eine Idee gegen eine BLOCK-Regel → schlage sie NICHT vor, erkläre kurz warum. "
                 "Bei WARN-Regeln nur mit expliziter Begründung im reasoning abweichen. "
                 "Bevorzuge Aktionen, die das Depot näher an die Soll-Allokation bringen.")
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
    """
    if not mandate:
        return "pass", []
    action = rec.get("action")
    if action == "sell":
        return "pass", []

    ticker = (rec.get("ticker") or "").upper()
    name = (rec.get("name") or "")
    reasoning = (rec.get("reasoning") or "")
    haystack = f"{ticker} {name} {reasoning}".lower()
    overview = overview or {}
    total = overview.get("total_value_eur") or 0
    positions = {(p.get("ticker") or "").upper(): p for p in overview.get("positions", [])}

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
                if kw.lower() in haystack:
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
            existing = positions.get(ticker, {}).get("current_value_eur", 0) or 0
            new_pct = (existing + added) / total * 100
            if new_pct > limit:
                bucket.append(f"{ticker} wäre {new_pct:.1f}% > max {limit}% je Einzelposition")

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
                if any(k in f"{(p.get('ticker') or '')} {(p.get('name') or '')}".lower() for k in kws)
            )
            adds_to_bucket = any(k in haystack for k in kws)
            new_pct = (cur + (added if adds_to_bucket else 0)) / total * 100
            if adds_to_bucket and new_pct > limit:
                bucket.append(f"{'/'.join(kws)} wäre {new_pct:.1f}% > max {limit}%")

        elif t == "max_sector_pct":
            limit = r.get("value")
            sector = r.get("sector")
            if limit is None or not sector or not total:
                continue
            pos = positions.get(ticker)
            rec_sector = (pos or {}).get("sector")
            if not rec_sector or rec_sector != sector:
                continue  # Sektor der Empfehlung unbekannt/anders → nicht prüfbar
            cur = (overview.get("sector_breakdown") or {}).get(sector, 0)
            added = _entry_value_eur(rec, overview) or 0
            new_pct = (cur + added) / total * 100
            if new_pct > limit:
                bucket.append(f"Sektor {sector} wäre {new_pct:.1f}% > max {limit}%")

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

    # Cash-Drift (Ist = % vom Gesamtvermögen)
    if targets.get("cash_pct") is not None:
        ist_cash = (overview.get("cash_total") or 0) / total * 100
        dev = ist_cash - targets["cash_pct"]
        dims.append({
            "name": "Cash", "kind": "cash",
            "soll": round(targets["cash_pct"], 1), "ist": round(ist_cash, 1),
            "abweichung_pp": round(dev, 1), "severity": _severity(dev),
        })

    # Einzelpositions-Übergewicht vs. max_position_pct
    max_pos_rule = next((r for r in mandate.get("hard_rules", []) if r.get("type") == "max_position_pct"), None)
    if max_pos_rule and max_pos_rule.get("value"):
        limit = max_pos_rule["value"]
        for p in overview.get("positions", []):
            pct = (p.get("current_value_eur") or 0) / total * 100
            if pct > limit:
                dims.append({
                    "name": f"{p.get('name')} ({p.get('ticker')})", "kind": "position",
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
