#!/usr/bin/env python3
"""
Auth-Wächter für die Claude-CLI hinter Velora.

Macht einen billigen Test-Aufruf (Haiku) und prüft, ob die CLI-Authentifizierung
noch lebt. Schlägt er fehl — typisch: abgelaufener/invalidierter OAuth-Token → 401 —
geht eine Telegram-Warnung an den Nutzer. Und zwar PROAKTIV, bevor das nächste
Briefing oder ein Chat daran scheitert und Velora scheinbar "still stirbt".

Ersetzt den früheren Keep-Alive: Ein langlebiger setup-token (1 Jahr) braucht
kein 4h-Warmhalten mehr. Was fehlte, war eine Benachrichtigung, wenn die Auth doch
einmal kippt — genau die liefert dieser Wächter.

Exit 0 = Auth ok.  Exit 1 = Auth defekt (Alarm verschickt).
"""

import asyncio
import fcntl
import logging
import subprocess
import sys
from pathlib import Path

# Script liegt in scripts/ — Repo-Root in den Importpfad heben.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.analysis.claude import _LOCK_PATH, _resolve_claude_bin, build_claude_env  # noqa: E402
from src.config_loader import load_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auth_watchdog")

TEST_TIMEOUT = 120


def _run_test_call() -> tuple[bool, str]:
    """Billiger CLI-Aufruf (Haiku). Returns (ok, detail)."""
    cmd = [
        _resolve_claude_bin(),
        "--print",
        "--tools", "",
        "--no-session-persistence",
        "--model", "claude-haiku-4-5",
    ]
    # Gleicher File-Lock wie ask_claude() — kollidiert nicht mit laufendem Briefing/Chat.
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            result = subprocess.run(
                cmd,
                input="Antworte nur mit: ok",
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT,
                env=build_claude_env(),
            )
        except subprocess.TimeoutExpired:
            return False, f"Timeout nach {TEST_TIMEOUT}s"
        except FileNotFoundError:
            return False, "Claude CLI nicht gefunden (PATH?)"
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()

    if result.returncode == 0 and (result.stdout or "").strip():
        return True, (result.stdout or "").strip()[:120]

    detail = ((result.stderr or "").strip() or (result.stdout or "").strip() or "(keine Ausgabe)")[:300]
    return False, f"exit {result.returncode}: {detail}"


async def _alert(detail: str) -> None:
    tg = load_settings().get("telegram", {})
    bot_token = (tg.get("bot_token") or "").strip()
    chat_id = (tg.get("chat_id") or "").strip()
    if not bot_token or not chat_id:
        logger.error("Kein Telegram-Token/Chat konfiguriert — kann nicht alarmieren.")
        return
    from src.delivery.telegram import send_error_alert
    msg = (
        "Claude-Login defekt — Velora kann gerade keine Briefings/Analysen erzeugen. "
        f"Detail: {detail} "
        "Beheben: am RockPi `claude setup-token` ausführen, dann "
        "`./venv/bin/python scripts/set_oauth_token.py` und Services neustarten."
    )
    await send_error_alert(bot_token, chat_id, msg)


def main() -> int:
    ok, detail = _run_test_call()
    if ok:
        logger.info("Claude-Auth ok (%s)", detail)
        return 0
    logger.error("Claude-Auth DEFEKT: %s", detail)
    try:
        asyncio.run(_alert(detail))
        logger.info("Telegram-Warnung verschickt.")
    except Exception:
        logger.exception("Telegram-Warnung fehlgeschlagen")
    return 1


if __name__ == "__main__":
    sys.exit(main())
