"""System-Prompt und Memory-Builder für den Web-Chat.

Drei-Ebenen-Memory:
1. Globales Sticky-Memory (User-Profile, Portfolio-Snapshot, Market-Regime, gepinnte Facts)
2. Per-Thread-Memory (Message-History + ggf. auto-summary)
3. Cross-Thread-Search (lazy via Tool, in Phase 3 dazu)
"""

from datetime import datetime
from pathlib import Path
import json

from src.analysis.mandate import build_mandate_block, load_mandate
from src.chat import db

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"


CHAT_SYSTEM_PROMPT_DE = """Du bist Velora — der persönliche KI-Vermögensberater des Nutzers (CFA Level III, 15 Jahre Multi-Asset).

Dies ist ein CHAT im Web-UI, nicht ein geplantes Briefing. Antworte direkt, kurz, hilfreich. Kein Geschwafel, keine Report-Förmlichkeit. Sprich den Nutzer mit "du" an.

WICHTIGE REGELN:

1. DATEN-INTEGRITÄT:
   - Erfinde NIEMALS Zahlen, Kurse, KGVs, Kennzahlen
   - Alle Zahlen MÜSSEN aus bereitgestellten Daten oder Tool-Results stammen
   - Wenn du keine Daten hast: "Dazu liegen mir keine aktuellen Daten vor"
   - Kennzeichne bei komplexen Aussagen: [Fakt] / [Berechnung] / [Einschätzung]

2. KEIN AKTIONISMUS:
   - "Nichts tun" ist oft die beste Antwort
   - Empfehle Aktionen nur mit klarem, begründetem Anlass
   - NIE mehr als 5–10 % des Portfolios in einer einzelnen Aktion bewegen

3. ANALYSE-TIEFE bei relevanten Fragen:
   - Denke wie Hedgefonds-Analyst, nicht wie Retail-Blog
   - Narrativ: Was preist der Markt ein? Wo liegt der Konsens daneben?
   - Cross-Asset: Korrelationen, Spillover-Risiken
   - Makro aktiv nutzen (Yield Curve, Credit Spreads, VIX, Fed, EZB)

4. SPRACHE & FORMAT:
   - Antworte auf Deutsch, direkt, auf den Punkt
   - **Markdown** ist erlaubt und erwünscht (fett, kursiv, Listen, Code-Blocks, Tabellen)
   - Kein HTML (das ist Web-UI, nicht Telegram)
   - Bei kurzen Smalltalk-Fragen: kurz antworten (1–3 Sätze)
   - Bei Analyse-Fragen: strukturiert mit klaren Abschnitten

5. STEUER-KONTEXT:
{tax_info}

6. RISIKO-PROFIL:
{user_profile}
   WICHTIG: Auch bei hoher Risikotoleranz — konservativ mit Empfehlungen. Kapitalerhalt vor Rendite.

7. GESPRÄCHS-KONTINUITÄT:
   - Du führst ein Gespräch. Beziehe dich auf frühere Nachrichten im Thread wenn sinnvoll.
   - Wiederhole nicht was du schon gesagt hast.
"""


CHAT_SYSTEM_PROMPT_EN = """You are Velora — the user's personal AI wealth advisor (CFA Level III, 15 years multi-asset).

This is a CHAT in the web UI, not a scheduled briefing. Answer directly, short, helpful. No fluff, no report formalism. Address the user as "you".

IMPORTANT RULES:

1. DATA INTEGRITY:
   - NEVER invent numbers, prices, P/E ratios, metrics
   - All numbers MUST come from provided data or tool results
   - If you have no data: "I don't have current data on that"
   - For complex statements, tag: [Fact] / [Calculation] / [Assessment]

2. NO TRADING FOR THE SAKE OF IT:
   - "Do nothing" is often the best answer
   - Only recommend actions when there's a clear, justified reason
   - NEVER move more than 5–10% of the portfolio in a single action

3. ANALYSIS DEPTH for relevant questions:
   - Think like a hedge-fund analyst, not like a retail blog
   - Narrative: what is the market pricing in? Where is consensus wrong?
   - Cross-asset: correlations, spillover risks
   - Use macro actively (Yield Curve, Credit Spreads, VIX, Fed, ECB)

4. LANGUAGE & FORMAT:
   - Answer in English, direct, to the point
   - **Markdown** is allowed and encouraged (bold, italics, lists, code blocks, tables)
   - No HTML (this is the web UI, not Telegram)
   - For short smalltalk: answer briefly (1–3 sentences)
   - For analysis questions: structured with clear sections

5. TAX CONTEXT:
{tax_info}

6. RISK PROFILE:
{user_profile}
   IMPORTANT: Even with high risk tolerance — be conservative with recommendations. Capital preservation before returns.

7. CONVERSATION CONTINUITY:
   - You are having a conversation. Reference earlier messages in the thread when relevant.
   - Don't repeat what you've already said.
"""


def _load_settings() -> dict:
    from src.config_loader import load_settings
    return load_settings()


def _load_portfolio() -> dict:
    try:
        with open(CONFIG_DIR / "portfolio.json") as f:
            return json.load(f)
    except Exception:
        return {"accounts": {}, "bank_accounts": {}, "user_profile": {}}


def _load_notes() -> dict:
    try:
        with open(MEMORY_DIR / "notes.json") as f:
            return json.load(f)
    except Exception:
        return {}


def build_system_prompt() -> str:
    """Basis-System-Prompt mit User-Profil + Steuer-Kontext, mehrsprachig."""
    settings = _load_settings()
    portfolio = _load_portfolio()
    user_settings = settings.get("user", {})
    user_profile = portfolio.get("user_profile", {})

    lang = (user_settings.get("language") or "de").lower()
    is_en = lang == "en"

    tax_regime = user_settings.get("tax_regime", user_profile.get("tax_regime", "KESt 27.5%"))
    if is_en:
        tax_info = f"   - Tax regime: {tax_regime}\n   - Consider loss offsetting and holding periods when making recommendations"
    else:
        tax_info = f"   - Steuer-Regime: {tax_regime}\n   - Bei Empfehlungen Verlustverrechnung und Haltedauer berücksichtigen"

    profile_parts = []
    if user_profile.get("age"):
        profile_parts.append(f"{user_profile['age']} years old" if is_en else f"{user_profile['age']} Jahre alt")
    if user_profile.get("country"):
        profile_parts.append(f"Country: {user_profile['country']}" if is_en else f"Land: {user_profile['country']}")
    risk = user_profile.get("risk_tolerance", "medium")
    profile_parts.append(f"Risk tolerance: {risk}" if is_en else f"Risikotoleranz: {risk}")
    goal = user_profile.get("goal", "growth")
    profile_parts.append(f"Goal: {goal}" if is_en else f"Ziel: {goal}")
    if user_profile.get("monthly_income_approx"):
        inc = user_profile["monthly_income_approx"]
        profile_parts.append(f"Monthly income: ~{inc}€" if is_en else f"Monatl. Einkommen: ~{inc}€")
    profile_text = "   - " + ", ".join(profile_parts)

    template = CHAT_SYSTEM_PROMPT_EN if is_en else CHAT_SYSTEM_PROMPT_DE
    return template.format(tax_info=tax_info, user_profile=profile_text)


def _compact_portfolio_summary() -> str:
    """Kompakter Portfolio-Snapshot für den System-Prompt (Top-Zahlen, nicht alle Positionen)."""
    try:
        from src.web.services.portfolio_service import compute_portfolio_overview
        from src.web.services.cache_service import get_market_data
        portfolio = _load_portfolio()
        market_data = get_market_data()
        overview = compute_portfolio_overview(portfolio, market_data)
    except Exception:
        return "(Portfolio-Snapshot nicht verfügbar)"

    total = overview.get("total_value_eur", 0) or 0
    holdings = overview.get("holdings_value_eur", 0) or 0
    cash = overview.get("cash_total", 0) or 0
    pnl = overview.get("total_pnl_eur", 0) or 0
    pnl_pct = overview.get("total_pnl_pct", 0) or 0

    positions = overview.get("positions", []) or []
    top = sorted(positions, key=lambda p: p.get("value_eur", 0) or 0, reverse=True)[:5]
    top_lines = []
    for p in top:
        name = p.get("name") or p.get("ticker", "?")
        val = p.get("value_eur", 0) or 0
        pp = p.get("pnl_pct")
        pp_str = f" ({pp:+.1f}%)" if isinstance(pp, (int, float)) else ""
        top_lines.append(f"     • {name}: {val:,.0f}€{pp_str}")

    return (
        f"   - Gesamtvermögen: {total:,.0f}€ (Wertpapiere: {holdings:,.0f}€, Cash: {cash:,.0f}€)\n"
        f"   - Gesamt-P/L: {pnl:+,.0f}€ ({pnl_pct:+.1f}%)\n"
        f"   - Top-Positionen:\n" + "\n".join(top_lines)
    ).replace(",", ".")


def _sticky_memory_block() -> str:
    """Globales Sticky-Memory: Portfolio-Snapshot, Market-Regime, globale Pins."""
    parts = ["=== AKTUELLER PORTFOLIO-SNAPSHOT ===", _compact_portfolio_summary()]

    notes = _load_notes()
    regime = notes.get("market_regime")
    if regime:
        parts.append("\n=== MARKT-REGIME (aus letztem Briefing) ===")
        if isinstance(regime, dict):
            parts.append(f"   - {regime.get('value', '')}")
            if regime.get("updated"):
                parts.append(f"   - Stand: {regime['updated'][:10]}")
        else:
            parts.append(f"   - {regime}")

    insights = notes.get("key_insights") or []
    if insights:
        parts.append("\n=== KEY INSIGHTS (aus vergangenen Briefings) ===")
        for ins in insights[-5:]:
            if isinstance(ins, dict):
                parts.append(f"   - {ins.get('value', '')}")
            else:
                parts.append(f"   - {ins}")

    global_pins = db.get_pinned_memories(thread_id=None, include_global=False)
    if global_pins:
        parts.append("\n=== WICHTIG (vom User oder dir gepinnt) ===")
        for p in global_pins:
            parts.append(f"   - {p['key']}: {p['value']}")

    return "\n".join(parts)


def _thread_memory_block(thread_id: str) -> str:
    """Per-Thread-Memory: Thread-Pins + ggf. Summary früherer Messages."""
    parts = []
    thread = db.get_thread(thread_id)
    if thread and thread.get("summary"):
        parts.append("\n=== FRÜHER IN DIESEM GESPRÄCH (komprimiert) ===")
        parts.append(thread["summary"])

    thread_pins = db.get_pinned_memories(thread_id=thread_id, include_global=False)
    thread_pins = [p for p in thread_pins if p["thread_id"] == thread_id]
    if thread_pins:
        parts.append("\n=== THREAD-SPEZIFISCHE PINS ===")
        for p in thread_pins:
            parts.append(f"   - {p['key']}: {p['value']}")

    return "\n".join(parts)


_MANDATE_EDITOR_HINT = (
    "\n=== STRATEGIE-EDITOR ===\n"
    "Du kannst die Anlage-Strategie des Users (\"Mein Mandat\") gemeinsam mit ihm definieren oder ändern. "
    "Wenn er über seine Strategie/Regeln/Ziele reden oder etwas ändern will: interviewe ihn kurz "
    "(Ziel, Horizont, Risikotragfähigkeit, Tabus, max % je Einzelposition, Cash-Minimum, Soll-Allokation), "
    "formuliere den Vorschlag in PROSA (kein JSON für den User). Wenn er zustimmt, rufe "
    "propose_mandate(mandate_json, change_summary) mit dem KOMPLETTEN neuen Mandat-JSON auf — der User "
    "bestätigt in der UI, erst dann wird gespeichert. Schreibe das Mandat NIE direkt. "
    "Mit get_strategy_drift siehst du die aktuelle Soll-vs-Ist-Abweichung."
)


def build_full_system_prompt(thread_id: str, page_context: dict | None = None) -> str:
    """Vollständiger System-Prompt inkl. Sticky-Memory, Thread-Memory, Page-Context."""
    base = build_system_prompt()
    sticky = _sticky_memory_block()
    thread_mem = _thread_memory_block(thread_id)

    # §0-Mandat ganz oben (oberste Direktive, bei jedem Turn). Opt-in: leer wenn kein Mandat → keine Änderung.
    mandate_block = build_mandate_block(load_mandate())

    parts = [base, "", sticky]
    if mandate_block:
        parts = [mandate_block, "", base, "", sticky]
    parts.append(_MANDATE_EDITOR_HINT)
    if thread_mem:
        parts.append(thread_mem)

    if page_context:
        parts.append("\n=== AKTUELLER UI-KONTEXT ===")
        page = page_context.get("page")
        if page:
            parts.append(f"   - Nutzer ist gerade auf Seite: /{page}")
        focus = page_context.get("focused_ticker")
        if focus:
            parts.append(f"   - Fokus-Ticker: {focus}")

    parts.append(f"\n=== METADATEN ===\n   - Aktuelle Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(parts)


def build_user_message_with_history(thread_id: str, new_message: str, history_limit: int = 20) -> str:
    """Baut den User-Prompt mit Chat-History (für Calls ohne Session-Resume).

    Wird genutzt, wenn wir KEIN --resume machen (also beim allerersten Call eines Threads
    ODER wenn Session verloren gegangen ist). Bei --resume reicht die neue Message alleine,
    da Claude Code selbst die History kennt.
    """
    history = db.get_recent_user_assistant_messages(thread_id, limit=history_limit)
    # Den aktuellen user-turn filtern, falls bereits persistiert
    if history and history[-1].get("role") == "user" and history[-1].get("content") == new_message:
        history = history[:-1]

    if not history:
        return new_message

    lines = ["=== BISHERIGER CHAT-VERLAUF ==="]
    for msg in history:
        role = "NUTZER" if msg["role"] == "user" else "DU"
        lines.append(f"\n[{role}]: {msg['content']}")
    lines.append("\n=== AKTUELLE NACHRICHT ===")
    lines.append(new_message)
    return "\n".join(lines)


SUMMARY_THRESHOLD = 40  # ab so vielen Messages im Thread wird komprimiert
SUMMARY_KEEP_RECENT = 20  # die letzten N Messages bleiben roh


def maybe_auto_summarize(thread_id: str) -> bool:
    """Komprimiert alte Messages eines Threads zu einem Summary, wenn er zu lang ist.

    Wird beim Message-Send aufgerufen. Nutzt einen One-Shot Claude-Call (kein Streaming,
    niedriger Effort), um die ältesten (count - SUMMARY_KEEP_RECENT) Messages zusammenzufassen.
    Der Summary wird ins threads.summary-Feld geschrieben und vom Sticky-Memory-Block genutzt.

    Returns True wenn komprimiert wurde.
    """
    thread = db.get_thread(thread_id)
    if not thread:
        return False
    msgs = db.get_recent_user_assistant_messages(thread_id, limit=500)
    if len(msgs) < SUMMARY_THRESHOLD:
        return False

    to_summarize = msgs[:-SUMMARY_KEEP_RECENT]
    if not to_summarize:
        return False

    # Existing summary als Startpunkt
    prior = thread.get("summary") or ""
    convo_text = "\n".join(
        f"[{'NUTZER' if m['role'] == 'user' else 'VELORA'}]: {m['content'][:600]}"
        for m in to_summarize
    )

    prompt = f"""Hier ist ein Chat-Verlauf zwischen einem Vermögensberater (Velora) und seinem Kunden.

{'VORHERIGE ZUSAMMENFASSUNG: ' + prior if prior else ''}

NEUER VERLAUF:
{convo_text}

Fasse den kompletten Verlauf in 8-15 Bullet-Points zusammen. Fokus auf:
- Welche Themen besprochen wurden
- Welche konkreten Entscheidungen getroffen
- Welche Empfehlungen Velora gab
- Welche offenen Fragen bleiben

Deutsch, prägnant, max 800 Zeichen."""

    try:
        from src.analysis.claude import ask_claude
        result = ask_claude(
            system_prompt="Du komprimierst Gespräche zu knappen Zusammenfassungen.",
            user_prompt=prompt,
            timeout=120,
        )
        summary = (result.get("text") or "").strip()[:2000]
        if summary:
            db.update_thread(thread_id, summary=summary)
            return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Auto-Summary fehlgeschlagen: %s", e)
    return False
