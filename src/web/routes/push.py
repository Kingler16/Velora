"""Push-Notification-API: Subscribe/Unsubscribe/Preferences/Test.

Web-App: VAPID-Subscriptions (/subscribe).  iOS-App: APNs-Gerätetoken (/apns/…).
Preferences gelten für beide Wege.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.chat.db import (
    deactivate_apns_device,
    deactivate_push_subscription,
    get_notification_preferences,
    set_notification_preference,
    upsert_apns_device,
    upsert_push_subscription,
)
from src.config_loader import load_settings
from src.delivery.push_sender import send_push

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/vapid-public-key")
async def vapid_public_key():
    key = load_settings().get("web_push", {}).get("vapid_public_key") or ""
    return {"key": key, "configured": bool(key)}


@router.post("/subscribe")
async def subscribe(req: Request):
    data = await req.json()
    sub = data.get("subscription") or data
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not (endpoint and p256dh and auth):
        raise HTTPException(status_code=400, detail="Invalid subscription payload")
    upsert_push_subscription(
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=req.headers.get("user-agent", "")[:200],
    )
    logger.info("Push-Subscription registriert: %s…", endpoint[:60])
    return {"status": "ok"}


@router.post("/unsubscribe")
async def unsubscribe(req: Request):
    data = await req.json()
    endpoint = data.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")
    deactivate_push_subscription(endpoint)
    return {"status": "ok"}


_APNS_TOKEN = re.compile(r"^[0-9a-fA-F]{64,200}$")


@router.post("/apns/register")
async def apns_register(req: Request):
    """iOS-App meldet ihr Gerätetoken – bei jedem Start, weil es sich ändern kann."""
    data = await req.json()
    token = str(data.get("token") or "").strip()
    environment = data.get("environment") or "production"
    if not _APNS_TOKEN.match(token):
        raise HTTPException(status_code=400, detail="Ungültiges Gerätetoken")
    if environment not in ("production", "sandbox"):
        raise HTTPException(status_code=400, detail="environment muss production oder sandbox sein")
    upsert_apns_device(
        token=token.lower(),
        environment=environment,
        device_name=str(data.get("device_name") or "")[:100] or None,
        app_version=str(data.get("app_version") or "")[:40] or None,
    )
    logger.info("iOS-Gerät registriert (%s): %s…", environment, token[:12])
    return {"status": "ok"}


@router.post("/apns/unregister")
async def apns_unregister(req: Request):
    data = await req.json()
    token = str(data.get("token") or "").strip().lower()
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    deactivate_apns_device(token)
    return {"status": "ok"}


@router.get("/preferences")
async def get_preferences():
    return get_notification_preferences()


@router.post("/preferences")
async def set_preferences(req: Request):
    """Body: { category: { telegram_enabled, push_enabled } } — bulk update."""
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected object")
    # Fehlende Felder behalten ihren Wert – die iOS-App schickt nur push_enabled.
    current = get_notification_preferences()
    updated = 0
    for category, prefs in body.items():
        if not isinstance(prefs, dict):
            continue
        cur = current.get(category, {})
        set_notification_preference(
            category=category,
            telegram_enabled=bool(prefs.get("telegram_enabled", cur.get("telegram_enabled", True))),
            push_enabled=bool(prefs.get("push_enabled", cur.get("push_enabled", True))),
        )
        updated += 1
    return {"status": "ok", "updated": updated}


@router.post("/test")
async def test_push():
    """Schickt eine Test-Push an alle aktiven Subscriptions (ignoriert Kategorien-Toggle)."""
    # Direkt ohne Kategorien-Filter senden — test ist immer gewollt
    count = send_push(
        category="test",
        title="Velora-Push funktioniert ✓",
        body="Dies ist eine Test-Benachrichtigung.",
        url="/",
        tag="velora-test",
    )
    return JSONResponse({"status": "ok", "sent": count})
