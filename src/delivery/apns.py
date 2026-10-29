"""
Apple Push Notification service (APNs) für die iOS-App.

Token-basierte Auth: ein .p8-Schlüssel (Apple Developer → Keys) signiert ein
kurzlebiges JWT, das für alle Geräte gilt.  Konfiguration in settings.json:

    "apns": {
      "key_path":  "config/keys/apns_AuthKey_XXXXXXXXXX.p8",
      "key_id":    "XXXXXXXXXX",
      "team_id":   "564XMJKP3J",
      "bundle_id": "dev.max.velora"
    }

Fehlt etwas davon, wird still übersprungen (wie beim Web-Push ohne VAPID).
Ungültige/abgemeldete Gerätetokens werden automatisch deaktiviert.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from src.chat.db import deactivate_apns_device, get_active_apns_devices, touch_apns_device
from src.config_loader import load_settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent

APNS_HOSTS = {
    "production": "https://api.push.apple.com",
    "sandbox": "https://api.sandbox.push.apple.com",
}

# Apple: Provider-Token frühestens nach 20 min, spätestens nach 60 min erneuern.
_TOKEN_MAX_AGE = 50 * 60
_token_cache: dict[str, tuple[float, str]] = {}

# Gründe, bei denen das Gerätetoken dauerhaft unbrauchbar ist (App gelöscht, falsche App).
_DEAD_TOKEN_REASONS = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}
_AUTH_REASONS = {"ExpiredProviderToken", "InvalidProviderToken"}

# APNs erlaubt 4 KB Payload – Zusatzdaten nur mitschicken, solange sicher Platz ist.
_MAX_DATA_BYTES = 2000


def apns_config() -> dict | None:
    cfg = load_settings().get("apns", {}) or {}
    key_path = (cfg.get("key_path") or "").strip()
    key_id = (cfg.get("key_id") or "").strip()
    team_id = (cfg.get("team_id") or "").strip()
    bundle_id = (cfg.get("bundle_id") or "").strip()
    if not (key_path and key_id and team_id and bundle_id):
        return None
    path = Path(key_path)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    if not path.exists():
        logger.warning("APNs-Schlüssel %s fehlt — iOS-Push übersprungen", path)
        return None
    return {"key_path": path, "key_id": key_id, "team_id": team_id, "bundle_id": bundle_id}


def _provider_token(cfg: dict) -> str:
    cached = _token_cache.get(cfg["key_id"])
    if cached and time.time() - cached[0] < _TOKEN_MAX_AGE:
        return cached[1]
    import jwt

    issued = time.time()
    token = jwt.encode(
        {"iss": cfg["team_id"], "iat": int(issued)},
        cfg["key_path"].read_text(),
        algorithm="ES256",
        headers={"kid": cfg["key_id"]},
    )
    _token_cache[cfg["key_id"]] = (issued, token)
    return token


def build_payload(category: str, title: str, body: str, url: str,
                  data: dict[str, Any] | None = None) -> dict:
    payload: dict[str, Any] = {
        "aps": {
            "alert": {"title": title[:120], "body": body[:400]},
            "sound": "default",
            "thread-id": category,
        },
        "category": category,
        "url": url,
    }
    if data:
        encoded = json.dumps(data, ensure_ascii=False, default=str)
        if len(encoded.encode()) <= _MAX_DATA_BYTES:
            payload["data"] = json.loads(encoded)
    return payload


def send_apns(
    category: str,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    """Schickt eine Mitteilung an alle registrierten iPhones.  Returns Anzahl Zustellungen."""
    cfg = apns_config()
    if cfg is None:
        logger.debug("APNs nicht konfiguriert — überspringe %s", category)
        return 0

    devices = get_active_apns_devices()
    if not devices:
        logger.debug("Keine registrierten iOS-Geräte — überspringe %s", category)
        return 0

    try:
        import httpx
    except ImportError:
        logger.warning("httpx nicht installiert — iOS-Push für %s übersprungen", category)
        return 0

    payload = json.dumps(build_payload(category, title, body, url, data), ensure_ascii=False).encode()
    headers = {
        "authorization": f"bearer {_provider_token(cfg)}",
        "apns-topic": cfg["bundle_id"],
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time()) + 24 * 3600),
    }
    if tag:
        headers["apns-collapse-id"] = tag.encode()[:64].decode(errors="ignore")

    sent = 0
    with httpx.Client(http2=True, timeout=15) as client:
        for d in devices:
            host = APNS_HOSTS.get(d["environment"], APNS_HOSTS["production"])
            try:
                r = client.post(f"{host}/3/device/{d['token']}", content=payload, headers=headers)
            except Exception:
                logger.exception("APNs-Verbindung fehlgeschlagen für %s…", d["token"][:12])
                continue
            if r.status_code == 200:
                touch_apns_device(d["token"])
                sent += 1
                continue
            try:
                reason = r.json().get("reason", "")
            except Exception:
                reason = r.text[:100]
            if r.status_code == 410 or reason in _DEAD_TOKEN_REASONS:
                logger.info("APNs-Token ungültig (%s) — deaktiviere %s…", reason, d["token"][:12])
                deactivate_apns_device(d["token"])
            elif reason in _AUTH_REASONS:
                _token_cache.pop(cfg["key_id"], None)
                logger.warning("APNs lehnt den Schlüssel ab (%s) — Key-ID/Team-ID prüfen", reason)
            else:
                logger.warning("APNs HTTP %s (%s) für %s…", r.status_code, reason, d["token"][:12])

    logger.info("iOS-Push %s gesendet an %d/%d Geräte", category, sent, len(devices))
    return sent
