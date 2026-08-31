"""
Kandidaten-Screener für neue Investment-Ideen.

Ersetzt die alte Brave-Suche nach "undervalued stocks to buy", die nur
SEO-Listicles (Morningstar, Motley Fool, U.S. News) mit Überschrift und
Snippet lieferte — ohne Ticker, ohne Zahlen. Velora hat die deshalb in
jedem Briefing als "Morningstar-Nachplapper" abgelehnt (zu Recht: der
System-Prompt verbietet genau das), und konnte mangels Kursdaten für
Fremdtitel ohnehin keine Empfehlung mit Einstieg/Stop/Ziel formulieren.

Stattdessen: echter Yahoo-Screener (yfinance EquityQuery) auf Sektoren,
die im Depot fehlen oder untergewichtet sind. Jeder Kandidat kommt mit
vollen Kursdaten (ATR, RSI, SMA200, 52W-Range) zurück — damit sind
Stop-Distanzen und Ziele berechenbar statt geraten.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Yahoo-Sektor-Vokabular (exakt so vom Screener erwartet).
_ALL_SECTORS = [
    "Technology",
    "Communication Services",
    "Healthcare",
    "Financial Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Industrials",
    "Energy",
    "Utilities",
    "Real Estate",
    "Basic Materials",
]

# Qualitäts-Untergrenzen: hält OTC-/Pink-Sheet-Varianten und illiquide
# Zweitlistings draußen (DOGEF, IBDSF & Co. tauchten ohne diese Filter auf).
_MIN_MARKET_CAP = 3_000_000_000
_MIN_AVG_VOLUME = 800_000
_EXCHANGES = ["NYQ", "NMS"]  # NYSE + Nasdaq Global Select


def _held_sectors(market_data: dict) -> dict:
    """Sektor → Anzahl Positionen im Depot (aus den yfinance-Sektorlabels)."""
    counts: dict[str, int] = {}
    for data in (market_data.get("positions") or {}).values():
        sector = ((data.get("price") or {}).get("sector") or "").strip()
        if sector:
            counts[sector] = counts.get(sector, 0) + 1
    return counts


def _excluded_tickers(portfolio: dict, market_data: dict) -> set[str]:
    """Alles, was Velora nicht als *neue* Idee vorschlagen soll: Depot + Watchlist.
    Basis-Symbol ohne Börsensuffix, damit ASML.AS auch ASML trifft."""
    out: set[str] = set()

    def add(tk: str | None):
        if tk:
            tk = tk.upper()
            out.add(tk)
            out.add(tk.split(".")[0])

    for acc in (portfolio.get("accounts") or {}).values():
        for pos in acc.get("positions") or []:
            add(pos.get("ticker"))
    for tk in (market_data.get("watchlist") or {}):
        add(tk)
    return out


def _screen_sector(sector: str, size: int) -> list[dict]:
    """Ein Sektor-Screen. Gibt rohe Quote-Dicts zurück, leere Liste bei Fehler."""
    try:
        import yfinance as yf

        query = yf.EquityQuery("and", [
            yf.EquityQuery("gt", ["intradaymarketcap", _MIN_MARKET_CAP]),
            yf.EquityQuery("gt", ["avgdailyvol3m", _MIN_AVG_VOLUME]),
            yf.EquityQuery("is-in", ["sector", sector]),
            yf.EquityQuery("is-in", ["exchange"] + _EXCHANGES),
        ])
        result = yf.screen(query, size=size, sortField="intradaymarketcap", sortAsc=False)
        return result.get("quotes") or []
    except Exception as e:
        logger.warning("Screener für Sektor '%s' fehlgeschlagen: %s", sector, e)
        return []


def _enrich(candidate: dict) -> dict | None:
    """Kandidat mit echten Kursdaten anreichern (ATR/RSI/SMA/52W).
    Ohne diese Zahlen kann Velora keine Empfehlung mit Stop und Ziel bauen."""
    try:
        from src.data.market import fetch_price_data

        price = fetch_price_data(candidate["ticker"])
        if not price or not price.get("current_price"):
            return None
        # Mindest-Substanz: entweder ein KGV (profitabel) oder echte Analysten-
        # Abdeckung. Hält Vehikel ohne belastbare Fundamentaldaten draußen, lässt
        # aber unprofitable Wachstumstitel mit Coverage zu — deren Bewertung soll
        # Velora selbst treffen, nicht dieser Filter.
        if price.get("pe_ratio") is None and (price.get("analyst_count") or 0) < 5:
            logger.debug("Kandidat %s verworfen: weder KGV noch Analysten-Coverage",
                         candidate["ticker"])
            return None
        candidate["price"] = price
        return candidate
    except Exception as e:
        logger.debug("Anreicherung für %s fehlgeschlagen: %s", candidate.get("ticker"), e)
        return None


def find_candidates(portfolio: dict, market_data: dict, limit: int = 6) -> list[dict]:
    """Sucht Kandidaten in Sektoren, die im Depot fehlen oder dünn besetzt sind.

    Priorisiert komplett fehlende Sektoren (echte Diversifikation) vor solchen
    mit nur einer Position. Sektoren mit 2+ Positionen werden übersprungen —
    dort besteht kein Diversifikationsbedarf.

    Returns: Liste von {ticker, name, sector, market_cap, pe, price: {...}}.
    """
    try:
        held = _held_sectors(market_data)
        excluded = _excluded_tickers(portfolio, market_data)

        missing = [s for s in _ALL_SECTORS if held.get(s, 0) == 0]
        thin = [s for s in _ALL_SECTORS if held.get(s, 0) == 1]
        targets = (missing + thin)[:4]
        if not targets:
            logger.info("Screener: alle Sektoren belegt — keine Ziel-Sektoren")
            return []

        logger.info("Screener: Ziel-Sektoren %s (Depot deckt %s ab)",
                    targets, sorted(held.keys()))

        # Pro Sektor mehr holen als gebraucht — Depot-Ticker fliegen noch raus.
        per_sector = max(3, limit // max(1, len(targets)) + 3)
        raw: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(4, len(targets))) as ex:
            futures = {ex.submit(_screen_sector, s, per_sector): s for s in targets}
            for fut in as_completed(futures):
                sector = futures[fut]
                for q in fut.result():
                    symbol = (q.get("symbol") or "").upper()
                    if not symbol or symbol in excluded:
                        continue
                    raw.append({
                        "ticker": symbol,
                        "name": q.get("shortName") or q.get("longName") or symbol,
                        "sector": sector,
                        "market_cap": q.get("marketCap"),
                        "pe": q.get("trailingPE"),
                    })

        # Round-Robin über die Sektoren, damit nicht ein Sektor die Liste füllt.
        by_sector: dict[str, list[dict]] = {}
        for c in raw:
            by_sector.setdefault(c["sector"], []).append(c)

        picked: list[dict] = []
        while len(picked) < limit and any(by_sector.values()):
            for sector in targets:
                bucket = by_sector.get(sector) or []
                if bucket and len(picked) < limit:
                    picked.append(bucket.pop(0))

        if not picked:
            return []

        # Anreicherung parallel — das ist der teure Teil (~2-4s pro Ticker).
        enriched: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(6, len(picked))) as ex:
            for fut in as_completed([ex.submit(_enrich, c) for c in picked]):
                got = fut.result()
                if got:
                    enriched.append(got)

        enriched.sort(key=lambda c: (c["sector"], -(c.get("market_cap") or 0)))
        logger.info("Screener: %d Kandidaten mit Kursdaten (%s)",
                    len(enriched), ", ".join(c["ticker"] for c in enriched))
        return enriched

    except Exception as e:
        logger.warning("Screener komplett fehlgeschlagen: %s", e, exc_info=True)
        return []
