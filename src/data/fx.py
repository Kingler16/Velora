"""
Zentrale, validierte EUR/USD-Umrechnung — EINE Wahrheit für alle Pfade.

Vorher wurde der Kurs an 5+ Stellen mit `.get("value", 1.0)` ohne Sanity-Check
geholt (portfolio_service, prompt, performance, app /api/trade). Folgen:
- `value: None` umging den 1.0-Default → TypeError-Crash (performance.py:71).
- Fehlender Kurs im Trade-Pfad → USD-Kauf wurde dauerhaft 1:1 als EUR verbucht.

Regel:
- ANZEIGE-Pfade nutzen `safe_eur_usd()` (mit 1.0-Fallback, nie crashen).
- TRADE-/SCHREIB-Pfade nutzen `get_eur_usd()` und LEHNEN bei None ab, statt
  einen falschen, steuerrelevanten Buy-In zu persistieren.
"""

import logging

logger = logging.getLogger(__name__)

# Plausibilitäts-Korridor. EUR/USD lag historisch nie ausserhalb 0.7–1.5.
EUR_USD_MIN = 0.7
EUR_USD_MAX = 1.5


def get_eur_usd(market_data: dict | None) -> float | None:
    """Validierter EUR/USD-Kurs aus market_data['indices']['EUR/USD']['value'].

    Returns:
        float im Korridor (0.7, 1.5) — oder None wenn der Kurs fehlt, kein
        gültiger Float ist oder unplausibel ist. Caller im Trade-Pfad MUSS
        bei None den USD-Vorgang ablehnen.
    """
    if not market_data:
        return None
    indices = market_data.get("indices") or {}
    raw = indices.get("EUR/USD") or {}
    val = raw.get("value")
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None
    if not (EUR_USD_MIN < val < EUR_USD_MAX):
        logger.warning("Unplausibler EUR/USD-Kurs verworfen: %r", val)
        return None
    return val


def safe_eur_usd(market_data: dict | None, default: float = 1.0) -> float:
    """Wie get_eur_usd(), aber mit Fallback — NUR für reine Anzeige-Pfade.

    Niemals im Trade-/Schreib-Pfad verwenden (dort get_eur_usd() + Ablehnung).
    """
    val = get_eur_usd(market_data)
    return val if val is not None else default


def resolve_quote_currency(price_data: dict | None, pos_currency: str | None) -> str:
    """Notierungswährung des LIVE-Kurses — Marktdaten (yfinance) haben Vorrang.

    Das currency-Feld der Portfolio-Position beschreibt, in welcher Währung der
    Buy-in erfasst wurde — NICHT zwingend, in welcher Währung der Ticker notiert.
    Wer den Live-Kurs umrechnet, muss die echte Quote-Währung nehmen, sonst wird
    z.B. ein USD-Kurs als EUR interpretiert, sobald ein User die Position auf
    EUR gestellt hat (weil er seinen Buy-in in EUR eingibt) → Rendite um den
    FX-Kurs falsch.
    """
    ccy = (price_data or {}).get("currency") or pos_currency or "EUR"
    return str(ccy).upper()
