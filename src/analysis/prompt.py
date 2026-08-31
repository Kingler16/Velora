"""
System-Prompt und Daten-Formatting für den Vermögensberater.
"""

import json
from datetime import datetime

from src.analysis.mandate import build_mandate_block, load_mandate
from src.data.fx import safe_eur_usd


SYSTEM_PROMPT_TEMPLATE = """Du bist ein erfahrener, unabhängiger Vermögensberater (CFA Level III, 15 Jahre Erfahrung Multi-Asset).

WICHTIGE REGELN:

1. DATEN-INTEGRITÄT:
   - Du erfindest NIEMALS Zahlen, Kurse, KGVs oder Kennzahlen
   - Alle Zahlen die du nennst MÜSSEN aus den bereitgestellten Daten stammen
   - Wenn du keine Daten hast, sag: "Dazu liegen mir keine aktuellen Daten vor"
   - Kennzeichne immer: [Fakt] = aus Daten, [Berechnung] = abgeleitet, [Einschätzung] = deine Meinung

2. KEIN AKTIONISMUS:
   - "Nichts tun" ist eine VALIDE und oft die BESTE Empfehlung
   - Empfehle NUR Aktionen wenn es einen klaren, begründeten Anlass gibt
   - Nicht jedes Briefing braucht Kauf-/Verkaufsempfehlungen
   - Lieber einmal zu wenig handeln als einmal zu viel

3. ANALYSE-TIEFE:
   - Denke wie ein Hedgefonds-Analyst, nicht wie ein Retail-Blog
   - Narrativ-Analyse: Was preist der Markt ein? Wo liegt der Konsens daneben?
   - Szenario-Analyse: Bull/Base/Bear mit konkreten Triggern und Wahrscheinlichkeiten
   - Cross-Asset: Wie hängen Positionen zusammen? Korrelationen? Spillover-Risiken?
   - Insider-Signale: Was machen CEOs mit ihren eigenen Aktien?
   - Positionierung: Short Interest, institutionelle Flows
   - MAKRO IMMER EINBEZIEHEN: Du bekommst Makro-Daten (Fed Funds Rate, Yield Curve, CPI, EZB-Zins, HICP, Credit Spreads, VIX). Nutze sie AKTIV um die Marktlage einzuordnen.
   - FONDS ANALYSIEREN: Wenn der Nutzer Fonds-Positionen hat, analysiere deren Rolle im Portfolio auch wenn die Datenqualität eingeschränkt ist.

4. NICHT WIEDERHOLEN:
   - Du bekommst eine Memory-Sektion mit vergangenen Briefings
   - Wiederhole NICHT was du schon gesagt hast, es sei denn es hat sich etwas geändert
   - Fokussiere auf NEUE Entwicklungen und VERÄNDERTE Situationen

5. NEUE IDEEN:
   - Du bekommst zwei Quellen für Titel ausserhalb des Depots: die WATCHLIST des Nutzers
     und SCREENER-KANDIDATEN (regelbasiert gefiltert nach Sektoren, die im Depot fehlen)
   - Beide liefern echte Kursdaten (Kurs, ATR, RSI, SMA200, 52W-Range, KGV, Marktkap.).
     Das sind Rohdaten für deine eigene Analyse — keine fremden Kaufempfehlungen.
     Du kannst damit Einstieg, Stop (aus ATR) und Ziel genauso rechnen wie bei einer
     Depot-Position. "Dazu habe ich keine Daten" gilt für diese Titel also NICHT.
   - Prüfe: Passt es ins Portfolio? (Diversifikation, Sektor, Risiko, Mandat)
   - Nur vorschlagen wenn wirklich überzeugend, nicht auf Krampf. Überzeugt einer,
     dann als vollwertige Empfehlung mit Stückzahl — nicht als vages "beobachten".
   - Fremde Analysten-/Morningstar-Ranglisten bleiben tabu: nicht nachplappern.

6. NEWS-QUALITÄT:
   - Jede News hat ein Alter-Label. Ignoriere News älter als 7 Tage für taktische Einschätzungen
   - Unterscheide: Breaking (heute/gestern), Aktuell (diese Woche), Hintergrund (älter)

7. SPRACHE & FORMAT:
   - {language_instruction}
   - Wie ein Gespräch mit einem smarten Berater, nicht wie ein generierter Report
   - Sprich den Nutzer mit "du" an
   - Telegram-kompatibles HTML-Format

8. STEUER-KONTEXT:
   - {tax_info}
   - Berücksichtige steuerliche Optimierung (Verlustverrechnung, Haltedauer)

9. RISIKO-PROFIL DES NUTZERS:
   - {user_profile}
   - WICHTIG: Auch bei hoher Risikotoleranz — sei KONSERVATIV mit Empfehlungen. Kapitalerhalt geht vor Rendite. Empfehle NIE mehr als 5-10% des Portfolios in einer einzelnen Aktion zu bewegen. Bei Unsicherheit: lieber abwarten.
"""


def build_system_prompt(settings: dict, portfolio: dict) -> str:
    """Baut den System-Prompt dynamisch aus Settings und Portfolio."""
    user_settings = settings.get("user", {})
    user_profile = portfolio.get("user_profile", {})

    lang = user_settings.get("language", "de")
    language_instruction = "Deutsch, direkt, kein Geschwafel" if lang == "de" else "English, direct, no fluff"

    tax_regime = user_settings.get("tax_regime", user_profile.get("tax_regime", "Configure in settings"))
    tax_info = f"{tax_regime}"

    risk = user_profile.get("risk_tolerance", "medium")
    goal = user_profile.get("goal", "growth")
    profile_parts = [f"Risikotoleranz: {risk}, Ziel: {goal}"]
    if user_profile.get("age"):
        profile_parts.insert(0, f"{user_profile['age']} Jahre alt")
    if user_profile.get("country"):
        profile_parts.append(f"Land: {user_profile['country']}")

    return SYSTEM_PROMPT_TEMPLATE.format(
        language_instruction=language_instruction,
        tax_info=tax_info,
        user_profile=", ".join(profile_parts),
    )


BRIEFING_TEMPLATE = """
=== PORTFOLIO & MARKTDATEN (Stichtag: {date}) ===

{portfolio_summary}

=== AKTUELLE KURSE & FUNDAMENTALS (Kursperf. = allgemeine Aktienperformance, NICHT dein P/L!) ===

{market_data}

=== INDIZES & MARKTUMFELD ===

{index_data}

=== MAKRO-DATEN ===

{macro_data}

=== FEAR & GREED ===

{fear_greed}

=== NEWS ZU DEINEN POSITIONEN ===

{position_news}

=== MAKRO-NEWS ===

{macro_news}

=== WATCHLIST (beobachtet, noch NICHT im Depot — mit echten Kursdaten) ===

{watchlist}

=== SCREENER-KANDIDATEN (Sektoren, die im Depot fehlen — echte Kursdaten, keine Analystenliste) ===

{candidates}

=== MEMORY (vergangene Briefings & offene Empfehlungen) ===

{memory_context}

=== DEINE AUFGABE ===

Erstelle das Briefing. Struktur:

1. MARKTLAGE (2-3 Sätze, was hat sich VERÄNDERT seit dem letzten Briefing? Nutze die Makro-Daten: Yield Curve, Credit Spreads, Inflation, Zinsen. Nutze Benchmark-Vergleich. Verankere deine Einschätzung am berechneten MARKT-REGIME — wenn deine Lesart davon abweicht, begründe warum.)
2. PORTFOLIO-CHECK (nur Positionen erwähnen wo sich etwas RELEVANTES getan hat. Fonds-Positionen einordnen falls vorhanden. EUR/USD Auswirkung auf USD-Positionen berechnen. KRITISCH: Verwende für die Performance jeder Position IMMER die "P/L: ...€ (...%)" Werte aus dem PORTFOLIO-Abschnitt oben — diese basieren auf dem persönlichen Buy-In. Die "Kursperf. 1M/6M/1Y" Werte aus den MARKTDATEN zeigen die allgemeine Aktienperformance und sind NICHT identisch mit der Position-Performance!)

2b. STOP-CHECK (nur wenn die Sektion STOP-LOSS-LAGE vorhanden ist): Nenne JEDE Position ohne Stop beim Namen und gib einen konkreten Stop-Kurs in der Quote-Währung an. Hintergrund: Der Nutzer kann bei Trade Republic und Erste Bank KEINEN Stop zur Limit-Kauforder hinterlegen — er muss ihn nach der Ausführung von Hand nachtragen, und genau das geht unter. Ein Satz pro Position reicht: Titel, Stop-Kurs, was das im Verlustfall kostet. Nutze den Soll-Stop als Ausgangspunkt und weiche begründet ab, wenn Earnings anstehen oder die Charttechnik einen anderen Halt nahelegt. Auffällige Ist-Stops (zu eng, zu weit, ungültig, nachziehbar) ebenfalls ansprechen. Wenn alles sauber gesichert ist: ein Satz, fertig. Diese Hinweise gehören in den Fliesstext — in die JSON-Empfehlungsliste kommt ein Stop nur als "hold" mit stop_loss, und nur für Positionen, bei denen sich der Stop wirklich ändern soll.
3. EARNINGS & EVENTS (welche Positionen reporten bald? Was ist zu erwarten? Kommende Katalysatoren.)
4. EMPFEHLUNGEN — STRENG: max. 3 Einträge pro Briefing, nur High-Conviction. Wenn nichts überzeugt: 0 Empfehlungen ist die richtige Antwort. "Halten" / "Beobachten ohne Order" gehört in den Fließtext, NICHT in die JSON-Liste. Jede Empfehlung MUSS konkret sein: Einstieg, Stop-Loss, Ziel, Risk/Reward UND Stückzahl. Bei Kauf: Anzahl Stück. Bei Verkauf: Prozent der Position ODER Anzahl Stück. Bei buy/watch IMMER eine konkrete Stückzahl (`shares`) ODER einen €-Betrag angeben — orientiert an der freien Cash-Quote (z.B. 2-5% des Depotwerts pro Position). Ohne Stückzahl ist die Empfehlung nicht direkt ausführbar. Berücksichtige Tax-Loss-Harvesting wenn sinnvoll. WICHTIG: Leite Stop-Distanzen aus dem ATR ab (z.B. Stop ≈ Kurs − 1,5–2×ATR) statt sie zu raten — zu enge Stops sind der häufigste Verlustgrund. Berücksichtige Klumpenrisiko/Korrelation (effektive Positionen) und nutze die Analysten-Kursziele als Konsens-Anker für deine Ziele. Jede Empfehlung MUSS das Mandat (§0) einhalten — Block-Verstöße werden beim Speichern automatisch verworfen, Warn-Verstöße markiert; schlage Block-Verstöße gar nicht erst vor. KALIBRIERUNG: Schau VOR dem Empfehlen auf deine Hit-Rate + Expectancy in der EMPFEHLUNGS-BILANZ. Bei Hit-Rate < 50% nenne explizit, was deine letzten Fehlschläge gemeinsam hatten und warum diese Empfehlung anders ist; übergewichte nicht systematisch dieselbe These/denselben Sektor, in der du zuletzt falsch lagst.
5. NEUE IDEEN — Kandidaten kommen aus WATCHLIST und SCREENER-KANDIDATEN oben. Beide Listen liefern dir echte Kursdaten (Kurs, ATR, RSI, SMA200, 52W-Range), du kannst also Einstieg, Stop und Ziel genauso sauber rechnen wie bei einer Depot-Position — nichts davon musst du schätzen. Der Screener zeigt bewusst Sektoren, die im Depot fehlen: das ist Diversifikation, kein Aktionismus. Prüfe pro Kandidat: Bewertung, Technik, Portfolio-Fit, Mandats-Konformität. Wenn einer überzeugt, gehört er als vollwertige buy/watch-Empfehlung in die JSON-Liste unter Punkt 4 (mit Stückzahl) — nicht nur als Fließtext-Erwähnung. Wenn keiner überzeugt: sag knapp warum, das ist eine valide Antwort. Es ist KEINE Liste fremder Analystenempfehlungen, die du abnicken sollst — es sind Rohdaten für deine eigene Analyse.
6. RISIKEN AUF DEM RADAR (was könnte schiefgehen?)
7. EMPFEHLUNGS-BILANZ (wenn es offene Empfehlungen gibt: wie haben sie sich entwickelt? Für frisch ABGESCHLOSSENE Empfehlungen: kurzes POST-MORTEM — war die ursprüngliche These richtig oder falsch, und WARUM? Was lernst du daraus für künftige Empfehlungen?)

Am Ende: Gib eine JSON-Zusammenfassung aus, eingepackt in ```json ... ```, mit:
- "summary": kurze Zusammenfassung des Briefings (1-2 Sätze)
- "market_regime": aktuelle Marktlage in einem Satz
- "recommendations": MAXIMAL 3 Einträge. Lieber leere Liste als halbgare Vorschläge. Jeder Eintrag MUSS dieser Pflicht-Checkliste folgen — sonst wird er beim Speichern verworfen:
  Format: {{"ticker": "...", "action": "buy/sell/watch/hold", "entry_price": ..., "target_price": ..., "stop_loss": ..., "shares": ..., "sell_pct": ..., "reasoning": "..."}}
  WICHTIG zu Preisen: entry_price/stop_loss/target_price IMMER in der Quote-Währung des Tickers angeben — also USD für US-Ticker (AAPL, META, TSLA, NVDA...) und EUR für europäische Ticker (ASML.AS, ALV.DE, MC.PA...). KEINE Umrechnung. Die UI rendert das Symbol ($/€) automatisch anhand des Tickers.
  ERLAUBTE AKTIONEN (alle anderen werden verworfen):
    * "buy"   → Aktien kaufen. MUSS shares ODER sell_pct UND reasoning ≥ 20 Zeichen haben. entry_price optional (mit = Limit-Order, ohne = Markt).
    * "sell"  → Aktien verkaufen. MUSS shares ODER sell_pct (z.B. 50 für 50%) haben.
    * "watch" → Limit-Kauf-Order vorbereiten. NUR mit konkretem entry_price! "Mal beobachten" ohne Level wird gedroppt — gehört in den Fließtext.
    * "hold"  → NUR mit konkretem stop_loss-Wert! Das ist die "Stop nachziehen / setzen"-Aktion (User muss zum Broker und Stop-Order anpassen). "Einfach behalten ohne Stop-Änderung" gehört in den Fließtext (PORTFOLIO-CHECK), NICHT in diese Liste.
  Wiederhole KEINE Empfehlung, die schon offen aus einem vorherigen Briefing existiert (siehe Memory-Sektion) — es sei denn, sich hat etwas Wesentliches geändert (z.B. Stop-Anpassung von altem auf neuen Level).
- "new_insights": Liste von neuen Key Insights die gemerkt werden sollen
- "position_theses_updates": {{"TICKER": "aktualisierte These"}} nur wenn sich etwas geändert hat

Formatiere das Briefing in Telegram-kompatiblem HTML (<b>, <i>, <code>, <pre>).
"""


MONTHLY_REPORT_TEMPLATE = """
=== MONATSREPORT-DATEN ===

{monthly_data}

=== MEMORY (vergangene Monatssnapshots) ===

{monthly_snapshots}

=== DEINE AUFGABE ===

Erstelle den Monatsreport. Struktur:

1. MONATSÜBERBLICK: Wie ist der Monat gelaufen? Performance in € und %
2. TOP & FLOP: Beste und schlechteste Positionen
3. EMPFEHLUNGS-BILANZ: Welche Empfehlungen wurden gegeben? Wie haben sie performt?
4. PORTFOLIO-ENTWICKLUNG: Vergleich zum Vormonat (Gesamtwert, Allokation, Cash-Quote)
5. AUSBLICK: Was steht nächsten Monat an? (Earnings, Makro-Events, etc.)
6. LESSONS LEARNED: Was lief gut, was schlecht, was lernen wir daraus?

Formatiere in Telegram-kompatiblem HTML.

Am Ende: JSON-Block mit:
- "total_value": Gesamtwert des Portfolios
- "monthly_return_pct": Monatsrendite in %
- "monthly_return_eur": Monatsrendite in €
- "top_performer": {{"ticker": "...", "return_pct": ...}}
- "worst_performer": {{"ticker": "...", "return_pct": ...}}
"""


TICKER_ANALYSIS_TEMPLATE = """
=== ON-DEMAND ANALYSE: {ticker} ===

{ticker_data}

=== AKTUELLES PORTFOLIO ===

{portfolio_summary}

=== NEWS ZU {ticker} ===

{news}

=== DEINE AUFGABE ===

Der Nutzer will wissen ob {ticker} eine gute Investment-Idee ist.

Analysiere:
1. UNTERNEHMEN: Was macht die Firma? Geschäftsmodell, Moat, Wettbewerbsposition
2. BEWERTUNG: Fair Value Einschätzung basierend auf den Daten. Über-/unterbewertet?
3. MOMENTUM: Trend, technische Lage
4. PORTFOLIO-FIT: Passt es ins bestehende Portfolio? Korrelation, Sektor-Overlap, Diversifikation?
5. BULL/BEAR CASE: Was spricht dafür, was dagegen?
6. VERDICT: Klare Empfehlung mit Begründung

Formatiere in Telegram-kompatiblem HTML.
"""


def build_portfolio_summary(portfolio: dict, market_data: dict) -> str:
    """Baut eine Portfolio-Zusammenfassung mit aktuellen Werten. EUR/USD korrekt konvertiert."""
    lines = []
    total_value_eur = 0
    total_invested_eur = 0

    # EUR/USD Kurs (validiert, mit 1.0-Fallback — reiner Anzeige-/Prompt-Pfad)
    eur_usd = safe_eur_usd(market_data)
    lines.append(f"[EUR/USD: {eur_usd}]")

    for account_name, account in portfolio["accounts"].items():
        lines.append(f"\n--- {account_name.upper()} ---")
        for pos in account["positions"]:
            ticker = pos.get("ticker")
            shares = pos["shares"]
            buy_in = pos["buy_in"]
            currency = pos.get("currency", "EUR")

            # Buy-In in EUR: buy_in_eur aus Portfolio nutzen (historischer Kurs),
            # NICHT den aktuellen EUR/USD-Kurs auf den USD-Buy-In anwenden!
            if pos.get("buy_in_eur"):
                buy_in_eur = pos["buy_in_eur"]
            elif currency == "EUR":
                buy_in_eur = buy_in
            else:
                # Fallback: aktueller Kurs (ungenau bei FX-Schwankungen!)
                buy_in_eur = buy_in / eur_usd
            invested_eur = shares * buy_in_eur

            current_price = None
            price_data = {}
            if ticker and ticker in market_data.get("positions", {}):
                price_data = market_data["positions"][ticker].get("price", {})
                current_price = price_data.get("current_price")

            if current_price:
                # Aktuellen Wert in EUR umrechnen — Quote-Währung aus Marktdaten,
                # nicht aus pos.currency (das ist nur die Buy-in-Währung).
                from src.data.fx import resolve_quote_currency
                quote_ccy = resolve_quote_currency(price_data, currency)
                current_price_eur = current_price if quote_ccy == "EUR" else current_price / eur_usd
                current_value_eur = shares * current_price_eur
                pnl_eur = current_value_eur - invested_eur
                pnl_pct = (pnl_eur / invested_eur) * 100 if invested_eur else 0
                total_value_eur += current_value_eur
                total_invested_eur += invested_eur

                currency_note = f" [{quote_ccy}→EUR, Kurs in {quote_ccy}: {current_price:.2f}]" if quote_ccy != "EUR" else ""
                lines.append(
                    f"{pos['name']} ({ticker}): {shares:.2f} Stk @ {current_price_eur:.2f}€{currency_note} "
                    f"= {current_value_eur:.2f}€ | P/L: {pnl_eur:+.2f}€ ({pnl_pct:+.1f}%) | Buy-In: {buy_in_eur:.2f}€"
                )
            else:
                # Für Fonds ohne Ticker: letzte bekannte Werte aus portfolio.json nutzen
                estimated_value = shares * buy_in_eur  # Mindestens Einstandswert anzeigen
                lines.append(
                    f"{pos['name']} ({ticker or 'kein Ticker'}): {shares:.2f} Stk | "
                    f"Buy-In: {buy_in_eur:.2f}€/Stk | Einstand gesamt: {estimated_value:.2f}€ | KEIN LIVE-KURS"
                )
                total_invested_eur += estimated_value
                total_value_eur += estimated_value  # Konservativ: Einstandswert als Schätzung

    # Bankkonten (einzige Cash-Quelle, keine Doppelzählung)
    lines.append("\n--- BANKKONTEN ---")
    cash_total = 0
    depot_cash = 0
    free_cash = 0
    for name, acc in portfolio.get("bank_accounts", {}).items():
        val = acc["value"]
        cash_total += val
        is_depot = acc.get("is_depot_cash", False)
        if is_depot:
            depot_cash += val
        else:
            free_cash += val
        label = " [Depot-Cash]" if is_depot else " [frei verfügbar]"
        lines.append(f"{name}: {val:.2f}€ ({acc['interest']}% Zinsen){label}")

    total_value_eur += cash_total
    portfolio_value = total_value_eur - cash_total
    cash_pct = (cash_total / total_value_eur * 100) if total_value_eur else 0

    # USD-Exposure berechnen
    usd_positions = sum(1 for acc in portfolio["accounts"].values() for p in acc["positions"] if p.get("currency") == "USD")

    lines.append(f"\n--- GESAMT (alle Werte in EUR, korrekt konvertiert) ---")
    lines.append(f"Portfolio-Wert (Aktien+Fonds): {portfolio_value:.2f}€")
    lines.append(f"Depot-Cash (TR + EB Abrechnungskonto): {depot_cash:.2f}€")
    lines.append(f"Freies Cash (Girokonto + Sparkonto): {free_cash:.2f}€")
    lines.append(f"Cash gesamt: {cash_total:.2f}€ ({cash_pct:.1f}%)")
    lines.append(f"GESAMTVERMÖGEN: {total_value_eur:.2f}€")
    lines.append(f"USD-Exposure: {usd_positions} Positionen in USD")

    return "\n".join(lines)


def format_market_data(market_data: dict) -> str:
    """Formatiert Marktdaten für den Prompt."""
    lines = []
    for ticker, data in market_data.get("positions", {}).items():
        p = data.get("price", {})
        stale = " ⚠KURS VERALTET" if p.get("stale_quote") else ""
        block = (
            f"{data['name']} ({ticker}):\n"
            f"  Kurs: {p.get('current_price')}{stale} | Tagesänderung: {p.get('change_pct', '?')}%\n"
            f"  52W-Hoch: {p.get('52w_high')} | 52W-Tief: {p.get('52w_low')}\n"
            f"  Kursperf. 1M: {p.get('perf_1m_pct') or 'k.A.'}{'%' if p.get('perf_1m_pct') is not None else ''} | Kursperf. 6M: {p.get('perf_6m_pct') or 'k.A.'}{'%' if p.get('perf_6m_pct') is not None else ''} | Kursperf. 1Y: {p.get('perf_1y_pct') or 'k.A.'}{'%' if p.get('perf_1y_pct') is not None else ''}\n"
            f"  KGV: {p.get('pe_ratio', '?')} | Forward KGV: {p.get('forward_pe', '?')} | PEG: {p.get('peg_ratio', '?')}\n"
            f"  Dividendenrendite: {p.get('dividend_yield', '?')} | Beta: {p.get('beta', '?')}\n"
            f"  Short Interest: {p.get('short_interest', '?')} | Insider-Anteil: {p.get('insider_buy_pct', '?')}\n"
            f"  Sektor: {p.get('sector', '?')} | Branche: {p.get('industry', '?')}\n"
            f"  [Quelle: {p.get('source')}, {p.get('timestamp', '')[:16]}]"
        )
        # Technik / Analysten-Konsens / Insider-Aggregat (Phase 2)
        sig = _position_signal_lines(p, data)
        if sig:
            block += "\n" + sig
        lines.append(block)

    return "\n\n".join(lines)


def _position_signal_lines(p: dict, data: dict) -> str:
    """Rendert die Phase-2-Signale (Technik, Analysten-Konsens, Insider-Aggregat)
    kompakt — nur Felder, die tatsächlich vorhanden sind."""
    out = []

    tech = []
    if p.get("rsi_14") is not None:
        tech.append(f"RSI14 {p['rsi_14']}")
    if p.get("sma_50") is not None and p.get("sma_200") is not None:
        trend = "über" if p.get("above_sma200") else "unter"
        cross = {"golden": " +GOLDEN-CROSS", "death": " +DEATH-CROSS"}.get(p.get("cross_signal"), "")
        tech.append(f"SMA50/200 {p['sma_50']}/{p['sma_200']} (Kurs {trend} SMA200{cross})")
    if p.get("dist_to_sma200_pct") is not None:
        tech.append(f"Δ-SMA200 {p['dist_to_sma200_pct']:+.1f}%")
    if p.get("atr_14") is not None:
        atr_pct = f" ({p['atr_pct']}%)" if p.get("atr_pct") is not None else ""
        tech.append(f"ATR14 {p['atr_14']}{atr_pct}")
    if p.get("realized_vol_30d") is not None:
        tech.append(f"Vol30d {p['realized_vol_30d']}%")
    if p.get("avg_volume_ratio") is not None:
        tech.append(f"Vol-Ratio {p['avg_volume_ratio']}")
    if tech:
        out.append("  Technik: " + " | ".join(tech))

    an = []
    if p.get("target_mean"):
        cur = p.get("current_price")
        up = f" ({(p['target_mean'] / cur - 1) * 100:+.0f}% Upside)" if cur else ""
        lo, hi = p.get("target_low"), p.get("target_high")
        rng = f" [{lo:.2f}–{hi:.2f}]" if lo and hi else ""
        an.append(f"Kursziel Ø {p['target_mean']:.2f}{up}{rng}")
    if p.get("analyst_rating") is not None:
        cnt = f" ({p['analyst_count']} Analysten)" if p.get("analyst_count") else ""
        an.append(f"Rating {p['analyst_rating']}/5{cnt}")
    if p.get("short_ratio") is not None:
        an.append(f"Short-Ratio {p['short_ratio']}")
    if an:
        out.append("  Analysten: " + " | ".join(an))

    isum = data.get("insider_summary") or {}
    nv = isum.get("net_value_90d")
    buyers = isum.get("distinct_buyers_90d") or 0
    sellers = isum.get("distinct_sellers_90d") or 0
    if nv or buyers or sellers:
        cluster = " | ⚑CLUSTER-KAUF" if isum.get("cluster_buy") else ""
        nv_str = f"Netto {nv:+,.0f} | " if nv else ""
        out.append(f"  Insider (90T): {nv_str}{buyers} Käufer / {sellers} Verkäufer{cluster}")

    return "\n".join(out)


def _quote_block(ticker: str, name: str, p: dict, head_extra: str = "") -> str:
    """Kompakter Kursblock für Titel ausserhalb des Depots (Watchlist/Screener).
    Bewusst mit ATR/RSI/SMA — ohne die kann Velora keinen Stop und kein Ziel rechnen."""
    lines = [f"{name} ({ticker}):{head_extra}"]
    cur = p.get("current_price")
    ccy = p.get("currency") or ""
    lines.append(
        f"  Kurs: {cur} {ccy} | Tagesänderung: {p.get('change_pct', '?')}% | "
        f"52W: {p.get('52w_low')}–{p.get('52w_high')}"
    )
    perf = " | ".join(
        f"{lbl} {p.get(k)}%" for lbl, k in
        (("1M", "perf_1m_pct"), ("6M", "perf_6m_pct"), ("1Y", "perf_1y_pct"))
        if p.get(k) is not None
    )
    if perf:
        lines.append(f"  Kursperf.: {perf}")
    lines.append(
        f"  KGV: {p.get('pe_ratio', '?')} | Forward KGV: {p.get('forward_pe', '?')} | "
        f"Div.-Rendite: {p.get('dividend_yield', '?')} | Beta: {p.get('beta', '?')}"
    )
    sig = _position_signal_lines(p, {})
    if sig:
        lines.append(sig)
    return "\n".join(lines)


def format_watchlist(market_data: dict) -> str:
    """Rendert die Watchlist des Nutzers mit Kursdaten.

    Diese Daten wurden schon immer geholt (collect_all_market_data), landeten aber
    nie im Prompt — Velora hat seine eigene Watchlist im Briefing nie gesehen.
    """
    wl = market_data.get("watchlist") or {}
    if not wl:
        return "Watchlist ist leer."
    blocks = []
    for ticker, data in wl.items():
        p = data.get("price") or {}
        if not p.get("current_price"):
            blocks.append(f"{data.get('name', ticker)} ({ticker}): KEIN LIVE-KURS")
            continue
        blocks.append(_quote_block(ticker, data.get("name", ticker), p))
    return "\n\n".join(blocks)


def format_candidates(candidates: list[dict] | None) -> str:
    """Rendert die Screener-Kandidaten (src/data/screener.py) für den Prompt."""
    if not candidates:
        return "Keine Kandidaten (Screener lieferte nichts oder alle Sektoren sind belegt)."
    blocks = []
    for c in candidates:
        cap = c.get("market_cap")
        cap_str = f" [{cap / 1_000_000_000:.0f} Mrd. Marktkap.]" if cap else ""
        head = f" — Sektor {c.get('sector', '?')}{cap_str}"
        blocks.append(_quote_block(c["ticker"], c.get("name", c["ticker"]), c.get("price") or {}, head))
    return "\n\n".join(blocks)


def format_regime(regime: dict) -> str:
    """Rendert das berechnete Markt-Regime (classify_regime) für den Prompt."""
    if not regime or not regime.get("label"):
        return "Nicht verfügbar."
    drivers = regime.get("drivers") or []
    lines = [f"Regime: {regime['label']} (Score {regime.get('score', '?')})"]
    for d in drivers:
        lines.append(f"  - {d}")
    return "\n".join(lines)


def format_risk_metrics(risk: dict, market_data: dict) -> str:
    """Rendert Risiko-Kennzahlen pro Position (compute_risk_metrics) für den Prompt."""
    per_pos = (risk or {}).get("per_position") or {}
    if not per_pos:
        return "Nicht verfügbar."
    names = {tk: d.get("name", tk) for tk, d in market_data.get("positions", {}).items()}
    lines = [f"(Risikofreier Zins: {((risk.get('rf_used') or 0) * 100):.1f}%)"]
    for tk, m in sorted(per_pos.items(), key=lambda kv: kv[1].get("vol_annual", 0), reverse=True):
        lines.append(
            f"  {names.get(tk, tk)} ({tk}): Vol {m.get('vol_annual', '?')}% p.a. | "
            f"Max-DD {m.get('max_drawdown', '?')}% | Sharpe {m.get('sharpe', '?')}"
        )
    return "\n".join(lines)


def format_correlation(corr: dict) -> str:
    """Rendert Korrelation & Klumpenrisiko (compute_correlation_data) für den Prompt."""
    if not corr:
        return "Nicht verfügbar."
    lines = []
    eff = corr.get("effective_positions")
    avg = corr.get("avg_correlation")
    if eff is not None:
        lines.append(f"Effektive Positionen: {eff} (je niedriger vs. Positionsanzahl, desto mehr Klumpenrisiko)")
    if avg is not None:
        lines.append(f"Ø paarweise Korrelation: {avg}")
    pairs = corr.get("top_pairs") or []
    if pairs:
        lines.append("Stark korrelierte Paare (|r|>0.7):")
        for pr in pairs:
            lines.append(f"  - {pr.get('a')} ↔ {pr.get('b')}: {pr.get('corr')}")
    return "\n".join(lines) if lines else "Keine auffälligen Korrelationen."


def format_strategy_drift(drift: dict | None) -> str:
    """Rendert die Strategie-Drift (Soll vs. Ist) für den Briefing-Prompt.
    Gibt "" zurück wenn kein Mandat / keine Abweichungs-Dimensionen."""
    if not drift or not drift.get("dimensions"):
        return ""
    lines = [f"Status: {drift.get('status')} — {drift.get('breaches', 0)} Abweichung(en), {drift.get('warnings', 0)} Warnung(en)"]
    for d in drift["dimensions"]:
        soll = f"Soll {d['soll']}%" if d.get("soll") is not None else "Limit"
        lines.append(f"  {d['name']}: Ist {d['ist']}% vs {soll} ({d['abweichung_pp']:+.1f}pp) [{d['severity']}]")
    lines.append("→ Bevorzuge Aktionen, die das Depot näher an die Soll-Allokation bringen (ohne Steuer-/Aktionismus-Kosten zu ignorieren).")
    return "\n".join(lines)


_ASSET_LABELS = {"equity": "Aktien", "bond": "Anleihen", "commodity": "Rohstoffe", "mixed": "Gemischt", "cash": "Cash"}


def format_lookthrough(lt: dict | None) -> str:
    """Rendert die echte Look-Through-Exposure (Fonds in Einzeltitel zerlegt) für den Prompt.
    Gibt "" zurück wenn keine Daten."""
    if not lt or not lt.get("asset_class"):
        return ""
    lines = []
    ac = " · ".join(f"{_ASSET_LABELS.get(a['name'], a['name'])} {a['pct']}%" for a in lt["asset_class"])
    lines.append(f"Asset-Klassen (durchgerechnet inkl. Fonds): {ac}")
    tt = lt.get("top_titles") or []
    if tt:
        lines.append("Top-Einzeltitel (Direktbestand + in Fonds versteckt): "
                     + " · ".join(f"{t['name']} {t['pct']}%" for t in tt[:10]))
    regs = lt.get("regions") or []
    if regs:
        lines.append("Regionen (durchgerechnet): " + " · ".join(f"{r['name']} {r['pct']}%" for r in regs[:6]))
    if lt.get("unresearched_funds"):
        lines.append(f"HINWEIS: {lt['unresearched_funds']} Fonds noch nicht recherchiert — Durchschau unvollständig.")
    return "\n".join(lines)


def format_index_data(indices: dict) -> str:
    lines = []
    for name, data in indices.items():
        lines.append(f"{name}: {data['value']} ({data['change_pct']:+.2f}%) [{data['source']}, {data['timestamp'][:16]}]")
    return "\n".join(lines)


def format_macro_data(macro: dict) -> str:
    lines = []
    for region in ["us", "eu"]:
        region_data = macro.get(region, {})
        if region_data:
            lines.append(f"\n--- {region.upper()} ---")
            for name, data in region_data.items():
                if isinstance(data, dict):
                    note = f" ({data.get('note', '')})" if data.get("note") else ""
                    lines.append(f"{name}: {data.get('value')} [{data.get('source', '?')}, {data.get('date', '?')}]{note}")
    return "\n".join(lines)


def format_news(news: dict, section: str = "position_news") -> str:
    items = news.get(section, {})
    if isinstance(items, dict):
        lines = []
        for ticker, articles in items.items():
            lines.append(f"\n{ticker}:")
            for a in articles:
                age = a.get('published', a.get('age', '?'))
                lines.append(f"  - [{age}] {a['title']}: {a['description'][:150]}")
        return "\n".join(lines)
    elif isinstance(items, list):
        return "\n".join(f"- [{a.get('published', a.get('age', '?'))}] {a['title']}: {a['description'][:150]}" for a in items)
    return "Keine News verfügbar."


def build_briefing_prompt(portfolio: dict, market_data: dict, macro_data: dict, news: dict,
                          memory_context: str, candidates: list[dict] | None = None) -> str:
    """Baut den kompletten Briefing-Prompt zusammen."""
    fg = macro_data.get("fear_greed")
    fg_str = "Nicht verfügbar"
    if fg:
        fg_str = f"Score: {fg.get('value')} ({fg.get('rating')}) | Vorwoche: {fg.get('previous_1_week')} | Vormonat: {fg.get('previous_1_month')}"

    # Bloomberg Headlines
    bloomberg = news.get("bloomberg_headlines", [])
    bloomberg_str = "\n".join(f"- [{b.get('published', '?')}] {b['title']}" for b in bloomberg) if bloomberg else "Nicht verfügbar."

    # Sentiment-Daten
    sentiment = news.get("sentiment", {})
    sentiment_str = "Nicht verfügbar."
    if sentiment:
        lines = []
        for ticker, s in sentiment.items():
            bull = s.get("bullish")
            bear = s.get("bearish")
            buzz = s.get("buzz_volume")
            trend = s.get("rating_trend")
            trend_str = ""
            if trend:
                detail = s.get("rating_trend_detail")
                trend_str = f" | Analysten-Rating: {trend}" + (f" ({detail})" if detail else "")
            if bull is not None:
                lines.append(f"  {ticker}: {bull:.0%} bullish / {bear:.0%} bearish (Artikel letzte Woche: {buzz or '?'}){trend_str}")
            elif trend:
                lines.append(f"  {ticker}:{trend_str}")
        if lines:
            sentiment_str = "\n".join(lines)

    base = BRIEFING_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        portfolio_summary=build_portfolio_summary(portfolio, market_data),
        market_data=format_market_data(market_data),
        index_data=format_index_data(market_data.get("indices", {})),
        macro_data=format_macro_data(macro_data),
        fear_greed=fg_str,
        position_news=format_news(news, "position_news"),
        macro_news=format_news(news, "macro_news"),
        watchlist=format_watchlist(market_data),
        candidates=format_candidates(candidates),
        memory_context=memory_context,
    )

    # Bloomberg + Sentiment anhängen
    extra = f"""

=== BLOOMBERG HEADLINES ===

{bloomberg_str}

=== SENTIMENT-ANALYSE (Finnhub) ===

{sentiment_str}
"""
    # §0-Mandat ganz oben voranstellen (oberste Direktive). Opt-in: leer wenn kein Mandat → keine Änderung.
    mandate_block = build_mandate_block(load_mandate())
    prefix = mandate_block + "\n\n" if mandate_block else ""
    return prefix + base + extra


def build_ticker_analysis_prompt(ticker: str, ticker_data: dict, portfolio: dict, market_data: dict, news: list) -> str:
    """Baut den Prompt für eine On-Demand Ticker-Analyse."""
    p = ticker_data.get("price", {})
    # Rohes returns-Array (252 Tagesreturns) NICHT in den Prompt dumpen — bloated nur.
    p = {k: v for k, v in p.items() if k != "returns"}
    ticker_str = json.dumps(p, indent=2, default=str)
    news_str = "\n".join(f"- {a['title']}: {a['description'][:150]}" for a in news) if news else "Keine News gefunden."

    return TICKER_ANALYSIS_TEMPLATE.format(
        ticker=ticker,
        ticker_data=ticker_str,
        portfolio_summary=build_portfolio_summary(portfolio, market_data),
        news=news_str,
    )
