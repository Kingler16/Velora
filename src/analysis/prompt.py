"""
System-Prompt und Daten-Formatting für den Vermögensberater.
"""

import json
from datetime import datetime


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
   - Wenn du in den News/Opportunities-Daten interessante Titel findest
   - Prüfe: Passt es ins Portfolio? (Diversifikation, Sektor, Risiko)
   - Nur vorschlagen wenn wirklich überzeugend, nicht auf Krampf
   - KEINE Morningstar/Analyst-Empfehlungen nachplappern. Eigene Analyse.

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

=== NEUE INVESTMENT-IDEEN (aus Research) ===

{opportunities}

=== MEMORY (vergangene Briefings & offene Empfehlungen) ===

{memory_context}

=== DEINE AUFGABE ===

Erstelle das Briefing. Struktur:

1. MARKTLAGE (2-3 Sätze, was hat sich VERÄNDERT seit dem letzten Briefing? Nutze die Makro-Daten: Yield Curve, Credit Spreads, Inflation, Zinsen. Nutze Benchmark-Vergleich.)
2. PORTFOLIO-CHECK (nur Positionen erwähnen wo sich etwas RELEVANTES getan hat. Fonds-Positionen einordnen falls vorhanden. EUR/USD Auswirkung auf USD-Positionen berechnen. KRITISCH: Verwende für die Performance jeder Position IMMER die "P/L: ...€ (...%)" Werte aus dem PORTFOLIO-Abschnitt oben — diese basieren auf dem persönlichen Buy-In. Die "Kursperf. 1M/6M/1Y" Werte aus den MARKTDATEN zeigen die allgemeine Aktienperformance und sind NICHT identisch mit der Position-Performance!)
3. EARNINGS & EVENTS (welche Positionen reporten bald? Was ist zu erwarten? Kommende Katalysatoren.)
4. EMPFEHLUNGEN — STRENG: max. 3 Einträge pro Briefing, nur High-Conviction. Wenn nichts überzeugt: 0 Empfehlungen ist die richtige Antwort. "Halten" / "Beobachten ohne Order" gehört in den Fließtext, NICHT in die JSON-Liste. Jede Empfehlung MUSS konkret sein: Einstieg, Stop-Loss, Ziel, Risk/Reward UND Stückzahl. Bei Kauf: Anzahl Stück. Bei Verkauf: Prozent der Position ODER Anzahl Stück. Berücksichtige Tax-Loss-Harvesting wenn sinnvoll.
5. NEUE IDEEN (nur wenn wirklich überzeugend. Eigene Analyse, keine Morningstar-Listen.)
6. RISIKEN AUF DEM RADAR (was könnte schiefgehen?)
7. EMPFEHLUNGS-BILANZ (wenn es offene Empfehlungen gibt: wie haben sie sich entwickelt?)

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

    # EUR/USD Kurs aus Indizes holen
    eur_usd = 1.0
    indices = market_data.get("indices", {})
    if "EUR/USD" in indices:
        eur_usd = indices["EUR/USD"].get("value", 1.0)
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
            if ticker and ticker in market_data.get("positions", {}):
                current_price = market_data["positions"][ticker].get("price", {}).get("current_price")

            if current_price:
                # Aktuellen Wert in EUR umrechnen
                current_price_eur = current_price if currency == "EUR" else current_price / eur_usd
                current_value_eur = shares * current_price_eur
                pnl_eur = current_value_eur - invested_eur
                pnl_pct = (pnl_eur / invested_eur) * 100 if invested_eur else 0
                total_value_eur += current_value_eur
                total_invested_eur += invested_eur

                currency_note = f" [USD→EUR, Kurs in {currency}: {current_price:.2f}]" if currency == "USD" else ""
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
        lines.append(
            f"{data['name']} ({ticker}):\n"
            f"  Kurs: {p.get('current_price')} | Tagesänderung: {p.get('change_pct', '?')}%\n"
            f"  52W-Hoch: {p.get('52w_high')} | 52W-Tief: {p.get('52w_low')}\n"
            f"  Kursperf. 1M: {p.get('perf_1m_pct') or 'k.A.'}{'%' if p.get('perf_1m_pct') is not None else ''} | Kursperf. 6M: {p.get('perf_6m_pct') or 'k.A.'}{'%' if p.get('perf_6m_pct') is not None else ''} | Kursperf. 1Y: {p.get('perf_1y_pct') or 'k.A.'}{'%' if p.get('perf_1y_pct') is not None else ''}\n"
            f"  KGV: {p.get('pe_ratio', '?')} | Forward KGV: {p.get('forward_pe', '?')} | PEG: {p.get('peg_ratio', '?')}\n"
            f"  Dividendenrendite: {p.get('dividend_yield', '?')} | Beta: {p.get('beta', '?')}\n"
            f"  Short Interest: {p.get('short_interest', '?')} | Insider-Anteil: {p.get('insider_buy_pct', '?')}\n"
            f"  Sektor: {p.get('sector', '?')} | Branche: {p.get('industry', '?')}\n"
            f"  [Quelle: {p.get('source')}, {p.get('timestamp', '')[:16]}]"
        )
        # Insider-Transaktionen
        insiders = data.get("insiders", [])
        if insiders:
            lines.append("  Insider-Transaktionen (letzte 90 Tage):")
            for ins in insiders[:3]:
                lines.append(f"    {ins.get('date')}: {ins.get('insider')} - {ins.get('transaction')} - {ins.get('shares')} Stk")

    return "\n\n".join(lines)


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


def build_briefing_prompt(portfolio: dict, market_data: dict, macro_data: dict, news: dict, memory_context: str) -> str:
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
            if bull is not None:
                lines.append(f"  {ticker}: {bull:.0%} bullish / {bear:.0%} bearish (Artikel letzte Woche: {buzz or '?'})")
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
        opportunities=format_news(news, "opportunities"),
        memory_context=memory_context,
    )

    # Bloomberg + Sentiment anhängen
    extra = f"""

=== BLOOMBERG HEADLINES ===

{bloomberg_str}

=== SENTIMENT-ANALYSE (Finnhub) ===

{sentiment_str}
"""
    return base + extra


def build_ticker_analysis_prompt(ticker: str, ticker_data: dict, portfolio: dict, market_data: dict, news: list) -> str:
    """Baut den Prompt für eine On-Demand Ticker-Analyse."""
    p = ticker_data.get("price", {})
    ticker_str = json.dumps(p, indent=2, default=str)
    news_str = "\n".join(f"- {a['title']}: {a['description'][:150]}" for a in news) if news else "Keine News gefunden."

    return TICKER_ANALYSIS_TEMPLATE.format(
        ticker=ticker,
        ticker_data=ticker_str,
        portfolio_summary=build_portfolio_summary(portfolio, market_data),
        news=news_str,
    )
