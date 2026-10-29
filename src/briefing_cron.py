"""
Briefing-Zeitplan → Crontab.

Die Briefings startet cron (`python -m src.main briefing`), eingerichtet von
scripts/setup_server.sh.  Ändert jemand den Zeitplan in App oder Web, ersetzt
diese Funktion die Velora-Briefing-Zeile in der Crontab – alle anderen Einträge
bleiben unangetastet.

Wessen Crontab: die des Benutzers, dem das Velora-Verzeichnis gehört.  Läuft der
Web-Dienst als root (typisch auf dem Pi), wird mit `crontab -u <besitzer>`
gearbeitet – sonst landete ein zweiter Job in roots Crontab und das Briefing
liefe doppelt.

Bewusst nur ÄNDERN, nicht still ANLEGEN: Auf einem Entwicklungsrechner ohne
Server-Setup soll Speichern keine Briefings per cron starten.  Angelegt wird der
Eintrag nur von setup_server.sh (`create=True`).
"""

from __future__ import annotations

import logging
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

WEEKDAYS = {
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 0,
}
_DAY_LABELS = {"monday": "Mo", "tuesday": "Di", "wednesday": "Mi", "thursday": "Do",
               "friday": "Fr", "saturday": "Sa", "sunday": "So"}

MARKER = "# Velora — Briefing"
_JOB = "src.main briefing"


class ScheduleError(ValueError):
    pass


def normalize(days, time: str) -> tuple[list[str], int, int]:
    """Prüft Tage + Uhrzeit.  days darf Liste oder "monday,thursday" sein."""
    if isinstance(days, str):
        days = days.split(",")
    picked = {str(d).strip().lower() for d in (days or []) if str(d).strip()}
    unknown = picked - WEEKDAYS.keys()
    if unknown:
        raise ScheduleError(f"Unbekannte Wochentage: {', '.join(sorted(unknown))}")
    if not picked:
        raise ScheduleError("Mindestens ein Wochentag nötig")
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(time or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ScheduleError(f"Ungültige Uhrzeit: {time!r} (erwartet HH:MM)")
    ordered = [d for d in WEEKDAYS if d in picked]
    return ordered, int(m.group(1)), int(m.group(2))


def briefing_block(install_dir: Path, days: list[str], hour: int, minute: int) -> list[str]:
    dow = ",".join(str(WEEKDAYS[d]) for d in days)
    return [
        f"{MARKER} ({','.join(days)} {hour:02d}:{minute:02d})",
        f"{minute} {hour} * * {dow} cd {install_dir} && ./venv/bin/python -m {_JOB} "
        f">> {install_dir}/logs/briefing.log 2>&1",
    ]


def rewrite(crontab: str, block: list[str], create: bool = False) -> str | None:
    """Neue Crontab mit `block` an Stelle des alten Briefing-Eintrags.

    None, wenn es keinen Briefing-Eintrag gibt und create=False.
    """
    lines = crontab.splitlines()
    is_job = [not l.lstrip().startswith("#") and _JOB in l for l in lines]
    if not any(is_job) and not create:
        return None
    kept: list[str] = []
    insert_at = None
    for line, job in zip(lines, is_job):
        if job or line.strip().startswith(MARKER):
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(line)
    if insert_at is None:
        insert_at = len(kept)
    kept[insert_at:insert_at] = block
    return "\n".join(kept) + "\n"


def _crontab_cmd(install_dir: Path) -> tuple[list[str], str]:
    owner = pwd.getpwuid(install_dir.stat().st_uid).pw_name
    if os.geteuid() == 0 and owner != "root":
        return ["crontab", "-u", owner], owner
    return ["crontab"], pwd.getpwuid(os.geteuid()).pw_name


def apply_briefing_schedule(days, time: str, install_dir: Path | None = None,
                            create: bool = False) -> dict:
    """Überträgt den Zeitplan in die Crontab.

    Returns {"applied": bool, "message": str}.  Wirft ScheduleError nur bei
    ungültiger Eingabe; Systemprobleme (kein cron, keine Rechte) kommen als
    applied=False mit Erklärung zurück.
    """
    ordered, hour, minute = normalize(days, time)
    install_dir = Path(install_dir or _REPO_ROOT)
    label = f"{', '.join(_DAY_LABELS[d] for d in ordered)} um {hour:02d}:{minute:02d}"

    if not shutil.which("crontab"):
        return {"applied": False,
                "message": "Zeitplan gespeichert, aber auf diesem System gibt es kein cron – "
                           "Briefings bitte selbst planen (python -m src.main briefing)."}

    cmd, user = _crontab_cmd(install_dir)
    current = subprocess.run(cmd + ["-l"], capture_output=True, text=True, timeout=15)
    if current.returncode != 0 and "no crontab" not in (current.stderr or "").lower():
        logger.warning("crontab -l fehlgeschlagen: %s", current.stderr.strip())
        return {"applied": False, "message": f"Zeitplan gespeichert, Crontab nicht lesbar: {current.stderr.strip()}"}
    text = current.stdout if current.returncode == 0 else ""

    new = rewrite(text, briefing_block(install_dir, ordered, hour, minute), create=create)
    if new is None:
        return {"applied": False,
                "message": f"Zeitplan gespeichert, aber in der Crontab von {user} gibt es noch keinen "
                           "Velora-Briefing-Eintrag – einmal `bash scripts/setup_server.sh` ausführen."}
    if new.strip() == text.strip():
        return {"applied": True, "message": f"Briefings laufen {label}."}

    written = subprocess.run(cmd + ["-"], input=new, capture_output=True, text=True, timeout=15)
    if written.returncode != 0:
        logger.warning("crontab schreiben fehlgeschlagen: %s", written.stderr.strip())
        return {"applied": False, "message": f"Zeitplan gespeichert, Crontab nicht änderbar: {written.stderr.strip()}"}
    logger.info("Briefing-Zeitplan in Crontab von %s übernommen: %s", user, label)
    return {"applied": True, "message": f"Briefings laufen ab jetzt {label}."}


if __name__ == "__main__":
    # Für scripts/setup_server.sh: Zeitplan aus settings.json übernehmen, Eintrag notfalls anlegen.
    import sys
    from src.config_loader import load_settings

    sched = load_settings().get("schedule", {})
    try:
        result = apply_briefing_schedule(sched.get("briefing_days") or ["monday", "thursday"],
                                         sched.get("briefing_time") or "07:00", create=True)
    except ScheduleError as e:
        print(f"✕ {e}")
        sys.exit(1)
    print(("✓ " if result["applied"] else "✕ ") + result["message"])
    sys.exit(0 if result["applied"] else 1)
