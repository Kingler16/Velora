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
        "market_regime": market_regime,
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


def _plausi_check(rec: dict, market_data: dict | None) -> tuple[bool, str]:
    """Deterministischer Sanity-Check der Order-Levels gegen Live-Kurse — fängt
    halluzinierte/vertippte Preise ab, bevor sie als Order in der UI landen.
    0 LLM-Zeit. Returns (ok, grund_wenn_gedroppt)."""
    if not market_data:
        return True, ""
    ticker = rec.get("ticker")
    pos = (market_data.get("positions") or {}).get(ticker) or (market_data.get("watchlist") or {}).get(ticker)
    live = (pos or {}).get("price", {}).get("current_price")
    entry = rec.get("entry_price")
    if live and entry:
        try:
            if abs(float(entry) / float(live) - 1) > 0.30:
                return False, f"entry_price {entry} weicht >30% vom Live-Kurs {live} ab (Tippfehler/Halluzination?)"
        except (ValueError, ZeroDivisionError, TypeError):
            pass
    stop = rec.get("stop_loss")
    target = rec.get("target_price")
    if entry and stop and target:
        is_sell = rec.get("action") == "sell"
        try:
            ok_order = (target < entry < stop) if is_sell else (stop < entry < target)
        except TypeError:
            ok_order = True
        if not ok_order:
            return False, f"Order-Levels unplausibel (stop={stop}, entry={entry}, target={target}, sell={is_sell})"
    return True, ""


def save_recommendations(recommendations: list[dict], overview: dict | None = None, market_data: dict | None = None):
    """Speichert neue Empfehlungen. Ersetzt offene Duplikate für denselben Ticker.

    Verwirft alles was nicht actionable ist (hold, watch ohne Order, leeres Reasoning,
    fehlende Stückzahl). Was gedroppt wurde, steht im Log.

    Wenn ein Mandat existiert (config/mandate.json), wird zusätzlich gegen die
    strukturierten Regeln geprüft: block-Verstöße werden verworfen, warn-Verstöße
    landen als rec["mandate_warnings"] (UI zeigt sie als Hinweis). `overview` =
    compute_portfolio_overview, damit Allokations-Regeln gegen echte Werte rechnen.
    """
    from src.analysis.mandate import load_mandate, validate_against_mandate

    existing = _load_json("recommendations.json", [])
    mandate = load_mandate()
    accepted = 0
    dropped = 0

    for rec in recommendations:
        ok, reason = _is_actionable(rec)
        if not ok:
            logger.info("Recommendation dropped (%s): %s", rec.get("ticker", "?"), reason)
            dropped += 1
            continue

        if mandate:
            verdict, violations = validate_against_mandate(rec, mandate, overview)
            if verdict == "block":
                logger.info("Recommendation mandate-blocked (%s): %s", rec.get("ticker", "?"), "; ".join(violations))
                dropped += 1
                continue
            if verdict == "warn":
                rec["mandate_warnings"] = violations

        ok_p, reason_p = _plausi_check(rec, market_data)
        if not ok_p:
            logger.info("Recommendation plausi-dropped (%s): %s", rec.get("ticker", "?"), reason_p)
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
    # Truncation nach Status trennen: alle offenen behalten + die letzten 40 geschlossenen.
    # Vorher kürzte existing[-50:] rein FIFO — das warf die abgeschlossenen Recs (= die
    # Lern-Daten mit echten Outcomes) zuerst weg, sobald viele offene nachrückten.
    open_r = [r for r in existing if r.get("status") == "open"]
    closed_r = [r for r in existing if r.get("status") != "open"]
    existing = open_r + closed_r[-40:]
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

        # Lookup auf gehaltene Ticker UND Watchlist — watch/buy-Limit-Empfehlungen
        # auf neue Ideen sind nicht im Portfolio, müssen aber getrackt werden.
        pos = market_data.get("positions", {}).get(ticker) or market_data.get("watchlist", {}).get(ticker)
        if not ticker or not pos:
            continue

        current_price = pos.get("price", {}).get("current_price")
        if not current_price:
            continue

        target = rec.get("target_price")
        stop_loss = rec.get("stop_loss")
        entry_price = rec.get("entry_price")

        # Sell-Empfehlungen sind invertiert: Ziel liegt UNTER, Stop ÜBER dem Kurs.
        # target/stop können None sein (hold nur mit Stop, sell ohne Ziel) — nie
        # gegen None vergleichen, das riss als TypeError das ganze Briefing ab.
        is_sell = rec.get("action") == "sell"
        hit_target = target is not None and ((current_price <= target) if is_sell else (current_price >= target))
        hit_stop = stop_loss is not None and ((current_price >= stop_loss) if is_sell else (current_price <= stop_loss))

        if target and hit_target:
            rec["status"] = "target_hit"
            rec["outcome"] = f"Ziel erreicht bei {current_price}"
            rec["closed_date"] = now.isoformat()
            if entry_price:
                raw = (current_price / entry_price - 1) * 100
                rec["realized_pct"] = round(-raw if is_sell else raw, 2)
            updated = True
        elif stop_loss and hit_stop:
            rec["status"] = "stop_hit"
            rec["outcome"] = f"Stop ausgelöst bei {current_price}"
            rec["closed_date"] = now.isoformat()
            if entry_price:
                raw = (current_price / entry_price - 1) * 100
                rec["realized_pct"] = round(-raw if is_sell else raw, 2)
            updated = True
        elif entry_price:
            raw = (current_price / entry_price - 1) * 100
            rec["unrealized_pct"] = round(-raw if is_sell else raw, 2)

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


def add_position_thesis(ticker: str, thesis: str, price_target=None):
    """Hängt eine NEUE Thesen-Version an (statt die alte zu überschreiben).

    So bleibt die Prognose-Historie erhalten: beim nächsten Briefing kann die alte
    These gegen den tatsächlichen Verlauf geprüft werden. Migrationssicher gegen das
    alte Single-Dict-Format."""
    notes = _load_json("notes.json", {})
    theses = notes.setdefault("position_theses", {})
    entry = theses.get(ticker)
    if isinstance(entry, list):
        history = entry
    elif isinstance(entry, dict):
        history = [entry]  # Migration: altes Single-Dict in Liste überführen
    else:
        history = []
    history.append({
        "thesis": thesis,
        "date": datetime.now().isoformat(),
        "price_target": price_target,
    })
    theses[ticker] = history[-5:]  # letzte 5 Versionen behalten
    _save_json("notes.json", notes)


TRADE_HISTORY_MAX = 40


def record_trade(action: str, ticker: str, shares: float, price=None, account=None,
                 shares_before=None, shares_after=None):
    """Hängt einen AUSGEFÜHRTEN Trade an die Trade-History (memory/trade_history.json).

    Diese fliesst ins nächste Briefing (get_context_for_prompt), damit die Analyse
    Käufe/Verkäufe als Ereignis 'sieht' statt nur die veränderte Stückzahl — sonst
    übernimmt das LLM veraltete Positions-Thesen (z.B. 'grösste Einzelwette' für eine
    längst reduzierte Position). Best-effort: ein Fehler hier darf nie den Trade
    selbst (Portfolio-Write) gefährden."""
    try:
        history = _load_json("trade_history.json", [])
        history.append({
            "date": datetime.now().isoformat(),
            "action": action,
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "account": account,
            "shares_before": shares_before,
            "shares_after": shares_after,
        })
        _save_json("trade_history.json", history[-TRADE_HISTORY_MAX:])
    except Exception:
        logger.exception("record_trade fehlgeschlagen (%s %s) — Trade selbst ist unberührt", action, ticker)


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
        parts.append("\n=== ABGESCHLOSSENE EMPFEHLUNGEN (lerne daraus — mach ein kurzes Post-Mortem in der BILANZ: war die These richtig/falsch, warum?) ===")
        for r in closed_recs[-5:]:
            rp = f" [{r['realized_pct']:+.1f}%]" if r.get("realized_pct") is not None else ""
            why = f" | These war: {r['reasoning'][:90]}" if r.get("reasoning") else ""
            parts.append(f"- {r['date'][:10]} {r.get('ticker','?')}: {r.get('action','?')} -> {r.get('outcome','?')}{rp}{why}")

    # Letzte ausgeführte Trades (vom User) — damit die Analyse sie als Ereignis
    # berücksichtigt und nicht an veralteten Thesen festhält.
    trades = _load_json("trade_history.json", [])
    if trades:
        parts.append("\n=== DEINE LETZTEN TRADES (vom User ausgeführt — berücksichtige sie! Ein "
                     "Verkauf/Zukauf ändert Positionsgröße und Gewicht; eine alte These kann damit "
                     "überholt sein. Behandle jede Position nach ihrer AKTUELLEN Größe, nicht nach der "
                     "alten Erzählung) ===")
        for tr in trades[-8:]:
            verb = "GEKAUFT" if tr.get("action") == "buy" else "VERKAUFT"
            px = f" @ {tr['price']:.2f}€" if tr.get("price") else ""
            sz = ""
            sb, sa = tr.get("shares_before"), tr.get("shares_after")
            if sb is not None and sa is not None:
                sz = f" (Position {sb:.2f} → {sa:.2f} Stk)"
            parts.append(f"- {tr.get('date','')[:10]}: {verb} {tr.get('shares','?')} Stk "
                         f"{tr.get('ticker','?')}{px}{sz}")

    # Position-Thesen (versioniert — alte Prognose gegen Realität prüfen)
    notes = memory["notes"]
    theses = notes.get("position_theses", {})
    if theses:
        parts.append("\n=== INVESTMENT-THESEN PRO POSITION (prüfe ob alte Prognosen eingetreten sind) ===")
        for ticker, t in theses.items():
            if isinstance(t, list) and t:
                latest = t[-1]
                line = f"- {ticker}: {latest.get('thesis','')} ({latest.get('date','')[:10]})"
                if len(t) > 1:
                    prev = t[-2]
                    line += f"\n    [vorherige These {prev.get('date','')[:10]}: {(prev.get('thesis') or '')[:80]} — eingetreten?]"
                parts.append(line)
            elif isinstance(t, dict):
                parts.append(f"- {ticker}: {t.get('thesis','')} ({t.get('date','')[:10]})")

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
