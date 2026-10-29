"""
System-Alarme (Briefing/Report fehlgeschlagen, Claude-Login defekt).

Gehen als Mitteilung (Kategorie system_error) an iPhone und Web-App.  Telegram
nur, wenn es für system_error eingeschaltet ist — oder als Notnagel, wenn kein
einziger Push zugestellt wurde.  Ein Alarm, der niemanden erreicht, wäre
schlimmer als eine doppelte Nachricht.
"""

from __future__ import annotations

import asyncio
import logging

from src.config_loader import load_settings

logger = logging.getLogger(__name__)


async def send_system_alert(title: str, detail: str) -> None:
    """Niemals eine Exception raus — läuft in Fehlerpfaden."""
    from src.delivery.push_sender import send_push_safe

    sent = await asyncio.to_thread(
        send_push_safe,
        category="system_error",
        title=title,
        body=detail[:300],
        url="/",
        tag="system-error",
    )

    try:
        from src.chat.db import is_channel_enabled
        telegram_on = is_channel_enabled("system_error", "telegram")
    except Exception:
        telegram_on = False

    if sent and not telegram_on:
        return

    tg = load_settings().get("telegram", {})
    bot_token = (tg.get("bot_token") or "").strip()
    chat_id = str(tg.get("chat_id") or "").strip()
    if not bot_token or not chat_id:
        if not sent:
            logger.error("Alarm '%s' konnte nirgends zugestellt werden", title)
        return
    if not sent:
        logger.warning("Kein Push zugestellt — Alarm '%s' geht per Telegram", title)
    try:
        from src.delivery.telegram import send_error_alert
        await send_error_alert(bot_token, chat_id, f"{title}: {detail}")
    except Exception:
        logger.exception("Telegram-Alarm fehlgeschlagen")
