"""Faktor-Linse: Style-Exposure des Depots (regelbasiert, rein diagnostisch).

Motivation (Quant-Research-Erkenntnis): Sektor-Diversifikation allein übersieht
Faktor-Klumpen. "Fünf Titel, alle High-Momentum-Growth" fällt im Drawdown
gemeinsam — auch wenn die Sektoren verschieden aussehen. Diese Linse macht das
sichtbar. Sie ist bewusst NICHT prognostisch (kein Signal, kein Sizing, kein
Backtest-Overfitting möglich): sie beschreibt nur den Ist-Zustand als Kontext
für Claudes Empfehlungen.

Alle Inputs existieren bereits in market_data (yfinance) — kein neuer API-Call:
perf_1y/perf_1m (Momentum 12-1), pe_ratio (Value), realized_vol_30d + beta
(Low-Vol), market_cap (Size), profit_margin/revenue_growth (Quality/Growth).

Fonds/ETFs werden nicht gescored (kein sinnvolles Einzel-P/E) — ihr Gewicht wird
separat ausgewiesen; das echte Faktor-Profil dort liefert die Fonds-Durchschau.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Schwellwerte — bewusst grob (Buckets statt Scheingenauigkeit)
MOM_HIGH_PCT = 15.0     # 12-1-Momentum über +15% = hoch
MOM_NEG_PCT = -10.0     # unter -10% = Abwärtstrend
PE_CHEAP = 16.0
PE_EXPENSIVE = 28.0
VOL_LOW = 20.0          # realized_vol_30d annualisiert in %
VOL_HIGH = 35.0
BETA_DEFENSIVE = 0.9
MEGA_CAP = 200e9
LARGE_CAP = 10e9

# Konzentrations-Schwellen (Anteil am investierten Kapital)
STYLE_WARN_PCT = 45.0
STYLE_BREACH_PCT = 60.0


def _momentum_12_1(perf_1y_pct, perf_1m_pct):
    """Klassisches 12-1-Momentum: 1J-Return OHNE den letzten Monat (der mean-reverted).
    ((1+r_1y) / (1+r_1m) - 1) — None-tolerant."""
    if perf_1y_pct is None:
        return None
    if perf_1m_pct is None:
        return perf_1y_pct  # Fallback: rohes 1J-Momentum
    try:
        return ((1 + perf_1y_pct / 100) / (1 + perf_1m_pct / 100) - 1) * 100
    except ZeroDivisionError:
        return None


def _classify_stock(md_price: dict) -> dict:
    """Faktor-Tags + primärer Style-Bucket für eine Einzelaktie."""
    mom = _momentum_12_1(md_price.get("perf_1y_pct"), md_price.get("perf_1m_pct"))
    pe = md_price.get("pe_ratio")
    vol = md_price.get("realized_vol_30d")
    beta = md_price.get("beta")
    mcap = md_price.get("market_cap")
    margin = md_price.get("profit_margin")       # Fraction (0..1)
    growth = md_price.get("revenue_growth")      # Fraction

    tags = {}
    tags["momentum"] = None if mom is None else ("hoch" if mom >= MOM_HIGH_PCT else "negativ" if mom <= MOM_NEG_PCT else "neutral")
    tags["value"] = None if pe is None else ("günstig" if pe < PE_CHEAP else "teuer" if pe > PE_EXPENSIVE else "neutral")
    tags["vol"] = None if vol is None else ("niedrig" if vol < VOL_LOW else "hoch" if vol > VOL_HIGH else "mittel")
    tags["size"] = None if mcap is None else ("Mega" if mcap >= MEGA_CAP else "Large" if mcap >= LARGE_CAP else "Mid/Small")
    tags["quality"] = None if margin is None else ("hoch" if margin >= 0.15 else "niedrig" if margin < 0.05 else "mittel")

    # Primärer Style (Reihenfolge = Priorität): der Bucket, in dem die Position
    # im Stress am ehesten mit ihresgleichen korreliert.
    growthy = (tags["value"] == "teuer") or (growth is not None and growth > 0.10)
    if tags["momentum"] == "hoch" and growthy:
        style = "High-Momentum-Growth"
    elif tags["momentum"] == "negativ":
        style = "Abwärtstrend"
    elif tags["value"] == "günstig":
        style = "Value"
    elif tags["vol"] == "niedrig" and (beta is not None and beta <= BETA_DEFENSIVE):
        style = "Defensiv"
    else:
        style = "Core/Neutral"

    return {"style": style, "tags": tags, "momentum_12_1_pct": round(mom, 1) if mom is not None else None}


def compute_factor_data(market_data: dict, overview: dict) -> dict:
    """Berechnet das Faktor-/Style-Profil des Depots als strukturiertes Dict."""
    from src.data.holdings import needs_lookthrough

    empty = {"positions": [], "styles": {}, "warnings": [], "fund_weight_pct": 0.0,
             "stock_count": 0, "total_invested_eur": 0.0}
    all_pos = overview.get("positions") or []
    if not all_pos:
        return empty

    # Über Accounts aggregieren (gleicher Ticker in Erste + TR = eine Wette)
    agg: dict[str, dict] = {}
    for p in all_pos:
        key = p.get("ticker") or p.get("isin") or p.get("name") or "?"
        e = agg.setdefault(key, {"ticker": p.get("ticker", ""), "name": p.get("name", ""),
                                 "isin": p.get("isin", ""), "value_eur": 0.0})
        e["value_eur"] += p.get("current_value_eur") or 0.0

    total = sum(e["value_eur"] for e in agg.values())
    if total <= 0:
        return empty

    md_positions = market_data.get("positions", {}) if market_data else {}

    positions = []
    styles: dict[str, float] = {}
    fund_weight = 0.0
    stock_count = 0

    for key, e in agg.items():
        weight = e["value_eur"] / total * 100
        is_fund = needs_lookthrough(e["name"], e["ticker"], e["isin"])
        if is_fund:
            fund_weight += weight
            positions.append({"ticker": e["ticker"] or e["isin"], "name": e["name"],
                              "weight_pct": round(weight, 1), "style": "Fonds/ETF",
                              "tags": {}, "momentum_12_1_pct": None})
            continue

        md_price = (md_positions.get(e["ticker"]) or {}).get("price") or {}
        cls = _classify_stock(md_price)
        stock_count += 1
        styles[cls["style"]] = styles.get(cls["style"], 0.0) + weight
        positions.append({"ticker": e["ticker"], "name": e["name"],
                          "weight_pct": round(weight, 1), **cls})

    # Warnungen: Style-Klumpen unter den Einzelaktien
    warnings = []
    for style, w in sorted(styles.items(), key=lambda kv: -kv[1]):
        if style == "Core/Neutral":
            continue  # Neutral ist kein Klumpenrisiko
        if w >= STYLE_BREACH_PCT:
            warnings.append(f"BREACH: {w:.0f}% des investierten Kapitals im Style '{style}' — fällt im Drawdown gemeinsam")
        elif w >= STYLE_WARN_PCT:
            warnings.append(f"WARNUNG: {w:.0f}% im Style '{style}' — versteckter Faktor-Klumpen trotz ggf. verschiedener Sektoren")

    # Stiller Klumpen: viele Momentum-Titel, die einzeln unauffällig sind
    hm = [p for p in positions if p.get("style") == "High-Momentum-Growth"]
    hm_weight = sum(p["weight_pct"] for p in hm)
    if len(hm) >= 3 and hm_weight >= 30 and not any("High-Momentum-Growth" in w for w in warnings):
        warnings.append(f"HINWEIS: {len(hm)} Titel ({hm_weight:.0f}%) sind High-Momentum-Growth — gleiche Faktor-Wette, prüfe Korrelation")

    positions.sort(key=lambda p: -p["weight_pct"])
    return {
        "positions": positions,
        "styles": {k: round(v, 1) for k, v in sorted(styles.items(), key=lambda kv: -kv[1])},
        "warnings": warnings,
        "fund_weight_pct": round(fund_weight, 1),
        "stock_count": stock_count,
        "total_invested_eur": round(total, 2),
    }


def format_factor_data(data: dict) -> str:
    """Kompakter Prompt-Block. Leerstring wenn nichts zu sagen ist."""
    if not data or not data.get("positions"):
        return ""

    lines = []
    if data.get("styles"):
        style_str = ", ".join(f"{k} {v:.0f}%" for k, v in data["styles"].items())
        lines.append(f"Style-Verteilung (Einzelaktien, Anteil am investierten Kapital): {style_str}")
    if data.get("fund_weight_pct"):
        lines.append(f"Fonds/ETF: {data['fund_weight_pct']:.0f}% (Faktor-Profil siehe Fonds-Durchschau)")

    lines.append("")
    for p in data["positions"]:
        if p["style"] == "Fonds/ETF":
            continue
        t = p.get("tags", {})
        parts = []
        if p.get("momentum_12_1_pct") is not None:
            parts.append(f"Mom12-1 {p['momentum_12_1_pct']:+.0f}%")
        if t.get("value"):
            parts.append(f"Value: {t['value']}")
        if t.get("vol"):
            parts.append(f"Vol: {t['vol']}")
        if t.get("size"):
            parts.append(t["size"])
        if t.get("quality"):
            parts.append(f"Quality: {t['quality']}")
        detail = ", ".join(parts) if parts else "keine Daten"
        lines.append(f"- {p['ticker']} ({p['weight_pct']}%): {p['style']} [{detail}]")

    if data.get("warnings"):
        lines.append("")
        for w in data["warnings"]:
            lines.append(f"! {w}")
    else:
        lines.append("")
        lines.append("Kein Style-Klumpen über den Schwellwerten — Faktor-Diversifikation ok.")

    lines.append("")
    lines.append("(Diagnose, kein Signal: nutze das als Kontext für Klumpenrisiko-Einschätzung, "
                 "nicht als Kauf-/Verkaufsgrund allein.)")
    return "\n".join(lines)
