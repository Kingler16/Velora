"""
Warnung, bevor der TestFlight-Build der iOS-App abläuft.

TestFlight-Builds laufen 90 Tage nach dem Upload ab. Danach startet die App
nicht mehr, und Mitteilungen (auch Systemfehler) kommen still nicht mehr an.
ios/testflight.sh vergibt Build-Nummern als JJJJMMTT.HHMM — die App meldet sie
bei jeder Anmeldung als app_version („1.0 (20261029.1625)“), daraus lässt sich
das Upload-Datum ablesen, ohne dass die App etwas Neues schicken muss.

Andere Builds (Xcode direkt, kostenloser Account, andere Nummern) werden still
übersprungen.
"""

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).parent.parent.parent / "memory" / "build_expiry.json"

TESTFLIGHT_DAYS = 90
WARN_DAYS = (14, 7, 3, 1)       # an diesen Resttagen je einmal per Push erinnern
SHOW_DAYS = WARN_DAYS[0]        # ab hier Hinweis im Dashboard
_BUILD_RE = re.compile(r"\((\d{8})\.\d{4}\)")


def build_date(app_version: str | None) -> date | None:
    m = _BUILD_RE.search(app_version or "")
    if not m:
        return None
    try:
        s = m.group(1)
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def expiry_status(devices: list[dict] | None = None, today: date | None = None) -> dict | None:
    """Ältester TestFlight-Build unter den aktiven Geräten. None ohne passendes Gerät."""
    if devices is None:
        from src.chat.db import get_active_apns_devices
        devices = get_active_apns_devices()
    today = today or date.today()
    builds = [(build_date(d.get("app_version")), d.get("app_version"))
              for d in devices if d.get("environment") == "production"]
    builds = [b for b in builds if b[0]]
    if not builds:
        return None
    built, version = min(builds)
    expires = built + timedelta(days=TESTFLIGHT_DAYS)
    return {"app_version": version, "built": built.isoformat(), "expires": expires.isoformat(),
            "days_left": (expires - today).days}


def _load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("build_expiry.json nicht lesbar: %s", e)
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_PATH)


def check_and_notify(devices: list[dict] | None = None, today: date | None = None, send=None) -> bool:
    """Schickt höchstens eine Erinnerung je Schwelle und Build. True, wenn gesendet wurde."""
    status = expiry_status(devices, today)
    if not status or status["days_left"] < 0:
        return False
    due = [d for d in WARN_DAYS if status["days_left"] <= d]
    if not due:
        return False
    threshold = min(due)
    state = _load_state()
    sent_for = state.get(status["app_version"], [])
    if threshold in sent_for:
        return False

    days = status["days_left"]
    when = "heute" if days == 0 else ("morgen" if days == 1 else f"in {days} Tagen")
    expires = date.fromisoformat(status["expires"]).strftime("%d.%m.%Y")
    if send is None:
        from src.delivery.push_sender import send_push_safe as send
    send(category="system_error",
         title=f"iOS-App läuft {when} ab",
         body=(f"Der TestFlight-Build {status['app_version']} läuft am {expires} ab. Danach kommen keine "
               f"Mitteilungen mehr an. Neuen Build mit ios/testflight.sh hochladen."),
         url="/", tag="build-expiry")
    # Alle Schwellen bis hierher als erledigt markieren — nach einer Pause
    # (Server aus) nicht mehrere Erinnerungen auf einmal nachschicken.
    state[status["app_version"]] = sorted(set(sent_for) | set(due))
    _save_state(state)
    logger.info("Ablauf-Erinnerung gesendet: %s, noch %d Tage", status["app_version"], days)
    return True
