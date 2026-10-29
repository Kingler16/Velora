"""
Push-Versand: Web Push (VAPID) für die Web-App + APNs für die iOS-App.

Liest VAPID-Keys aus config_loader (ENV > settings.json), iteriert alle
aktiven Subscriptions und sendet per pywebpush.  Respektiert die
notification_preferences-Tabelle pro Kategorie (push_enabled gilt für beide
Wege).  404/410 vom Push-Service deaktiviert die Subscription automatisch
(Cleanup von stale endpoints).  APNs-Details: src/delivery/apns.py.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.chat.db import (
    deactivate_push_subscription,
    get_active_push_subscriptions,
    is_channel_enabled,
    touch_push_subscription,
)
from src.config_loader import load_settings

logger = logging.getLogger(__name__)


def _vapid_config() -> dict | None:
    settings = load_settings().get("web_push", {})
    priv = settings.get("vapid_private_key")
    sub = settings.get("vapid_subject") or "mailto:admin@velora.local"
    if not priv:
        return None
    return {"vapid_private_key": priv, "vapid_claims": {"sub": sub}}


def send_push(
    category: str,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    """Sendet eine Push-Notification an alle aktiven Subscriptions und iPhones.

    Returns Anzahl erfolgreicher Sendungen.  Gibt 0 zurück wenn Kategorie
    deaktiviert, nichts konfiguriert oder keine Empfänger.
    """
    if not is_channel_enabled(category, "push"):
        logger.debug("Push für Kategorie %s deaktiviert — überspringe", category)
        return 0

    sent = _send_webpush(category, title, body, url, tag, data)
    try:
        from src.delivery.apns import send_apns
        sent += send_apns(category, title, body, url=url, tag=tag, data=data)
    except Exception:
        logger.exception("iOS-Push für %s fehlgeschlagen", category)
    return sent


def _send_webpush(
    category: str,
    title: str,
    body: str,
    url: str,
    tag: str | None,
    data: dict[str, Any] | None,
) -> int:
    vapid = _vapid_config()
    if vapid is None:
        logger.info("Web Push nicht konfiguriert (VAPID-Key fehlt) — überspringe %s", category)
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush nicht installiert — Push für %s übersprungen", category)
        return 0

    subs = get_active_push_subscriptions()
    if not subs:
        logger.debug("Keine aktiven Push-Subscriptions — überspringe %s", category)
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag or category,
        "category": category,
        "data": data or {},
    }, ensure_ascii=False)

    sent = 0
    for s in subs:
        subscription = {
            "endpoint": s["endpoint"],
            "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
        }
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=vapid["vapid_private_key"],
                vapid_claims=dict(vapid["vapid_claims"]),  # pywebpush mutiert
                ttl=60 * 60 * 24,  # 24h
            )
            touch_push_subscription(s["endpoint"])
            sent += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                logger.info("Stale Push-Endpoint (HTTP %s) — deaktiviere %s", code, s["endpoint"][:60])
                deactivate_push_subscription(s["endpoint"])
            else:
                logger.warning("Push fehlgeschlagen (HTTP %s) für %s: %s", code, s["endpoint"][:60], e)
        except Exception:
            logger.exception("Unerwarteter Fehler beim Push-Senden für %s", s["endpoint"][:60])

    logger.info("Push %s gesendet an %d/%d Subscriptions", category, sent, len(subs))
    return sent


def send_push_safe(*args, **kwargs) -> int:
    """Niemals eine Exception raus — fürs Einbetten in kritische Pfade wie Trade-Logging."""
    try:
        return send_push(*args, **kwargs)
    except Exception:
        logger.exception("send_push raised unexpectedly")
        return 0
