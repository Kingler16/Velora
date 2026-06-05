"""
Performance-Tracking: Benchmark-Vergleich, Recommendation-Tracking, Tax-Loss-Harvesting.
"""

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.fx import safe_eur_usd

logger = logging.getLogger(__name__)

# Mindestanzahl Tagesreturns, ab der eine Position für Risiko/Korrelation taugt.
MIN_RETURNS = 30
TRADING_DAYS = 252

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"


def compute_benchmark_data(market_data: dict) -> list:
    """Berechnet Benchmark-Daten als strukturierte Liste."""
    indices = market_data.get("indices", {})
    benchmarks = []

    for name in ["S&P 500", "NASDAQ", "DAX", "ATX", "Euro Stoxx 50", "Gold", "BTC/USD"]:
        if name in indices:
            change = indices[name].get("change_pct", 0)
            if change is None or (isinstance(change, float) and math.isnan(change)):
                change = 0.0
            benchmarks.append({"name": name, "change_pct": change})

    benchmarks.sort(key=lambda x: x["change_pct"], reverse=True)
    return benchmarks


def calculate_benchmark_comparison(market_data: dict) -> str:
    """Vergleicht Portfolio-Performance mit Benchmarks."""
    benchmarks = compute_benchmark_data(market_data)

    if not benchmarks:
        return "Keine Benchmark-Daten verfügbar."

    lines = ["BENCHMARK-VERGLEICH (Wochenperformance):"]
    for b in benchmarks:
        change = b["change_pct"]
        if math.isnan(change):
            lines.append(f"  {b['name']:20s}: n/a")
            continue
        bar = "+" * int(abs(change)) if change > 0 else "-" * int(abs(change))
        lines.append(f"  {b['name']:20s}: {change:+.2f}% {bar}")

    return "\n".join(lines)


def _load_tax_rate() -> float:
    """Lädt Steuersatz aus Settings."""
    try:
        settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
        with open(settings_path) as f:
            settings = json.load(f)
        return settings.get("user", {}).get("tax_rate", 0.275)
    except Exception:
        return 0.275


def compute_tax_loss_data(portfolio: dict, market_data: dict, tax_rate: float = None) -> dict:
    """Berechnet Tax-Loss-Harvesting Daten als strukturiertes Dict."""
    if tax_rate is None:
        tax_rate = _load_tax_rate()

    gains = []
    losses = []

    eur_usd = safe_eur_usd(market_data)

    for account_name, account in portfolio.get("accounts", {}).items():
        for pos in account.get("positions", []):
            ticker = pos.get("ticker")
            if not ticker or ticker not in market_data.get("positions", {}):
                continue

            shares = pos["shares"]
            buy_in = pos["buy_in"]
            currency = pos.get("currency", "EUR")
            current_price = market_data["positions"][ticker].get("price", {}).get("current_price")

            if not current_price:
                continue

            # Buy-In in EUR: buy_in_eur aus Portfolio nutzen (historischer Kurs)
            if pos.get("buy_in_eur"):
                buy_in_eur = pos["buy_in_eur"]
            elif currency == "USD":
                buy_in_eur = buy_in / eur_usd
            else:
                buy_in_eur = buy_in

            if currency == "USD":
                current_eur = current_price / eur_usd
            else:
                current_eur = current_price

            pnl_eur = (current_eur - buy_in_eur) * shares
            pnl_pct = ((current_eur / buy_in_eur) - 1) * 100 if buy_in_eur else 0

            entry = {
                "name": pos["name"],
                "ticker": ticker,
                "pnl_eur": round(pnl_eur, 2),
                "pnl_pct": round(pnl_pct, 1),
                "account": account_name,
            }

            if pnl_eur > 0:
                gains.append(entry)
            elif pnl_eur < 0:
                losses.append(entry)

    total_gains = sum(g["pnl_eur"] for g in gains)
    total_losses = sum(l["pnl_eur"] for l in losses)
    potential_tax = total_gains * tax_rate
    net_after_harvesting = (total_gains + total_losses) * tax_rate
    tax_savings = potential_tax - max(0, net_after_harvesting)

    # Per-Account Aufschlüsselung
    account_data = {}
    for entry in gains + losses:
        acc = entry["account"]
        if acc not in account_data:
            account_data[acc] = {"gains": [], "losses": []}
        if entry["pnl_eur"] > 0:
            account_data[acc]["gains"].append(entry)
        else:
            account_data[acc]["losses"].append(entry)

    per_account = {}
    for acc, data in account_data.items():
        acc_gains = sum(g["pnl_eur"] for g in data["gains"])
        acc_losses = sum(l["pnl_eur"] for l in data["losses"])
        acc_potential_tax = acc_gains * tax_rate
        acc_net = (acc_gains + acc_losses) * tax_rate
        acc_savings = acc_potential_tax - max(0, acc_net)
        per_account[acc] = {
            "total_gains": round(acc_gains, 2),
            "total_losses": round(acc_losses, 2),
            "potential_tax": round(acc_potential_tax, 2),
            "net_tax": round(max(0, acc_net), 2),
            "tax_savings": round(acc_savings, 2),
            "gains": sorted(data["gains"], key=lambda x: x["pnl_eur"], reverse=True),
            "losses": sorted(data["losses"], key=lambda x: x["pnl_eur"]),
        }

    return {
        "tax_rate": tax_rate,
        "total_gains": round(total_gains, 2),
        "total_losses": round(total_losses, 2),
        "potential_tax": round(potential_tax, 2),
        "net_tax": round(max(0, net_after_harvesting), 2),
        "tax_savings": round(tax_savings, 2),
        "gains": sorted(gains, key=lambda x: x["pnl_eur"], reverse=True),
        "losses": sorted(losses, key=lambda x: x["pnl_eur"]),
        "per_account": per_account,
    }


def find_tax_loss_harvesting(portfolio: dict, market_data: dict, tax_rate: float = None) -> str:
    """Identifiziert Tax-Loss-Harvesting Opportunitäten (String-Format für Prompts)."""
    data = compute_tax_loss_data(portfolio, market_data, tax_rate)

    lines = [
        "TAX-LOSS-HARVESTING ANALYSE (KESt 27.5%):",
        f"  Unrealisierte Gewinne: {data['total_gains']:+.2f}€",
        f"  Unrealisierte Verluste: {data['total_losses']:+.2f}€",
        f"  Potenzielle KESt auf Gewinne: {data['potential_tax']:.2f}€",
        f"  KESt nach Verlustverrechnung: {data['net_tax']:.2f}€",
        f"  Mögliche Steuerersparnis: {data['tax_savings']:.2f}€",
        "",
        "  Verlust-Positionen (Kandidaten für Harvesting):",
    ]
    for l in data["losses"]:
        lines.append(f"    {l['name']} ({l['ticker']}): {l['pnl_eur']:+.2f}€ ({l['pnl_pct']:+.1f}%) [{l['account']}]")

    lines.append("")
    lines.append("  Gewinn-Positionen:")
    for g in data["gains"]:
        lines.append(f"    {g['name']} ({g['ticker']}): {g['pnl_eur']:+.2f}€ ({g['pnl_pct']:+.1f}%) [{g['account']}]")

    return "\n".join(lines)


def compute_recommendation_data(market_data: dict) -> dict:
    """Berechnet Empfehlungs-Performance als strukturiertes Dict."""
    empty = {
        "open": [], "wins": [], "losses": [], "expired": [],
        "hit_rate": 0, "total_closed": 0, "open_count": 0, "expired_count": 0,
    }
    recs_path = MEMORY_DIR / "recommendations.json"
    if not recs_path.exists():
        return dict(empty)

    with open(recs_path) as f:
        recs = json.load(f)

    if not recs:
        return dict(empty)

    open_recs = []
    wins = []
    losses = []
    expired = []

    for rec in recs:
        status = rec.get("status", "open")
        if status == "open":
            open_recs.append(rec)
        elif status == "target_hit":
            wins.append(rec)
        elif status == "stop_hit":
            losses.append(rec)
        elif status == "cancelled":
            # Auto-abgelaufene watch-Empfehlungen: Limit nie erreicht, nie getriggert.
            # Weder Win noch Loss — aber sichtbar machen (Survivorship-Bias).
            expired.append(rec)

    total_closed = len(wins) + len(losses)
    # Verfallene zählen NICHT als Loss — sie wurden nie getriggert.
    hit_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0

    return {
        "open": open_recs,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "hit_rate": round(hit_rate, 0),
        "total_closed": total_closed,
        "open_count": len(open_recs),
        "expired_count": len(expired),
    }


def track_recommendation_performance(market_data: dict) -> str:
    """Trackt wie vergangene Empfehlungen performt haben (String-Format für Prompts)."""
    data = compute_recommendation_data(market_data)

    if not data["open"] and not data["wins"] and not data["losses"] and not data["expired"]:
        return "Noch keine Empfehlungen zum Tracken."

    lines = ["EMPFEHLUNGS-BILANZ:"]
    lines.append(f"  Abgeschlossen: {data['total_closed']} (Hit-Rate: {data['hit_rate']:.0f}%) | Offen: {data['open_count']}")
    if data["expired_count"]:
        # Survivorship-Bias sichtbar machen: verfallene Limits sind weder Win noch Loss,
        # zählen NICHT in die Hit-Rate — aber der Berater muss sie kennen.
        lines.append(f"  ⊘ verfallen (Limit nie erreicht): {data['expired_count']}")

    for rec in data["open"]:
        ticker = rec.get("ticker", "?")
        action = rec.get("action", "?")
        date = rec.get("date", "?")[:10]
        unrealized = rec.get("unrealized_pct")
        if unrealized is not None:
            emoji = "\U0001f4c8" if unrealized > 0 else "\U0001f4c9"
            lines.append(f"  {emoji} OFFEN {date}: {action} {ticker} \u2192 {unrealized:+.1f}%")

    for rec in data["wins"]:
        lines.append(f"  \u2705 {rec.get('date', '?')[:10]}: {rec.get('action', '?')} {rec.get('ticker', '?')} \u2192 Ziel erreicht")

    for rec in data["losses"]:
        lines.append(f"  \u274c {rec.get('date', '?')[:10]}: {rec.get('action', '?')} {rec.get('ticker', '?')} \u2192 Stop ausgelöst")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risiko-, Korrelations- & Regime-Analyse
#
# Datenquelle: market_data["positions"][ticker]["price"]["returns"] - Liste der
# 1y-Tagesreturns (Contract des market.py-Agenten). Zusaetzlich genutzt:
#   price["above_sma200"] (bool) fuer Breadth, price["current_price"] fuer Gewichte.
# macro_data["us"]["fed_funds_rate"]["value"]     -> rf (Prozent, z.B. 4.5)
# macro_data["us"]["yield_curve_spread"]["value"] -> 10y-2y (negativ = invertiert)
# macro_data["fear_greed"] = {"value": .., "rating": ..}
# market_data["indices"]["VIX"]["value"]          -> VIX
# Alle Funktionen sind defensiv: fehlende/zu kurze Daten -> Position auslassen,
# nie crashen.
# ---------------------------------------------------------------------------


def _get_returns(pos: dict):
    """Holt die Tagesreturns einer Position als float-Array - oder None.

    None bei: kein price-Dict, kein returns-Key, < MIN_RETURNS brauchbaren Werten,
    oder nicht-numerischen Werten. NaN/Inf werden rausgefiltert.
    """
    if not isinstance(pos, dict):
        return None
    price = pos.get("price")
    if not isinstance(price, dict):
        return None
    raw = price.get("returns")
    if not isinstance(raw, (list, tuple)) or len(raw) < MIN_RETURNS:
        return None
    try:
        arr = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        return None
    arr = arr[np.isfinite(arr)]
    if arr.size < MIN_RETURNS:
        return None
    return arr


def _rf_from_macro(macro_data: dict, fallback: float = 0.04) -> float:
    """Fed-Funds-Rate als Dezimal aus macro_data["us"]["fed_funds_rate"]["value"].

    FRED liefert den Wert in Prozent (z.B. 4.5) -> /100. Fallback 0.04 (=4%).
    """
    try:
        val = macro_data.get("us", {}).get("fed_funds_rate", {}).get("value")
        if val is None:
            return fallback
        return float(val) / 100.0
    except (AttributeError, TypeError, ValueError):
        return fallback


def compute_risk_metrics(market_data: dict, macro_data: dict) -> dict:
    """Pro Position: annualisierte Vol, Max-Drawdown, Sharpe (aus Tagesreturns).

    Rueckgabe:
        {
          "per_position": {ticker: {"vol_annual": float,    # % p.a.
                                    "max_drawdown": float,   # % (<= 0)
                                    "sharpe": float}},
          "rf_used": float,                                  # rf als Dezimal
        }
    Positionen ohne brauchbare returns werden ausgelassen.
    """
    rf = _rf_from_macro(macro_data)
    per_position: dict = {}

    positions = (market_data or {}).get("positions", {})
    for ticker, pos in positions.items():
        returns = _get_returns(pos)
        if returns is None:
            continue

        mean = float(np.mean(returns))
        std = float(np.std(returns))  # Population-Std (ddof=0)

        vol_annual = std * math.sqrt(TRADING_DAYS) * 100

        # Max-Drawdown auf dem kumulierten Return-Pfad (Wachstumsfaktor).
        # Start-Baseline 1.0 voranstellen, damit auch der Verlust der ERSTEN
        # Periode gegen den Anfangswert zaehlt (sonst ist der erste Punkt schon
        # das Maximum und der initiale Drop wird unterschlagen).
        cum = np.cumprod(1.0 + returns)
        cum = np.concatenate(([1.0], cum))
        running_max = np.maximum.accumulate(cum)
        drawdowns = cum / running_max - 1.0
        max_drawdown = float(np.min(drawdowns)) * 100  # negativ

        ann_return = mean * TRADING_DAYS
        ann_vol = std * math.sqrt(TRADING_DAYS)
        sharpe = (ann_return - rf) / ann_vol if ann_vol > 0 else 0.0

        per_position[ticker] = {
            "vol_annual": round(vol_annual, 1),
            "max_drawdown": round(max_drawdown, 1),
            "sharpe": round(sharpe, 2),
        }

    return {"per_position": per_position, "rf_used": round(rf, 4)}


def _position_value(pos: dict):
    """Naeherung des aktuellen Positionswerts fuer Gewichtung.

    Bevorzugt shares * current_price; faellt auf current_price zurueck (gleich-
    gewichtet, wenn shares fehlen - wie im Contract spezifiziert).
    """
    price = pos.get("price") if isinstance(pos, dict) else None
    if not isinstance(price, dict):
        return None
    cur = price.get("current_price")
    try:
        cur = float(cur)
    except (TypeError, ValueError):
        return None
    if cur <= 0:
        return None
    shares = pos.get("shares")
    try:
        if shares is not None:
            shares = float(shares)
            if shares > 0:
                return shares * cur
    except (TypeError, ValueError):
        pass
    return cur


def compute_correlation_data(market_data: dict) -> dict:
    """Korrelations- & Konzentrationsanalyse ueber alle Positionen mit returns.

    Rueckgabe:
        {
          "top_pairs": [{"a": str, "b": str, "corr": float}, ...],  # |corr|>0.7, max 8
          "herfindahl": float | None,            # HHI der Wertgewichte
          "effective_positions": float | None,   # 1/HHI
          "avg_correlation": float | None,        # Mittel oberes Dreieck
        }
    Defensiv: < 2 Positionen mit returns -> alles None/leer.
    """
    empty = {
        "top_pairs": [],
        "herfindahl": None,
        "effective_positions": None,
        "avg_correlation": None,
    }

    positions = (market_data or {}).get("positions", {})

    returns_by_ticker: dict = {}
    for ticker, pos in positions.items():
        r = _get_returns(pos)
        if r is not None:
            returns_by_ticker[ticker] = r

    if len(returns_by_ticker) < 2:
        return dict(empty)

    # Auf gemeinsame Laenge trimmen (von hinten = juengste Returns behalten).
    min_len = min(len(r) for r in returns_by_ticker.values())
    data = {t: r[-min_len:] for t, r in returns_by_ticker.items()}

    df = pd.DataFrame(data)
    corr = df.corr()

    # Oberes Dreieck (ohne Diagonale) als Paarliste.
    tickers = list(corr.columns)
    pairs = []
    upper_values = []
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            c = corr.iloc[i, j]
            if c is None or (isinstance(c, float) and math.isnan(c)):
                continue
            c = float(c)
            upper_values.append(c)
            pairs.append({"a": tickers[i], "b": tickers[j], "corr": c})

    top_pairs = [
        {"a": p["a"], "b": p["b"], "corr": round(p["corr"], 2)}
        for p in sorted(pairs, key=lambda p: abs(p["corr"]), reverse=True)
        if abs(p["corr"]) > 0.7
    ][:8]

    avg_correlation = round(sum(upper_values) / len(upper_values), 2) if upper_values else None

    # HHI nur ueber Positionen mit returns (gleiche Grundgesamtheit wie corr).
    values = []
    for ticker in tickers:
        v = _position_value(positions.get(ticker, {}))
        values.append(v if v is not None else 0.0)
    total = sum(values)
    herfindahl = None
    effective_positions = None
    if total > 0:
        weights = [v / total for v in values]
        hhi = sum(w * w for w in weights)
        if hhi > 0:
            herfindahl = round(hhi, 4)
            effective_positions = round(1.0 / hhi, 1)

    return {
        "top_pairs": top_pairs,
        "herfindahl": herfindahl,
        "effective_positions": effective_positions,
        "avg_correlation": avg_correlation,
    }


def _vix_value(market_data: dict):
    try:
        return float(market_data.get("indices", {}).get("VIX", {}).get("value"))
    except (TypeError, ValueError, AttributeError):
        return None


def _yield_curve_spread(macro_data: dict):
    try:
        val = macro_data.get("us", {}).get("yield_curve_spread", {}).get("value")
        return float(val) if val is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def classify_regime(market_data: dict, macro_data: dict) -> dict:
    """Regelbasiertes Markt-Regime-Scoring (kein ML/LLM).

    Scoring-Komponenten (je -1/0/+1):
      VIX        : <15 ruhig (+1), 15-25 neutral (0), >25 gestresst (-1)
      Fear&Greed : >60 Gier (+1), 40-60 neutral (0), <40 Angst (-1)
      Yield-Curve: invertiert (10y-2y < 0) (-1), sonst (0)
      Breadth    : Anteil Positionen ueber SMA200 >60% (+1), <40% (-1), sonst (0)
    Summe -> Label: >=2 "Risk-On", <=-2 "Risk-Off", sonst "Neutral".

    Rueckgabe: {"label": str, "score": int, "drivers": [str, ...]}
    drivers sind lesbare deutsche Strings fuer den Prompt.
    """
    score = 0
    drivers = []

    # --- VIX ---
    vix = _vix_value(market_data)
    if vix is not None:
        if vix < 15:
            score += 1
            drivers.append(f"VIX {vix:.0f} (ruhig, +1)")
        elif vix <= 25:
            drivers.append(f"VIX {vix:.0f} (neutral, 0)")
        else:
            score -= 1
            drivers.append(f"VIX {vix:.0f} (gestresst, -1)")
    else:
        drivers.append("VIX n/a")

    # --- Fear & Greed ---
    fg = (macro_data or {}).get("fear_greed") or {}
    fg_val = fg.get("value")
    rating = fg.get("rating")
    try:
        fg_val = float(fg_val) if fg_val is not None else None
    except (TypeError, ValueError):
        fg_val = None
    if fg_val is not None:
        rating_str = f", {rating}" if rating else ""
        if fg_val > 60:
            score += 1
            drivers.append(f"Fear&Greed {fg_val:.0f} (Gier{rating_str}, +1)")
        elif fg_val >= 40:
            drivers.append(f"Fear&Greed {fg_val:.0f} (neutral{rating_str}, 0)")
        else:
            score -= 1
            drivers.append(f"Fear&Greed {fg_val:.0f} (Angst{rating_str}, -1)")
    else:
        drivers.append("Fear&Greed n/a")

    # --- Yield Curve ---
    spread = _yield_curve_spread(macro_data)
    if spread is not None:
        if spread < 0:
            score -= 1
            drivers.append(f"Zinskurve {spread:+.2f}pp (invertiert, -1)")
        else:
            drivers.append(f"Zinskurve {spread:+.2f}pp (normal, 0)")
    else:
        drivers.append("Zinskurve n/a")

    # --- Breadth (Anteil Positionen ueber SMA200) ---
    # Nur Positionen mit echtem bool-Signal zaehlen. market.py setzt
    # above_sma200=None bei zu kurzer Historie -> die schliessen wir aus,
    # sonst wuerde die Breadth nach unten verzerrt.
    positions = (market_data or {}).get("positions", {})
    above = 0
    counted = 0
    for pos in positions.values():
        price = pos.get("price") if isinstance(pos, dict) else None
        if not isinstance(price, dict):
            continue
        flag = price.get("above_sma200")
        if not isinstance(flag, bool):
            continue
        counted += 1
        if flag:
            above += 1
    if counted > 0:
        breadth = above / counted
        pct = breadth * 100
        if breadth > 0.60:
            score += 1
            drivers.append(f"Breadth {pct:.0f}% ueber SMA200 (stark, +1)")
        elif breadth < 0.40:
            score -= 1
            drivers.append(f"Breadth {pct:.0f}% ueber SMA200 (schwach, -1)")
        else:
            drivers.append(f"Breadth {pct:.0f}% ueber SMA200 (neutral, 0)")
    else:
        drivers.append("Breadth n/a")

    if score >= 2:
        label = "Risk-On"
    elif score <= -2:
        label = "Risk-Off"
    else:
        label = "Neutral"

    return {"label": label, "score": score, "drivers": drivers}
