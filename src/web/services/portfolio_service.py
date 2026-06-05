"""
Portfolio-Service: Berechnet strukturierte Portfolio-Daten für das Web-Dashboard.
Logik extrahiert aus prompt.py:build_portfolio_summary(), aber als Dicts statt Strings.
"""

import json
import logging
from pathlib import Path

from src.data.fx import safe_eur_usd

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"

# Display-Namen für Konten
ACCOUNT_DISPLAY_NAMES = {
    "trade_republic": "Trade Republic",
    "erste_bank": "Erste Bank",
    "interactive_brokers": "Interactive Brokers",
    "flatex": "Flatex",
    "scalable": "Scalable Capital",
}

# Index-Beschreibungen für die Markt-Seite
INDEX_DESCRIPTIONS = {
    "S&P 500": "US Large Cap",
    "NASDAQ": "US Tech",
    "DAX": "Deutschland 40",
    "ATX": "Österreich",
    "Euro Stoxx 50": "Europa Top 50",
    "Gold": "Edelmetall (XAU)",
    "BTC/USD": "Bitcoin",
    "EUR/USD": "Wechselkurs",
    "VIX": "Volatilitätsindex",
}


# Sektor-Bezeichnungen vereinheitlichen (yfinance vs. GICS/Fonds-Factsheets vs. deutsch)
_SECTOR_CANON = {
    "financial services": "Finanzen", "financials": "Finanzen", "finanzwesen": "Finanzen", "finanzen": "Finanzen",
    "technology": "Technologie", "information technology": "Technologie", "informationstechnologie": "Technologie",
    "technologie": "Technologie",
    "consumer cyclical": "Konsum (zyklisch)", "consumer discretionary": "Konsum (zyklisch)",
    "consumer defensive": "Konsum (defensiv)", "consumer staples": "Konsum (defensiv)",
    "communication services": "Kommunikation", "communication": "Kommunikation", "communications": "Kommunikation",
    "kommunikation": "Kommunikation", "kommunikationsdienste": "Kommunikation",
    "healthcare": "Gesundheit", "health care": "Gesundheit", "gesundheit": "Gesundheit", "gesundheitswesen": "Gesundheit",
    "industrials": "Industrie", "industrie": "Industrie",
    "energy": "Energie", "energie": "Energie",
    "materials": "Grundstoffe", "basic materials": "Grundstoffe", "grundstoffe": "Grundstoffe",
    "utilities": "Versorger", "versorger": "Versorger",
    "real estate": "Immobilien", "immobilien": "Immobilien",
}


def _norm_sector(name: str) -> str:
    """Vereinheitlicht Sektor-Bezeichnungen, damit yfinance- und Fonds-Labels zusammenfallen.
    Exakt-Match zuerst, dann Teilstring-Fallback für verbose/kombinierte Factsheet-Labels."""
    if not name:
        return "Unbekannt"
    key = name.strip().lower()
    if key in _SECTOR_CANON:
        return _SECTOR_CANON[key]
    if "gold" in key or "edelmetall" in key or "precious" in key:
        return "Rohstoffe"
    if "staples" in key or "nichtzyklisch" in key or ("defensiv" in key and "konsum" in key):
        return "Konsum (defensiv)"
    if "discretionary" in key or "cyclical" in key or "zyklisch" in key:
        return "Konsum (zyklisch)"
    if "communication" in key or "kommunikation" in key:
        return "Kommunikation"
    if "health" in key or "gesundheit" in key:
        return "Gesundheit"
    if "financ" in key or "finanz" in key:
        return "Finanzen"
    if "technolog" in key or key == "it":
        return "Technologie"
    if "industr" in key:
        return "Industrie"
    if "energ" in key:
        return "Energie"
    if "material" in key or "grundstoff" in key:
        return "Grundstoffe"
    if "utilit" in key or "versorg" in key:
        return "Versorger"
    if "real estate" in key or "immobil" in key:
        return "Immobilien"
    if "other" in key or "sonstig" in key or "diversif" in key or "übrige" in key:
        return "Sonstige"
    return name


def _load_region_exposure() -> dict:
    """Lädt Region-Exposure Mapping aus config/region_exposure.json."""
    path = CONFIG_DIR / "region_exposure.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        # _comment Key ignorieren
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def _save_region_exposure(data: dict):
    """Speichert Region-Exposure Mapping."""
    path = CONFIG_DIR / "region_exposure.json"
    save_data = {"_comment": "Region-Exposure pro Ticker in Prozent. Basierend auf Revenue-Herkunft, nicht Firmensitz."}
    save_data.update(data)
    with open(path, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False)


def update_region_on_trade(action: str, ticker: str, position_removed: bool = False):
    """Aktualisiert region_exposure.json nach einem Trade.
    Bei Kauf neuer Position: Claude CLI Research starten (async).
    Bei komplettem Verkauf: Ticker entfernen."""
    regions = _load_region_exposure()

    if action == "sell" and position_removed:
        if ticker in regions:
            del regions[ticker]
            _save_region_exposure(regions)
            logger.info(f"Region-Exposure: {ticker} entfernt (Position verkauft)")

    elif action == "buy" and ticker not in regions:
        # Neue Position → Region-Research im Hintergrund
        import threading
        threading.Thread(target=_research_region, args=(ticker,), daemon=True).start()


def _research_region(ticker: str):
    """Ruft Claude CLI auf um die Revenue-Region eines Tickers zu bestimmen."""
    try:
        from src.analysis.claude import ask_claude
        prompt = (
            f"Analysiere die Revenue-Verteilung von {ticker} nach Regionen. "
            f"Gib NUR ein JSON zurück im Format: "
            f'```json\n{{"USA": 50, "Europa": 25, "Asien": 20, "Sonstige": 5}}\n```\n'
            f"Die Regionen sind: USA, Europa, Asien, Rohstoffe (nur für Rohstoff-ETCs/ETFs), Sonstige. "
            f"Prozente müssen sich auf 100 summieren. "
            f"Basiere auf dem tatsächlichen Revenue-Split, nicht auf dem Firmensitz."
        )
        result = ask_claude("Du bist ein Finanzanalyse-Assistent. Antworte NUR mit dem JSON-Block.", prompt)
        structured = result.get("structured")
        if structured and isinstance(structured, dict):
            # Validieren: Summe ~100
            total = sum(structured.values())
            if 95 <= total <= 105:
                regions = _load_region_exposure()
                regions[ticker] = structured
                _save_region_exposure(regions)
                logger.info(f"Region-Exposure: {ticker} → {structured}")
            else:
                logger.warning(f"Region-Research {ticker}: Summe {total} != 100, übersprungen")
        else:
            logger.warning(f"Region-Research {ticker}: Kein valides JSON von Claude")
    except Exception as e:
        logger.error(f"Region-Research {ticker} Fehler: {e}")


def load_portfolio() -> dict:
    """Lädt Portfolio aus config/portfolio.json."""
    path = CONFIG_DIR / "portfolio.json"
    if not path.exists():
        return {"accounts": {}, "bank_accounts": {}, "user_profile": {}}
    with open(path) as f:
        return json.load(f)


def load_watchlist() -> list:
    """Lädt Watchlist."""
    path = CONFIG_DIR / "watchlist.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def compute_portfolio_overview(portfolio: dict, market_data: dict) -> dict:
    """
    Berechnet vollständige Portfolio-Übersicht als strukturiertes Dict.
    Gibt zurück: total_value, holdings_value, cash, pnl, positions[], bank_accounts[], etc.
    """
    positions = []
    total_value_eur = 0
    total_invested_eur = 0

    # EUR/USD Kurs (validiert, mit 1.0-Fallback — reiner Anzeige-Pfad)
    eur_usd = safe_eur_usd(market_data)

    for account_name, account in portfolio.get("accounts", {}).items():
        for pos in account.get("positions", []):
            ticker = pos.get("ticker")
            shares = pos.get("shares", 0)
            buy_in = pos.get("buy_in", 0)
            currency = pos.get("currency", "EUR")
            name = pos.get("name", ticker or "Unbekannt")
            isin = pos.get("isin", "")

            # Buy-In in EUR: gespeicherten historischen Kurs nutzen, nicht aktuellen FX-Kurs
            if pos.get("buy_in_eur"):
                buy_in_eur = pos["buy_in_eur"]
            elif currency == "EUR":
                buy_in_eur = buy_in
            else:
                # Fallback: aktueller Kurs (ungenau bei FX-Schwankungen)
                buy_in_eur = buy_in / eur_usd
            invested_eur = shares * buy_in_eur

            current_price = None
            price_data = {}
            if ticker and ticker in market_data.get("positions", {}):
                price_data = market_data["positions"][ticker].get("price", {})
                current_price = price_data.get("current_price")

            has_live_price = current_price is not None
            if has_live_price:
                current_price_eur = current_price if currency == "EUR" else current_price / eur_usd
                current_value_eur = shares * current_price_eur
                pnl_eur = current_value_eur - invested_eur
                pnl_pct = (pnl_eur / invested_eur * 100) if invested_eur else 0
            else:
                current_price_eur = buy_in_eur
                current_value_eur = invested_eur
                pnl_eur = 0
                pnl_pct = 0

            total_value_eur += current_value_eur
            total_invested_eur += invested_eur

            positions.append({
                "name": name,
                "ticker": ticker or "",
                "isin": isin,
                "account": account_name,
                "shares": shares,
                "buy_in": buy_in,
                "buy_in_eur": round(buy_in_eur, 2),
                "currency": currency,
                "current_price": current_price,
                "current_price_eur": round(current_price_eur, 2),
                "current_value_eur": round(current_value_eur, 2),
                "invested_eur": round(invested_eur, 2),
                "pnl_eur": round(pnl_eur, 2),
                "pnl_pct": round(pnl_pct, 1),
                "has_live_price": has_live_price,
                "sector": price_data.get("sector", ""),
                "beta": price_data.get("beta"),
                "pe_ratio": price_data.get("pe_ratio"),
                "dividend_yield": price_data.get("dividend_yield"),
                "change_pct": price_data.get("change_pct"),
                "perf_1m_pct": price_data.get("perf_1m_pct"),
                "perf_6m_pct": price_data.get("perf_6m_pct"),
                "perf_1y_pct": price_data.get("perf_1y_pct"),
                "high_52w": price_data.get("52w_high"),
                "low_52w": price_data.get("52w_low"),
            })

    # Allocation berechnen
    holdings_value = total_value_eur  # vor Cash
    for p in positions:
        p["allocation_pct"] = round(p["current_value_eur"] / holdings_value * 100, 1) if holdings_value else 0

    # Bankkonten
    bank_accounts = []
    cash_total = 0
    depot_cash = 0
    free_cash = 0
    for name, acc in portfolio.get("bank_accounts", {}).items():
        val = acc.get("value", 0)
        is_depot = acc.get("is_depot_cash", False)
        cash_total += val
        if is_depot:
            depot_cash += val
        else:
            free_cash += val
        bank_accounts.append({
            "name": name,
            "bank": acc.get("bank", ""),
            "value": val,
            "interest": acc.get("interest", 0),
            "note": acc.get("note", ""),
            "is_depot_cash": is_depot,
        })

    total_value_eur += cash_total
    total_pnl_eur = total_value_eur - total_invested_eur - cash_total
    total_pnl_pct = (total_pnl_eur / total_invested_eur * 100) if total_invested_eur else 0

    # Sortiere Positionen nach Wert (absteigend)
    positions.sort(key=lambda p: p["current_value_eur"], reverse=True)

    # Region-Exposure (gewichtet nach Revenue-Regionen aus region_exposure.json)
    region_map = _load_region_exposure()
    regions = {}
    for p in positions:
        ticker = p.get("ticker", "")
        value = p["current_value_eur"]
        if ticker in region_map:
            for region, pct in region_map[ticker].items():
                regions[region] = regions.get(region, 0) + value * pct / 100
        else:
            # Fallback: ISIN-basiert
            isin_prefix = p["isin"][:2] if p.get("isin") and len(p["isin"]) >= 2 else ""
            fallback = {"US": "USA", "DE": "Europa", "AT": "Europa", "NL": "Europa",
                        "FR": "Europa", "IE": "Europa", "GB": "Europa", "CH": "Europa",
                        "JP": "Asien", "CN": "Asien", "HK": "Asien", "KR": "Asien"}
            region = fallback.get(isin_prefix, "Sonstige")
            regions[region] = regions.get(region, 0) + value

    # Sektor-Breakdown — Fonds/ETFs/Anleihen via Durchschau-Research zerlegen statt "Unbekannt"
    try:
        from src.data.holdings import load_holdings_research, needs_lookthrough
        _research = load_holdings_research()
    except Exception:
        _research, needs_lookthrough = {}, None
    sectors = {}
    for p in positions:
        val = p["current_value_eur"]
        key = p.get("isin") or p.get("ticker") or p.get("name", "")
        entry = _research.get(key)
        is_fund = needs_lookthrough(p.get("name", ""), p.get("ticker", ""), p.get("isin", "")) if needs_lookthrough else False
        if is_fund and entry:
            sb = entry.get("sector_breakdown") or {}
            ac = entry.get("asset_class")
            if sb:
                covered = 0.0
                for sec, pct in sb.items():
                    w = (pct or 0) / 100
                    covered += w
                    cs = _norm_sector(sec)
                    sectors[cs] = sectors.get(cs, 0) + val * w
                if max(0.0, 1 - covered) > 0.01:
                    sectors["Sonstige"] = sectors.get("Sonstige", 0) + val * (1 - covered)
            elif ac == "bond":
                sectors["Anleihen"] = sectors.get("Anleihen", 0) + val
            elif ac == "commodity":
                sectors["Rohstoffe"] = sectors.get("Rohstoffe", 0) + val
            else:
                sectors["Unbekannt"] = sectors.get("Unbekannt", 0) + val
        elif is_fund:
            sectors["Fonds (nicht recherchiert)"] = sectors.get("Fonds (nicht recherchiert)", 0) + val
        else:
            sector = _norm_sector(p["sector"] or "Unbekannt")
            sectors[sector] = sectors.get(sector, 0) + val

    # Account-Breakdown
    accounts = {}
    for p in positions:
        acc = p["account"]
        accounts[acc] = accounts.get(acc, 0) + p["current_value_eur"]

    # Account-gruppierte Positionen mit Display-Namen
    accounts_grouped = {}
    for p in positions:
        acc = p["account"]
        if acc not in accounts_grouped:
            accounts_grouped[acc] = {
                "display_name": ACCOUNT_DISPLAY_NAMES.get(acc, acc.replace("_", " ").title()),
                "positions": [],
                "total_value": 0,
                "total_pnl": 0,
            }
        accounts_grouped[acc]["positions"].append(p)
        accounts_grouped[acc]["total_value"] += p["current_value_eur"]
        accounts_grouped[acc]["total_pnl"] += p["pnl_eur"]
    for acc in accounts_grouped.values():
        acc["total_value"] = round(acc["total_value"], 2)
        acc["total_pnl"] = round(acc["total_pnl"], 2)

    return {
        "total_value_eur": round(total_value_eur, 2),
        "holdings_value_eur": round(holdings_value, 2),
        "cash_total": round(cash_total, 2),
        "depot_cash": round(depot_cash, 2),
        "free_cash": round(free_cash, 2),
        "total_invested_eur": round(total_invested_eur, 2),
        "total_pnl_eur": round(total_pnl_eur, 2),
        "total_pnl_pct": round(total_pnl_pct, 1),
        "position_count": len(positions),
        "top_position": ({"name": positions[0]["name"], "ticker": positions[0]["ticker"],
                          "pct": round(positions[0]["current_value_eur"] / total_value_eur * 100, 1)}
                         if positions and total_value_eur else None),
        "cash_pct": round(cash_total / total_value_eur * 100, 1) if total_value_eur else 0,
        "positions": positions,
        "bank_accounts": bank_accounts,
        "eur_usd_rate": eur_usd,
        "region_exposure": {k: round(v, 2) for k, v in sorted(regions.items(), key=lambda x: x[1], reverse=True)},
        "sector_breakdown": {k: round(v, 2) for k, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)},
        "account_breakdown": {k: round(v, 2) for k, v in sorted(accounts.items(), key=lambda x: x[1], reverse=True)},
        "accounts_grouped": accounts_grouped,
    }


def compute_index_data(market_data: dict) -> list:
    """Extrahiert Index-Daten als Liste für die Anzeige."""
    indices = market_data.get("indices", {})
    result = []
    for name in ["S&P 500", "NASDAQ", "DAX", "ATX", "Euro Stoxx 50", "Gold", "BTC/USD", "EUR/USD", "VIX"]:
        if name in indices:
            idx = indices[name]
            result.append({
                "name": name,
                "description": INDEX_DESCRIPTIONS.get(name, ""),
                "value": idx.get("value"),
                "change_pct": idx.get("change_pct"),
            })
    return result
