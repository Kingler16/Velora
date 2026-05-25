"""
Cache-Service: Liest gecachte Daten und liefert sie an die Web-Routes.
"""

import json
import logging
from pathlib import Path

from src.data.cache import load_cache, get_cache_age_minutes, get_cache_timestamp

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent.parent.parent / "memory"


def get_market_data() -> dict:
    """Lädt gecachte Marktdaten oder gibt leeres Dict zurück."""
    return load_cache("market_data") or {}


def get_macro_data() -> dict:
    """Lädt gecachte Makrodaten."""
    return load_cache("macro_data") or {}


def get_news_data() -> dict:
    """Lädt gecachte News."""
    return load_cache("news_data") or {}


def get_calendar_data() -> dict:
    """Lädt gecachte Kalender-Daten."""
    return load_cache("calendar_data") or {}


def get_cache_status() -> dict:
    """Gibt Status aller Caches zurück."""
    keys = ["market_data", "macro_data", "news_data", "calendar_data"]
    status = {}
    for key in keys:
        age = get_cache_age_minutes(key)
        status[key] = {
            "available": age is not None,
            "age_minutes": round(age, 1) if age else None,
            "timestamp": get_cache_timestamp(key),
        }
    return status


def get_monthly_snapshots() -> list:
    """Lädt monatliche Portfolio-Snapshots aus memory/."""
    path = MEMORY_DIR / "monthly_snapshots.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def get_briefings() -> list:
    """Lädt Briefing-History."""
    path = MEMORY_DIR / "briefings.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def get_recommendations() -> list:
    """Lädt Empfehlungen. Filtert 'hold' raus — die Empfehlungs-UI zeigt nur Aktionen, die der User tatsächlich ausführen muss (Kauf/Verkauf/Limit-Order)."""
    path = MEMORY_DIR / "recommendations.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            recs = json.load(f)
        return [r for r in recs if r.get("action") != "hold"]
    except Exception:
        return []


def get_notes() -> dict:
    """Lädt Notes (Market Regime, Thesen, Insights)."""
    path = MEMORY_DIR / "notes.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}
