"""
Haupt-Orchestrator für den AI-Vermögensberater.

Modi:
  briefing  — Reguläres Briefing (2x/Woche via Cron)
  monthly   — Monatsbericht (1x/Monat via Cron)
  analyze   — On-Demand Ticker-Analyse
  bot       — Telegram Bot dauerhaft laufen lassen
"""

import argparse
import asyncio
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.market import collect_all_market_data, fetch_price_data, get_all_tickers, load_portfolio, fetch_insider_activity
from src.data.macro import collect_all_macro_data
from src.data.news import collect_all_news, search_position_news
from src.data.calendar import (
    fetch_earnings_calendar,
    get_market_status,
    get_upcoming_macro_events,
    format_full_calendar,
)
from src.analysis.prompt import (
    build_system_prompt,
    build_briefing_prompt,
    build_ticker_analysis_prompt,
    build_portfolio_summary,
    format_regime,
    format_risk_metrics,
    format_correlation,
    format_strategy_drift,
    MONTHLY_REPORT_TEMPLATE,
)
from src.analysis.claude import ask_claude, strip_json_block, ClaudeCLIError
from src.analysis.memory import (
    get_context_for_prompt,
    save_briefing_summary,
    save_recommendations,
    update_recommendation_outcomes,
    save_monthly_snapshot,
    update_notes,
    add_position_thesis,
    load_memory,
)
from src.analysis.chat_history import add_message, get_history_for_prompt
from src.analysis.performance import (
    calculate_benchmark_comparison,
    find_tax_loss_harvesting,
    track_recommendation_performance,
    classify_regime,
    compute_risk_metrics,
    compute_correlation_data,
)
from src.data.cache import save_cache
from src.delivery.telegram import send_briefing, send_document, send_error_alert, create_bot_app

try:
    from src.delivery.pdf_report import generate_pdf
    HAS_PDF = True
except (ImportError, OSError):
    HAS_PDF = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"

from src.config_loader import load_settings  # noqa: E402  ENV-Override + settings.json


async def run_briefing():
    """Führt das reguläre Briefing durch."""
    logger.info("=== BRIEFING START ===")
    settings = load_settings()
    tg = settings.get("telegram", {})

    try:
        portfolio = load_portfolio()

        # 1. Daten sammeln
        logger.info("Sammle Marktdaten...")
        market_data = collect_all_market_data(portfolio)

        logger.info("Sammle Makrodaten...")
        macro_data = collect_all_macro_data(settings.get("fred", {}).get("api_key", ""))

        logger.info("Sammle News...")
        tickers = get_all_tickers(portfolio)
        news = collect_all_news(
            tickers,
            brave_api_key=settings.get("brave_search", {}).get("api_key", ""),
            finnhub_api_key=settings.get("finnhub", {}).get("api_key", ""),
        )

        logger.info("Sammle Kalender-Daten...")
        earnings = fetch_earnings_calendar(tickers)
        market_status = get_market_status()
        macro_events = get_upcoming_macro_events(days_ahead=30)
        calendar_str = format_full_calendar(market_status, earnings, macro_events)

        # 1b. Cache für Dashboard schreiben
        save_cache("market_data", market_data)
        save_cache("macro_data", macro_data)
        save_cache("news_data", news)
        save_cache("calendar_data", {
            "earnings": earnings,
            "market_status": market_status,
            "macro_events": macro_events,
        })

        # 2. Performance & Analytics
        logger.info("Berechne Performance-Metriken...")
        benchmark = calculate_benchmark_comparison(market_data)
        tax_loss = find_tax_loss_harvesting(portfolio, market_data)
        rec_tracking = track_recommendation_performance(market_data)
        regime = classify_regime(market_data, macro_data)
        risk_metrics = compute_risk_metrics(market_data, macro_data)
        correlation = compute_correlation_data(market_data)
        from src.web.services.portfolio_service import compute_portfolio_overview
        overview = compute_portfolio_overview(portfolio, market_data)
        from src.analysis.mandate import load_mandate, compute_strategy_drift
        drift_str = format_strategy_drift(compute_strategy_drift(overview, load_mandate()))
        drift_section = f"\n=== STRATEGIE-DRIFT (Soll vs. Ist deines Mandats) ===\n\n{drift_str}\n" if drift_str else ""

        # 3. Memory laden + offene Empfehlungen updaten
        logger.info("Lade Memory...")
        update_recommendation_outcomes(market_data)
        memory_context = get_context_for_prompt()

        # 4. Prompt bauen + Claude aufrufen
        logger.info("Baue Prompt...")
        base_prompt = build_briefing_prompt(portfolio, market_data, macro_data, news, memory_context)

        # Zusätzliche Sektionen anhängen
        extra = f"""

=== MARKT-REGIME (berechnet, regelbasiert — als objektiver Anker für deine Einschätzung) ===

{format_regime(regime)}

=== RISIKO-KENNZAHLEN PRO POSITION (aus 1J-Tagesdaten) ===

{format_risk_metrics(risk_metrics, market_data)}

=== KORRELATION & KLUMPENRISIKO ===

{format_correlation(correlation)}
{drift_section}
=== FINANZKALENDER (Börsen, Earnings, Makro-Events) ===

{calendar_str}

=== BENCHMARK-VERGLEICH ===

{benchmark}

=== TAX-LOSS-HARVESTING (KESt 27.5%) ===

{tax_loss}

=== EMPFEHLUNGS-BILANZ ===

{rec_tracking}
"""
        full_prompt = base_prompt + extra

        logger.info(f"Rufe Claude auf (Prompt: {len(full_prompt)} Zeichen)...")
        result = ask_claude(build_system_prompt(load_settings(), load_portfolio()), full_prompt)

        # 5. Memory updaten
        briefing_text = strip_json_block(result["text"])
        structured = result.get("structured")
        if structured:
            if structured.get("summary"):
                save_briefing_summary(
                    structured["summary"],
                    structured.get("recommendations", []),
                    structured.get("market_regime"),
                    full_text=briefing_text,
                )
            if structured.get("recommendations"):
                save_recommendations(structured["recommendations"], overview)
            if structured.get("market_regime"):
                update_notes("market_regime", structured["market_regime"])
            if structured.get("new_insights"):
                memory = load_memory()
                existing = memory["notes"].get("key_insights", [])
                existing.extend(structured["new_insights"])
                existing = existing[-20:]
                update_notes("key_insights", existing)
            if structured.get("position_theses_updates"):
                for ticker, thesis in structured["position_theses_updates"].items():
                    add_position_thesis(ticker, thesis)

        # 6. Via Telegram senden (wenn aktiviert)
        try:
            from src.chat.db import is_channel_enabled
            telegram_on = is_channel_enabled("briefings", "telegram")
        except Exception:
            telegram_on = True

        if tg.get("bot_token") and tg.get("chat_id") and telegram_on:
            logger.info("Sende via Telegram...")
            await send_briefing(tg["bot_token"], tg["chat_id"], briefing_text)
        elif not telegram_on:
            logger.info("Telegram-Briefings deaktiviert (notification_preferences)")
            print(briefing_text)
        else:
            print(briefing_text)

        # 7. Push-Notification (Kategorie: briefings)
        try:
            from datetime import date
            from src.delivery.push_sender import send_push_safe
            summary_text = ""
            if structured and structured.get("summary"):
                summary_text = str(structured["summary"])[:120]
            send_push_safe(
                category="briefings",
                title=f"Briefing · {date.today().strftime('%d.%m.')}",
                body=summary_text or "Neues Briefing ist da.",
                url="/briefings",
                tag="briefing",
            )
        except Exception:
            logger.exception("Push für Briefing fehlgeschlagen")

    except Exception as e:
        error_msg = f"Briefing fehlgeschlagen: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        if tg.get("bot_token") and tg.get("chat_id"):
            await send_error_alert(tg["bot_token"], tg["chat_id"], str(e))

    logger.info("=== BRIEFING ENDE ===")


async def run_monthly_report():
    """Erstellt den Monatsreport."""
    logger.info("=== MONATSREPORT START ===")
    settings = load_settings()
    tg = settings.get("telegram", {})

    try:
        portfolio = load_portfolio()
        market_data = collect_all_market_data(portfolio)
        macro_data = collect_all_macro_data(settings.get("fred", {}).get("api_key", ""))
        memory = load_memory()

        # Cache für Dashboard
        save_cache("market_data", market_data)
        save_cache("macro_data", macro_data)

        portfolio_summary = build_portfolio_summary(portfolio, market_data)
        benchmark = calculate_benchmark_comparison(market_data)
        tax_loss = find_tax_loss_harvesting(portfolio, market_data)
        rec_tracking = track_recommendation_performance(market_data)

        monthly_data = f"""
PORTFOLIO-STAND:
{portfolio_summary}

BENCHMARK-VERGLEICH:
{benchmark}

TAX-LOSS-HARVESTING:
{tax_loss}

EMPFEHLUNGS-BILANZ:
{rec_tracking}

MAKRO-DATEN:
{json.dumps(macro_data, indent=2, default=str)}

INDIZES:
{json.dumps(market_data.get('indices', {}), indent=2, default=str)}
"""

        snapshots = json.dumps(memory.get("monthly_snapshots", []), indent=2, default=str)
        prompt = MONTHLY_REPORT_TEMPLATE.format(monthly_data=monthly_data, monthly_snapshots=snapshots)

        result = ask_claude(build_system_prompt(load_settings(), load_portfolio()), prompt)

        structured = result.get("structured")
        if structured:
            save_monthly_snapshot(structured)

        briefing_text = strip_json_block(result["text"])

        if tg.get("bot_token") and tg.get("chat_id"):
            # PDF generieren und senden (wenn verfügbar)
            if HAS_PDF:
                try:
                    logger.info("Generiere PDF-Report...")
                    pdf_path = generate_pdf(briefing_text)
                    await send_document(
                        tg["bot_token"], tg["chat_id"],
                        str(pdf_path),
                        caption=f"\U0001f4ca Monatsbericht {datetime.now().strftime('%B %Y')}",
                    )
                except Exception as e:
                    logger.warning(f"PDF-Generierung fehlgeschlagen: {e}")

            # Text-Nachricht immer senden
            await send_briefing(tg["bot_token"], tg["chat_id"], f"\U0001f4ca <b>MONATSREPORT</b>\n\n{briefing_text}")
        else:
            print(briefing_text)
            print(f"\nPDF gespeichert: {pdf_path}")

    except Exception as e:
        error_msg = f"Monatsreport fehlgeschlagen: {e}"
        logger.error(error_msg)
        if tg.get("bot_token") and tg.get("chat_id"):
            await send_error_alert(tg["bot_token"], tg["chat_id"], str(e))

    logger.info("=== MONATSREPORT ENDE ===")


async def run_ticker_analysis(ticker: str, update=None, context=None):
    """On-Demand Analyse eines Tickers."""
    logger.info(f"=== ANALYSE: {ticker} ===")
    settings = load_settings()

    price_data = fetch_price_data(ticker)
    if not price_data:
        msg = f"Konnte keine Daten für {ticker} finden. Prüfe den Ticker."
        if update:
            await update.message.reply_text(msg)
        else:
            print(msg)
        return

    insider_data = fetch_insider_activity(ticker)
    ticker_data = {"price": price_data, "insiders": insider_data}

    portfolio = load_portfolio()
    market_data = collect_all_market_data(portfolio)

    brave_key = settings.get("brave_search", {}).get("api_key", "")
    news = search_position_news(price_data.get("ticker", ticker), ticker, brave_key) if brave_key else []

    prompt = build_ticker_analysis_prompt(ticker, ticker_data, portfolio, market_data, news)
    try:
        result = ask_claude(build_system_prompt(load_settings(), load_portfolio()), prompt)
    except ClaudeCLIError as e:
        logger.error(f"Ticker-Analyse {ticker} fehlgeschlagen: {e}")
        tg = settings.get("telegram", {})
        if update:
            await update.message.reply_text(f"⚠️ Analyse fehlgeschlagen: {e}")
        elif tg.get("bot_token") and tg.get("chat_id"):
            await send_error_alert(tg["bot_token"], tg["chat_id"], f"Ticker-Analyse {ticker}: {e}")
        return
    analysis_text = strip_json_block(result["text"])

    if update:
        from src.delivery.telegram import send_briefing as tg_send
        await tg_send(settings["telegram"]["bot_token"], str(update.effective_chat.id), analysis_text)
    else:
        tg = settings.get("telegram", {})
        if tg.get("bot_token") and tg.get("chat_id"):
            await send_briefing(tg["bot_token"], tg["chat_id"], analysis_text)
        else:
            print(analysis_text)

    logger.info(f"=== ANALYSE {ticker} ENDE ===")


def run_bot():
    """Startet den Telegram Bot im Polling-Modus."""
    logger.info("=== TELEGRAM BOT START ===")
    settings = load_settings()
    tg = settings.get("telegram", {})

    if not tg.get("bot_token") or not tg.get("chat_id"):
        logger.error("Telegram bot_token und chat_id müssen in settings.json konfiguriert sein!")
        sys.exit(1)

    async def on_ticker_request(ticker, update, context):
        await run_ticker_analysis(ticker, update, context)

    async def on_briefing_request(update, context):
        await run_briefing()

    async def on_free_chat(text, update, context):
        """Freie Frage an Claude mit Portfolio-Kontext + Chat-Verlauf."""
        add_message("user", text)

        portfolio = load_portfolio()
        market_data = collect_all_market_data(portfolio)
        portfolio_summary = build_portfolio_summary(portfolio, market_data)
        memory_context = get_context_for_prompt()
        chat_history = get_history_for_prompt()

        prompt = f"""Der Nutzer schreibt dir eine Nachricht. Du bist sein persönlicher Vermögensberater.
Du führst ein Gespräch — beziehe dich auf den Chat-Verlauf wenn relevant.

=== PORTFOLIO-KONTEXT ===
{portfolio_summary}

=== MEMORY ===
{memory_context}

{chat_history}

=== AKTUELLE NACHRICHT ===
{text}

Antworte direkt, kurz und hilfreich auf Deutsch. Telegram-HTML-Format. Kein Geschwafel."""

        try:
            result = ask_claude(build_system_prompt(load_settings(), load_portfolio()), prompt)
            reply = strip_json_block(result["text"])
        except ClaudeCLIError as e:
            logger.error(f"Free-Chat fehlgeschlagen: {e}")
            reply = f"⚠️ Kann gerade nicht antworten: {e}"
        add_message("assistant", reply[:2000])
        await send_briefing(tg["bot_token"], str(update.effective_chat.id), reply)

    app = create_bot_app(tg["bot_token"], tg["chat_id"], on_ticker_request, on_briefing_request, on_free_chat)
    logger.info("Bot läuft... (Ctrl+C zum Beenden)")
    app.run_polling()


def run_web(host: str = "0.0.0.0", port: int = 8080):
    """Startet das Web-Dashboard."""
    logger.info("=== WEB DASHBOARD START ===")
    settings = load_settings()
    web_cfg = settings.get("web", {})
    host = web_cfg.get("host", host)
    port = web_cfg.get("port", port)

    from src.web.app import run_web_server
    run_web_server(host=host, port=port)


def main():
    parser = argparse.ArgumentParser(description="AI Vermögensberater")
    parser.add_argument(
        "mode",
        choices=["briefing", "monthly", "analyze", "bot", "web"],
        help="Modus: briefing (2x/Woche), monthly (Monatsreport), analyze (Ticker), bot (Telegram Bot), web (Dashboard)",
    )
    parser.add_argument("--ticker", "-t", help="Ticker für Analyse-Modus")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port für Web-Modus")

    args = parser.parse_args()

    if args.mode == "briefing":
        asyncio.run(run_briefing())
    elif args.mode == "monthly":
        asyncio.run(run_monthly_report())
    elif args.mode == "analyze":
        if not args.ticker:
            parser.error("--ticker ist für den Analyse-Modus erforderlich")
        asyncio.run(run_ticker_analysis(args.ticker))
    elif args.mode == "bot":
        run_bot()
    elif args.mode == "web":
        run_web(port=args.port)


if __name__ == "__main__":
    main()
