"""
Memory-System für den Vermögensberater.
Speichert vergangene Analysen, Empfehlungen und deren Outcomes.
Verhindert Wiederholungen und ermöglicht Lernen.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"


def _ensure_memory_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def load_memory() -> dict:
    """Lädt das gesamte Memory-System."""
    _ensure_memory_dir()
    memory = {
        "briefings": _load_json("briefings.json", []),
        "recommendations": _load_json("recommendations.json", []),
        "monthly_snapshots": _load_json("monthly_snapshots.json", []),
        "notes": _load_json("notes.json", {
            "market_regime": None,
            "position_theses": {},
            "user_preferences": [],
            "key_insights": [],
        }),
    }
    return memory


def _load_json(filename: str, default):
    path = MEMORY_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default


def _save_json(filename: str, data):
    _ensure_memory_dir()
    path = MEMORY_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def save_briefing_summary(summary: str, recommendations: list[dict], market_regime: str = None, full_text: str = None):
    """Speichert eine Zusammenfassung des Briefings."""
    briefings = _load_json("briefings.json", [])
    briefings.append({
        "date": datetime.now().isoformat(),
        "summary": summary,
        "recommendation_count": len(recommendations),
        "had_actions": any(r.get("action") not in (None, "hold", "watch") for r in recommendations),
        "full_text": full_text,
    })
    # Nur die letzten 20 Briefings behalten
    briefings = briefings[-20:]
    _save_json("briefings.json", briefings)


def _is_actionable(rec: dict) -> tuple[bool, str]:
    """Prüft ob eine Empfehlung eine echte Aktion ist — sonst Noise.

    Returns (ok, reason_if_dropped). Filter sind strikt, aber decken die drei
    realen Aktions-Muster ab:
      - buy/sell mit Order-Größe (Markt- oder Limit-Order ausführen)
      - watch mit entry_price (Limit-Order anlegen)
      - hold mit stop_loss (Stop nachziehen / setzen — User muss zum Broker)
    """
    action = rec.get("action")

    if action not in ("buy", "sell", "watch", "hold"):
        return False, f"action='{action}' ist kein gültiger Wert (buy/sell/watch/hold)"

    reasoning = (rec.get("reasoning") or "").strip()
    if len(reasoning) < 20:
        return False, f"reasoning fehlt oder zu kurz ({len(reasoning)} Zeichen)"

    if action == "hold":
        # "Halten ohne alles" = reines Noise. Aber "halten + Stop setzen/nachziehen"
        # ist eine konkrete Order-Aktion am Broker und bleibt sichtbar.
        if not rec.get("stop_loss"):
            return False, "action=hold ohne stop_loss (= reines 'nichts tun', keine Order-Aktion)"
        return True, ""

    if action == "watch" and not rec.get("entry_price"):
        return False, "watch ohne entry_price (= keine konkrete Limit-Order, nur Notiz)"

    if action in ("buy", "sell"):
        has_size = rec.get("shares") or rec.get("sell_pct")
        if not has_size:
            return False, "buy/sell ohne shares UND ohne sell_pct (= unklare Order-Größe)"

    return True, ""


def save_recommendations(recommendations: list[dict]):
    """Speichert neue Empfehlungen. Ersetzt offene Duplikate für denselben Ticker.

    Verwirft alles was nicht actionable ist (hold, watch ohne Order, leeres Reasoning,
    fehlende Stückzahl). Was gedroppt wurde, steht im Log — damit transparent ist
    warum eine vermeintliche Empfehlung nicht in der UI auftaucht.
    """
    existing = _load_json("recommendations.json", [])
    accepted = 0
    dropped = 0

    for rec in recommendations:
        ok, reason = _is_actionable(rec)
        if not ok:
            logger.info("Recommendation dropped (%s): %s", rec.get("ticker", "?"), reason)
            dropped += 1
            continue

        rec["date"] = datetime.now().isoformat()
        rec["status"] = "open"
        rec["outcome"] = None

        # Offene Empfehlung für denselben Ticker ersetzen statt duplizieren
        replaced = False
        for i, old in enumerate(existing):
            if old.get("ticker") == rec.get("ticker") and old.get("status") == "open":
                existing[i] = rec
                replaced = True
                break
        if not replaced:
            existing.append(rec)
        accepted += 1

    logger.info("save_recommendations: %d accepted, %d dropped", accepted, dropped)
    # Nur die letzten 50 behalten
    existing = existing[-50:]
    _save_json("recommendations.json", existing)


WATCH_EXPIRE_DAYS = 30


def update_recommendation_outcomes(market_data: dict):
    """Aktualisiert Outcomes offener Empfehlungen basierend auf aktuellen Kursen.

    Zusätzlich: offene watch-Empfehlungen, deren entry_price nach 30 Tagen nicht erreicht
    wurde, werden auf 'cancelled' gesetzt — sonst sammeln sich tote Limit-Order-Vorschläge
    in der UI an. Buy/Sell laufen nicht ab (klare Marktorder mit Stop/Target tracking).
    """
    recs = _load_json("recommendations.json", [])
    updated = False
    now = datetime.now()

    for rec in recs:
        if rec.get("status") != "open":
            continue
        ticker = rec.get("ticker")

        # Auto-Expire alter watch-Empfehlungen (unabhängig von market_data)
        if rec.get("action") == "watch":
            date_str = rec.get("date", "")
            try:
                rec_date = datetime.fromisoformat(date_str)
                age_days = (now - rec_date).days
                if age_days >= WATCH_EXPIRE_DAYS:
                    rec["status"] = "cancelled"
                    rec["outcome"] = f"Auto-abgelaufen nach {age_days} Tagen — Limit nie erreicht"
                    logger.info("Watch-Empfehlung %s nach %d Tagen auto-cancelled", ticker, age_days)
                    updated = True
                    continue
            except (ValueError, TypeError):
                pass

        if not ticker or ticker not in market_data.get("positions", {}):
            continue

        current_price = market_data["positions"][ticker].get("price", {}).get("current_price")
        if not current_price:
            continue

        target = rec.get("target_price")
        stop_loss = rec.get("stop_loss")
        entry_price = rec.get("entry_price")

        if target and current_price >= target:
            rec["status"] = "target_hit"
            rec["outcome"] = f"Ziel erreicht bei {current_price}"
            updated = True
        elif stop_loss and current_price <= stop_loss:
            rec["status"] = "stop_hit"
            rec["outcome"] = f"Stop-Loss ausgelöst bei {current_price}"
            updated = True
        elif entry_price:
            rec["unrealized_pct"] = round((current_price / entry_price - 1) * 100, 2)

    if updated:
        _save_json("recommendations.json", recs)

    return recs


def save_monthly_snapshot(snapshot: dict):
    """Speichert monatlichen Portfolio-Snapshot für Vergleiche."""
    snapshots = _load_json("monthly_snapshots.json", [])
    snapshot["date"] = datetime.now().isoformat()
    snapshots.append(snapshot)
    # 24 Monate behalten
    snapshots = snapshots[-24:]
    _save_json("monthly_snapshots.json", snapshots)


def update_notes(key: str, value):
    """Aktualisiert eine Notiz im Memory."""
    notes = _load_json("notes.json", {})
    notes[key] = value
    _save_json("notes.json", notes)


def add_position_thesis(ticker: str, thesis: str):
    """Speichert die Investment-These für eine Position."""
    notes = _load_json("notes.json", {})
    if "position_theses" not in notes:
        notes["position_theses"] = {}
    notes["position_theses"][ticker] = {
        "thesis": thesis,
        "date": datetime.now().isoformat(),
    }
    _save_json("notes.json", notes)


def get_context_for_prompt() -> str:
    """Baut den Memory-Kontext für den Claude-Prompt zusammen."""
    memory = load_memory()
    parts = []

    # Letzte Briefings (damit er sich nicht wiederholt)
    briefings = memory["briefings"]
    if briefings:
        parts.append("=== LETZTE BRIEFINGS (wiederhole dich NICHT) ===")
        for b in briefings[-5:]:
            actions = "ja" if b.get("had_actions") else "nein"
            parts.append(f"- {b['date'][:10]}: {b['summary']} [Aktionen empfohlen: {actions}]")

    # Offene Empfehlungen + Outcomes
    recs = memory["recommendations"]
    open_recs = [r for r in recs if r.get("status") == "open"]
    closed_recs = [r for r in recs if r.get("status") != "open"]

    if open_recs:
        parts.append("\n=== OFFENE EMPFEHLUNGEN (tracke diese) ===")
        for r in open_recs[-10:]:
            pnl = f", aktuell {r.get('unrealized_pct', '?')}%" if r.get("unrealized_pct") is not None else ""
            parts.append(f"- {r['date'][:10]} {r.get('ticker','?')}: {r.get('action','?')} bei {r.get('entry_price','?')}{pnl}")

    if closed_recs:
        parts.append("\n=== ABGESCHLOSSENE EMPFEHLUNGEN (lerne daraus) ===")
        for r in closed_recs[-5:]:
            parts.append(f"- {r['date'][:10]} {r.get('ticker','?')}: {r.get('action','?')} -> {r.get('outcome','?')}")

    # Position-Thesen
    notes = memory["notes"]
    theses = notes.get("position_theses", {})
    if theses:
        parts.append("\n=== INVESTMENT-THESEN PRO POSITION ===")
        for ticker, t in theses.items():
            parts.append(f"- {ticker}: {t['thesis']} ({t['date'][:10]})")

    # Market Regime
    if notes.get("market_regime"):
        parts.append(f"\n=== LETZTES MARKT-REGIME === \n{notes['market_regime']}")

    # Key Insights
    insights = notes.get("key_insights", [])
    if insights:
        parts.append("\n=== KEY INSIGHTS (behalte diese im Hinterkopf) ===")
        for i in insights[-10:]:
            parts.append(f"- {i}")

    return "\n".join(parts) if parts else "Keine vorherigen Daten vorhanden. Dies ist das erste Briefing."
