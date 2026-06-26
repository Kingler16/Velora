"""
Zentraler Settings-Loader mit ENV-Override.

Alle Module importieren von hier statt eigene _load_settings-Funktionen zu haben.
ENV-Variablen haben Vorrang vor config/settings.json — wichtig für Secrets auf
Production (RockPi via systemd EnvironmentFile), damit settings.json nur
Defaults/Struktur enthält und Tokens/Keys nicht auf der Platte liegen müssen.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"

# (section, key) -> ENV-Variable.  ENV gewinnt immer über Datei-Wert.
_ENV_OVERRIDES: dict[tuple[str, str], str] = {
    ("telegram", "bot_token"):           "TELEGRAM_BOT_TOKEN",
    ("telegram", "chat_id"):             "TELEGRAM_CHAT_ID",
    ("brave_search", "api_key"):         "BRAVE_API_KEY",
    ("fred", "api_key"):                 "FRED_API_KEY",
    ("finnhub", "api_key"):              "FINNHUB_API_KEY",
    ("data", "twelvedata_api_key"):      "TWELVEDATA_API_KEY",
    ("web_push", "vapid_public_key"):    "VAPID_PUBLIC_KEY",
    ("web_push", "vapid_private_key"):   "VAPID_PRIVATE_KEY",
    ("web_push", "vapid_subject"):       "VAPID_SUBJECT",
    ("web", "public_url"):               "VELORA_PUBLIC_URL",
    ("notifications", "telegram_enabled"): "TELEGRAM_ENABLED",
    ("claude", "oauth_token"):             "CLAUDE_CODE_OAUTH_TOKEN",
}

_BOOL_KEYS = {("notifications", "telegram_enabled")}


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> dict:
    """Liest settings.json und überlagert mit ENV-Variablen."""
    try:
        data: dict = json.loads(_SETTINGS_PATH.read_text()) if _SETTINGS_PATH.exists() else {}
    except Exception:
        data = {}

    for (section, key), env_name in _ENV_OVERRIDES.items():
        val = os.getenv(env_name)
        if val is None or val == "":
            continue
        section_map = data.setdefault(section, {})
        if (section, key) in _BOOL_KEYS:
            section_map[key] = _parse_bool(val)
        else:
            section_map[key] = val
    return data
