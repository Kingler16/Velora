"""
Cash-Einsatzplan — Cash oberhalb des Mandats-Bands planmässig investieren.

Hintergrund: Ein Cash-Ziel ohne Obergrenze und ohne Plan führt dazu, dass das LLM
Briefing für Briefing „hohe Cash-Quote ist kein Handlungsdruck" zitiert und
nichts investiert. Der Code rechnet deshalb den Überschuss über dem Band aus,
teilt ihn in feste Monatstranchen und gibt dem Briefing ein konkretes €-Budget.
Das LLM entscheidet weiter, WORIN investiert wird — und muss begründen, wenn nicht.

Opt-in über das Mandat:
    "policy": {
      "cash": {"min": 15, "target": 20, "max": 25},          # % vom Gesamtvermögen
      "deployment": {"months": 4, "parking": "none"}         # optional
    }
Ohne policy.cash.max ist der Plan aus (None) und alles läuft wie bisher.

Der Plan rechnet aus dem echten Cash-Stand, nicht aus Empfehlungen: Was der
Nutzer tatsächlich kauft, senkt den Überschuss und damit das Restbudget.
Ungenutzte Tranchen werden NICHT ins nächste Monatsbudget geschoben (sonst staut
sich das Cash wieder), sondern als Rückstand ausgewiesen und nach der
parking-Regel behandelt.
"""

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
STATE_PATH = MEMORY_DIR / "cash_plan.json"

DEFAULT_MONTHS = 4
MAX_MONTHS = 6
PARKING_OPTIONS = ("none", "existing_positions")
MIN_EXCESS_EUR = 250.0        # darunter lohnt kein Plan (Ordergebühren)
# Nur für die Schätzung des Renditeverzichts, nie für Entscheidungen:
# langfristige nominale Aktienrendite p. a.
EXPECTED_EQUITY_RETURN_PCT = 7.0


def cash_band(mandate: dict | None) -> dict | None:
    """{"min", "target", "max"} aus policy.cash — None, wenn keine Obergrenze gesetzt ist."""
    cash = ((mandate or {}).get("policy") or {}).get("cash") or {}
    if cash.get("max") is None:
        return None
    target = cash.get("target", ((mandate or {}).get("targets") or {}).get("cash_pct"))
    return {"min": cash.get("min"), "target": target, "max": cash["max"]}


def deployment_policy(mandate: dict | None) -> dict:
    dep = ((mandate or {}).get("policy") or {}).get("deployment") or {}
    months = dep.get("months") or DEFAULT_MONTHS
    months = max(1, min(MAX_MONTHS, int(months)))
    parking = dep.get("parking") if dep.get("parking") in PARKING_OPTIONS else "none"
    return {"months": months, "parking": parking}


def _month_index(start: date, today: date) -> int:
    return (today.year - start.year) * 12 + (today.month - start.month)


def _load_state(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("cash_plan.json nicht lesbar, starte neu: %s", e)
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _cash_rate_pct(overview: dict) -> float:
    """Gewichteter Zins über alle Bankkonten."""
    accounts = overview.get("bank_accounts") or []
    total = sum(a.get("value") or 0 for a in accounts)
    if not total:
        return 0.0
    return sum((a.get("value") or 0) * (a.get("interest") or 0) for a in accounts) / total


def compute_cash_plan(overview: dict | None, mandate: dict | None, today: date | None = None,
                      persist: bool = True) -> dict | None:
    """Status des Einsatzplans. None, wenn das Mandat kein Cash-Band mit Obergrenze hat.

    persist=False rechnet nur (z. B. für Anzeigen) und startet bzw. beendet keinen Plan.
    """
    band = cash_band(mandate)
    if not band or not overview:
        return None
    total = overview.get("total_value_eur") or 0
    if total <= 0:
        return None
    today = today or date.today()
    cash = overview.get("cash_total") or 0
    dep = deployment_policy(mandate)
    excess = cash - band["max"] / 100 * total

    state = _load_state(STATE_PATH)
    plan = state.get("plan")
    changed = False
    if plan and _month_index(date.fromisoformat(plan["start"]), today) >= plan["months"]:
        state.setdefault("history", []).append({**plan, "ended": today.isoformat(),
                                                "excess_left_eur": round(max(excess, 0), 2)})
        plan, changed = None, True
    if excess < MIN_EXCESS_EUR and plan:
        state.setdefault("history", []).append({**plan, "ended": today.isoformat(), "excess_left_eur": 0})
        plan, changed = None, True
    if excess >= MIN_EXCESS_EUR and not plan:
        plan = {"start": today.replace(day=1).isoformat(), "months": dep["months"],
                "total_excess_eur": round(excess, 2)}
        changed = True
        logger.info("Cash-Einsatzplan gestartet: %.0f € über %d Monate", excess, dep["months"])
    if persist and changed:
        state["plan"] = plan
        state["history"] = (state.get("history") or [])[-24:]
        _save_state(STATE_PATH, state)

    cash_rate = _cash_rate_pct(overview)
    result = {
        "band": band,
        "cash_eur": round(cash, 2),
        "cash_pct": round(cash / total * 100, 1),
        "excess_eur": round(max(excess, 0), 2),
        "cash_rate_pct": round(cash_rate, 2),
        "drag_eur_per_year": round(max(excess, 0) * max(EXPECTED_EQUITY_RETURN_PCT - cash_rate, 0) / 100),
        "parking": dep["parking"],
        "below_min": band.get("min") is not None and cash / total * 100 < band["min"],
        "active": bool(plan),
    }
    if not plan:
        return result

    k = _month_index(date.fromisoformat(plan["start"]), today)
    months = plan["months"]
    tranche = plan["total_excess_eur"] / months
    # Soll-Überschuss am Ende dieses Monats; das Budget ist der Weg dorthin,
    # gedeckelt auf EINE Tranche — Verpasstes wird nicht nachgeschoben.
    target_end = plan["total_excess_eur"] * (1 - (k + 1) / months)
    gap = max(excess - target_end, 0)
    result.update({
        "start": plan["start"],
        "month": k + 1,
        "months": months,
        "total_excess_eur": plan["total_excess_eur"],
        "tranche_eur": round(tranche, 2),
        "budget_eur": round(min(gap, tranche), 2),
        "backlog_eur": round(max(gap - tranche, 0), 2),
    })
    return result


def _eur(v: float) -> str:
    return f"{v:,.0f} €".replace(",", ".")


def _pct(v: float) -> str:
    return f"{v:.1f} %".replace(".", ",")


_PARKING_TEXT = {
    "none": "Parking: keines — der Rückstand bleibt Cash und wird als Renditeverzicht ausgewiesen.",
    "existing_positions": ("Parking: bestehende Positionen — der Rückstand geht anteilig in Positionen mit "
                           "intakter These (nicht eingefroren, unter allen Mandatsgrenzen). Schlage dafür "
                           "konkrete Zukäufe mit Stückzahl vor."),
}


def format_cash_plan(plan: dict | None) -> str:
    """Prompt-Sektion. "" wenn kein Plan konfiguriert ist."""
    if not plan:
        return ""
    band = plan["band"]
    band_parts = [f"min {band['min']} %" if band.get("min") is not None else None,
                  f"Ziel {band['target']} %" if band.get("target") is not None else None,
                  f"max {band['max']} %"]
    lines = [f"Cash-Band laut Mandat: {' · '.join(p for p in band_parts if p)} — "
             f"Ist {_pct(plan['cash_pct'])} ({_eur(plan['cash_eur'])})"]
    if plan.get("below_min"):
        lines.append("Cash liegt UNTER dem Minimum: keine neuen Käufe aus Cash, bis der Puffer wieder steht.")
        return "\n".join(lines)
    if not plan["active"]:
        lines.append("Cash liegt im Band — kein Einsatzbudget, kein Handlungsbedarf aus der Cash-Quote.")
        return "\n".join(lines)

    lines.append(f"Überschuss über dem Band: {_eur(plan['excess_eur'])} · geschätzter Renditeverzicht "
                 f"≈ {_eur(plan['drag_eur_per_year'])}/Jahr (Annahme {EXPECTED_EQUITY_RETURN_PCT:.0f} % "
                 f"Aktienrendite p. a. gegen {_pct(plan['cash_rate_pct'])} Cash-Zins)")
    start = date.fromisoformat(plan["start"])
    lines.append(f"Einsatzplan: Monat {plan['month']} von {plan['months']} (Start {start.strftime('%m/%Y')}, "
                 f"Ausgangsüberschuss {_eur(plan['total_excess_eur'])}, Tranche {_eur(plan['tranche_eur'])}/Monat)")
    lines.append(f"BUDGET DIESEN MONAT: {_eur(plan['budget_eur'])}")
    if plan["backlog_eur"] > 0:
        lines.append(f"Rückstand aus verfallenen Tranchen bzw. neuen Zuflüssen: {_eur(plan['backlog_eur'])}. "
                     + _PARKING_TEXT[plan["parking"]])
    lines.append(
        "REGEL: Nicht investiertes Kapital oberhalb des Bands ist ein Fehler wie ein Fehlkauf — beide kosten "
        "Geld. Setze das Monatsbudget in deine überzeugendsten Ideen (Kandidaten, Watchlist oder Aufstockung "
        "bestehender Positionen mit intakter These); Mandatsgrenzen und Order-Deckel gelten weiter, mehrere "
        "kleinere Orders sind ok. Wurde eine Kaufempfehlung dieses Monats noch nicht ausgeführt, wiederhole sie "
        "nicht, sondern verweise darauf. Investierst du weniger als das Budget, nenne den Restbetrag und begründe "
        "PRO geprüftem Kandidaten mit einem dieser Gründe: (a) erwartete Rendite unter dem Cash-Zins, "
        "(b) Mandatsgrenze verletzt, (c) Bewertung klar über fairem Wert, (d) Quartalszahlen innerhalb von "
        "5 Handelstagen, (e) These nicht in zwei Sätzen erklärbar. Kein gültiger Grund sind Marktstimmung, "
        "Regime, Fear & Greed oder „unsichere Lage“ — das wäre Market-Timing."
    )
    return "\n".join(lines)
