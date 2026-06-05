"""
Durchschau / Look-Through — Research zur Zusammensetzung von Fonds, ETFs, Anleihen.

yfinance liefert für (v.a. österreichische) Fonds, Laufzeitfonds und Anleihen weder
Kurs noch Zusammensetzung — Velora ist für diese Positionen sonst blind. Dieses Modul
lässt Claude (web-augmentiert über Brave) jede Fonds-/ETF-/Anleihen-Position recherchieren
und in eine strukturierte Tabelle (config/holdings_research.json) eintragen: Asset-Klasse,
Top-Holdings (zum Zerlegen in Einzeltitel), Sektor-/Region-Split, bei Anleihen Emittent/
Laufzeit/Rating/Duration. Daraus wird die ECHTE Exposure (Fonds-Durchschau + Direktbestand
kombiniert) berechnet.

Persistenz wie region_exposure.json: gitignored Laufzeitdaten, bleibt bei Deploy erhalten.
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
RESEARCH_PATH = CONFIG_DIR / "holdings_research.json"

# Re-Research wenn älter als das (Holdings/Factsheets ändern sich langsam).
STALE_DAYS = 90

# Hinweis-Stichworte im Positionsnamen, die auf einen Fonds/ETF/Bond/ETC deuten.
_FUND_HINTS = (
    "etf", "etc", "fonds", "fund", "ucits", "index", "msci", "s&p", "stoxx",
    "laufzeitfonds", "bond", "anleihe", "treasury", "aggregate", "ftse",
    "nasdaq-100", "physical gold", "physical silver", "dividend", "responsible",
    "nachhaltig", "global stock", "world", "emerging",
)


# ─── Erkennung ───────────────────────────────────────────────

def needs_lookthrough(name: str, ticker: str, isin: str) -> bool:
    """True wenn die Position ein Fonds/ETF/ETC/Bond ist (Durchschau sinnvoll),
    False für Einzelaktien (yfinance liefert dort genug)."""
    n = (name or "").lower()
    if any(h in n for h in _FUND_HINTS):
        return True
    # Österreichische Fonds nutzen die ISIN als "Ticker" (z.B. AT0000646799).
    if ticker and isin and ticker.strip().upper() == isin.strip().upper():
        return True
    return False


# ─── Persistenz ──────────────────────────────────────────────

def load_holdings_research() -> dict:
    if not RESEARCH_PATH.exists():
        return {}
    try:
        with open(RESEARCH_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.error("holdings_research.json laden fehlgeschlagen: %s", e)
        return {}


def save_holdings_research(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".holdings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, RESEARCH_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _is_stale(entry: dict) -> bool:
    ts = (entry or {}).get("researched_at")
    if not ts:
        return True
    try:
        age = (datetime.now() - datetime.fromisoformat(ts)).days
        return age >= STALE_DAYS
    except (ValueError, TypeError):
        return True


# ─── Web-Fetch (best-effort) ─────────────────────────────────

def _fetch_url_text(url: str, max_chars: int = 5000) -> str:
    """Holt eine HTML-Seite und strippt sie zu Plaintext (best-effort, kurzer Timeout)."""
    try:
        import requests
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (Velora research)"})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


# ─── Research ────────────────────────────────────────────────

_RESEARCH_SYSTEM = (
    "Du bist ein Fonds-/Wertpapieranalyst. Du recherchierst die Zusammensetzung von Fonds, "
    "ETFs und Anleihen und gibst sie als striktes JSON aus. Du erfindest keine exakten Gewichte — "
    "wenn du unsicher bist, schätzt du konservativ und setzt confidence niedrig. Antworte NUR mit "
    "dem JSON-Block."
)

_RESEARCH_SCHEMA_HINT = """Gib NUR einen ```json ... ``` Block zurück mit:
{
  "instrument_type": "etf" | "fund" | "bond_fund" | "bond" | "commodity" | "stock" | "unknown",
  "asset_class": "equity" | "bond" | "commodity" | "mixed" | "cash",
  "ter_pct": Zahl oder null,
  "summary": "1-2 Sätze: was ist das, Strategie, ungefähre Titelzahl",
  "confidence": "high" | "medium" | "low",
  "source": "woher die Daten stammen (z.B. justETF, Erste AM Factsheet, Schätzung)",
  "top_holdings": [ {"name": "...", "ticker": "... oder null", "weight_pct": Zahl}, ... bis ~12 ],
  "sector_breakdown": {"Technology": Zahl, ...},          // in Prozent, Summe ~100
  "region_breakdown": {"USA": Zahl, "Europa": Zahl, "Asien": Zahl, "Sonstige": Zahl},
  "bond": {"issuer": "...", "type": "government|corporate|mixed", "avg_maturity": "Jahr/Datum",
           "avg_rating": "z.B. A", "duration_years": Zahl, "currency": "EUR"}   // nur bei bond/bond_fund, sonst null
}
Bei einer reinen Einzelaktie: instrument_type="stock", asset_class="equity", top_holdings=[].
Regionen-Summe = 100. Bei einem Laufzeitfonds/Rentenfonds: asset_class="bond", fülle das "bond"-Objekt."""


def research_holding(name: str, isin: str, ticker: str, brave_key: str = "") -> dict | None:
    """Recherchiert eine einzelne Position (web-augmentiert) → strukturiertes Dict.
    Gibt None bei hartem Fehler (Caller behält dann den alten Eintrag)."""
    from src.analysis.claude import ask_claude, extract_json_block, ClaudeCLIError
    from src.data.news import search_brave

    # 1. Websuche nach Factsheet/Holdings
    web_context = ""
    if brave_key:
        query = f"{name} {isin} Fonds ETF Zusammensetzung holdings factsheet"
        results = search_brave(query, brave_key, count=6, freshness="py")
        if results:
            snippets = [f"- {r['title']}: {r['description']} [{r.get('url','')}]" for r in results]
            web_context = "SUCHERGEBNISSE:\n" + "\n".join(snippets)
            # Top-1-HTML-Seite best-effort nachladen für mehr Detail
            for r in results[:2]:
                page = _fetch_url_text(r.get("url", ""))
                if page:
                    web_context += f"\n\nSEITENINHALT ({r.get('url')}):\n{page}"
                    break

    prompt = (
        f"Recherchiere die Zusammensetzung dieser Portfolio-Position:\n"
        f"Name: {name}\nISIN: {isin}\nTicker: {ticker}\n\n"
        f"{web_context or '(Keine Websuche verfügbar — nutze dein Wissen, confidence niedriger.)'}\n\n"
        f"{_RESEARCH_SCHEMA_HINT}"
    )

    try:
        result = ask_claude(_RESEARCH_SYSTEM, prompt, timeout=300)
    except ClaudeCLIError as e:
        logger.error("Research für %s (%s) fehlgeschlagen: %s", name, isin, e)
        return None

    data = extract_json_block(result.get("text", ""))
    if not isinstance(data, dict):
        logger.warning("Research für %s: kein valides JSON", name)
        return None

    data["name"] = name
    data["isin"] = isin
    data["ticker"] = ticker
    data["researched_at"] = datetime.now().isoformat(timespec="seconds")
    return data


def research_portfolio_holdings(portfolio: dict, settings: dict, force: bool = False,
                                only_isin: str | None = None) -> dict:
    """Recherchiert alle Fonds/ETF/Bond-Positionen, die noch keine (frische) Research haben.
    Gibt die aktualisierte Research-Tabelle zurück. Läuft seriell (Claude-Lock)."""
    research = load_holdings_research()
    brave_key = (settings.get("brave_search", {}) or {}).get("api_key", "")

    candidates = []
    seen = set()
    for acc in portfolio.get("accounts", {}).values():
        for pos in acc.get("positions", []):
            isin = (pos.get("isin") or "").strip()
            name = pos.get("name", "")
            ticker = pos.get("ticker", "")
            key = isin or ticker or name
            if not key or key in seen:
                continue
            if only_isin and key != only_isin:
                continue
            if not needs_lookthrough(name, ticker, isin):
                continue
            if not force and not _is_stale(research.get(key)):
                continue
            seen.add(key)
            candidates.append((key, name, isin, ticker))

    logger.info("Holdings-Research: %d Kandidaten", len(candidates))
    for key, name, isin, ticker in candidates:
        logger.info("Recherchiere %s (%s)...", name, isin)
        data = research_holding(name, isin, ticker, brave_key)
        if data:
            research[key] = data
            save_holdings_research(research)  # inkrementell speichern (Fortschritt sichern)

    return research


# ─── Look-Through-Exposure ───────────────────────────────────

def _position_value_eur(pos: dict, market_data: dict, eur_usd: float) -> float:
    """EUR-Wert einer Position (Live-Kurs, sonst Einstand)."""
    shares = pos.get("shares", 0) or 0
    ticker = pos.get("ticker")
    currency = pos.get("currency", "EUR")
    price = None
    if ticker:
        price = (market_data.get("positions", {}).get(ticker, {}).get("price", {}) or {}).get("current_price")
    if price:
        price_eur = price if currency == "EUR" else price / (eur_usd or 1.0)
        return shares * price_eur
    # Fallback: Einstandswert
    buy_in_eur = pos.get("buy_in_eur") or pos.get("buy_in", 0)
    return shares * (buy_in_eur or 0)


def compute_lookthrough(portfolio: dict, market_data: dict, research: dict | None = None) -> dict:
    """Berechnet die ECHTE Exposure: Fonds werden über ihre Top-Holdings in Einzeltitel
    zerlegt und mit dem Direktbestand kombiniert. Liefert Asset-Klassen-Split, echte
    Einzeltitel-Top-Exposure und Region-/Sektor-Durchschau."""
    research = research if research is not None else load_holdings_research()
    from src.data.fx import safe_eur_usd
    eur_usd = safe_eur_usd(market_data)
    # Region-Map für Direktaktien (gleiche Quelle wie Dashboard)
    try:
        from src.web.services.portfolio_service import _load_region_exposure
        region_map = _load_region_exposure()
    except Exception:
        region_map = {}

    asset_class = {}        # equity/bond/commodity/mixed/cash -> EUR
    titles = {}             # Einzeltitel-Name -> EUR (direkt + durchgerechnet)
    regions = {}            # Region -> EUR
    sectors = {}            # Sektor -> EUR
    fund_count = 0
    researched_funds = 0
    total_invested = 0.0

    for acc in portfolio.get("accounts", {}).values():
        for pos in acc.get("positions", []):
            val = _position_value_eur(pos, market_data, eur_usd)
            if val <= 0:
                continue
            total_invested += val
            isin = (pos.get("isin") or "").strip()
            ticker = pos.get("ticker", "")
            name = pos.get("name", "")
            key = isin or ticker or name
            entry = research.get(key)
            is_fund = needs_lookthrough(name, ticker, isin)

            if is_fund:
                fund_count += 1
            if is_fund and entry:
                researched_funds += 1
                ac = entry.get("asset_class", "mixed")
                asset_class[ac] = asset_class.get(ac, 0) + val
                # Region/Sektor des Fonds gewichtet
                for reg, pct in (entry.get("region_breakdown") or {}).items():
                    regions[reg] = regions.get(reg, 0) + val * (pct or 0) / 100
                for sec, pct in (entry.get("sector_breakdown") or {}).items():
                    sectors[sec] = sectors.get(sec, 0) + val * (pct or 0) / 100
                # Top-Holdings in Einzeltitel zerlegen
                holdings = entry.get("top_holdings") or []
                covered = 0.0
                for h in holdings:
                    w = (h.get("weight_pct") or 0) / 100
                    if w <= 0:
                        continue
                    covered += w
                    titles[h.get("name", "?")] = titles.get(h.get("name", "?"), 0) + val * w
                rest = max(0.0, 1 - covered)
                if rest > 0.01:
                    label = f"Übrige Titel ({name})"
                    titles[label] = titles.get(label, 0) + val * rest
            else:
                # Einzelaktie (oder Fonds ohne Research): direkt zählen
                asset_class["equity" if not is_fund else "mixed"] = \
                    asset_class.get("equity" if not is_fund else "mixed", 0) + val
                titles[name] = titles.get(name, 0) + val
                # Sektor aus market_data
                sec = (market_data.get("positions", {}).get(ticker, {}).get("price", {}) or {}).get("sector")
                if sec:
                    sectors[sec] = sectors.get(sec, 0) + val
                # Region aus region_exposure.json (Direktaktien), sonst ISIN-Fallback
                rmap = region_map.get(ticker) or region_map.get(isin)
                if rmap:
                    for reg, pct in rmap.items():
                        regions[reg] = regions.get(reg, 0) + val * (pct or 0) / 100
                elif isin[:2]:
                    fb = {"US": "USA", "DE": "Europa", "AT": "Europa", "NL": "Europa", "FR": "Europa",
                          "IE": "Europa", "GB": "Europa", "CH": "Europa", "JP": "Asien", "CN": "Asien"}
                    regions[fb.get(isin[:2], "Sonstige")] = regions.get(fb.get(isin[:2], "Sonstige"), 0) + val

    # Cash als eigene Asset-Klasse
    cash = sum(a.get("value", 0) for a in portfolio.get("bank_accounts", {}).values())
    if cash:
        asset_class["cash"] = asset_class.get("cash", 0) + cash
    grand_total = total_invested + cash

    def to_pct_sorted(d, base):
        return [
            {"name": k, "value_eur": round(v, 2), "pct": round(v / base * 100, 1) if base else 0}
            for k, v in sorted(d.items(), key=lambda x: x[1], reverse=True)
        ]

    return {
        "asset_class": to_pct_sorted(asset_class, grand_total),
        "top_titles": to_pct_sorted(titles, total_invested)[:20],
        "regions": to_pct_sorted(regions, total_invested),
        "sectors": to_pct_sorted(sectors, total_invested),
        "fund_count": fund_count,
        "researched_funds": researched_funds,
        "unresearched_funds": fund_count - researched_funds,
        "total_invested_eur": round(total_invested, 2),
        "grand_total_eur": round(grand_total, 2),
    }
