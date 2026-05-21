"""
Claude Code CLI Wrapper.
Ruft Claude im non-interactive Modus auf.
"""

import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaudeCLIError(RuntimeError):
    """Claude CLI-Aufruf fehlgeschlagen (exit code, timeout, auth, leere Antwort)."""


_LOCK_PATH = Path.home() / ".claude" / ".velora-cli.lock"


def _resolve_claude_bin() -> str:
    """Claude-Binary-Pfad auflösen: settings.json > PATH > bekannte Pfade."""
    claude_bin = "claude"
    try:
        settings_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
        with open(settings_path) as f:
            settings = json.load(f)
        claude_bin = settings.get("claude", {}).get("command", "claude")
    except Exception:
        pass

    if claude_bin == "claude" or not Path(claude_bin).is_absolute():
        found = shutil.which("claude")
        if found:
            return found
        home = Path.home()
        candidates = [
            home / ".local" / "bin" / "claude",
            home / ".npm-global" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
            Path("/usr/bin/claude"),
            Path("/snap/bin/claude"),
        ]
        nvm_dir = home / ".nvm" / "versions" / "node"
        if nvm_dir.exists():
            for node_ver in sorted(nvm_dir.iterdir(), reverse=True):
                candidates.append(node_ver / "bin" / "claude")
        for c in candidates:
            if c.exists() and os.access(c, os.X_OK):
                logger.info(f"Claude CLI gefunden: {c}")
                return str(c)
        logger.warning("Claude CLI nicht in bekannten Pfaden — versuche 'claude' direkt.")
    return claude_bin


def ask_claude(system_prompt: str, user_prompt: str, timeout: int = 1200) -> dict:
    """
    Ruft Claude Code CLI auf und gibt Analyse + strukturierte Daten zurück.
    Prompt wird via stdin übergeben.

    Raises:
        ClaudeCLIError: Bei exit≠0, leerer Antwort, Timeout, Binary fehlt oder Auth-Fehler.
            Caller MUSS die Exception fangen — niemals den Error-Text als Analyse weiterreichen.
    """
    claude_bin = _resolve_claude_bin()
    cmd = [
        claude_bin,
        "--print",
        "--system-prompt", system_prompt,
        "--tools", "",
        "--no-session-persistence",
        "--model", "claude-opus-4-6",
        "--effort", "high",
    ]

    # File-Lock serialisiert parallele Aufrufe aus diesem Projekt (bot + web + briefing).
    # Verhindert Race Conditions beim Token-Refresh, die die .credentials.json korrumpieren.
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        logger.info(f"Claude CLI wird aufgerufen (Prompt: {len(user_prompt)} Zeichen)...")
        try:
            result = subprocess.run(
                cmd,
                input=user_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI Timeout nach {timeout}s")
            raise ClaudeCLIError(f"Timeout nach {timeout}s")
        except FileNotFoundError:
            logger.error("Claude CLI nicht gefunden. Ist 'claude' im PATH?")
            raise ClaudeCLIError("Claude CLI nicht installiert")
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        combined = stderr or stdout
        if "401" in combined or "authentication" in combined.lower() or "invalid" in combined.lower() and "credentials" in combined.lower():
            logger.error(f"Claude CLI Auth-Fehler (exit {result.returncode}): stderr={stderr[:500]} stdout={stdout[:500]}")
            raise ClaudeCLIError(
                "Claude CLI ist nicht mehr authentifiziert (401). "
                "Bitte am RockPi interaktiv `claude` starten und `/login` ausführen."
            )
        logger.error(f"Claude CLI Fehler (exit {result.returncode}): stderr={stderr[:1000]!r} stdout={stdout[:1000]!r}")
        detail = stderr[:200] or stdout[:200] or '(kein stderr/stdout)'
        raise ClaudeCLIError(f"Claude CLI exit {result.returncode}: {detail}")

    output = (result.stdout or "").strip()
    if not output:
        stderr = (result.stderr or "").strip()
        logger.error(f"Claude CLI leere Ausgabe. Stderr: {stderr[:500]}")
        raise ClaudeCLIError(f"Leere Antwort von Claude (stderr: {stderr[:200] or 'leer'})")

    logger.info(f"Claude Antwort: {len(output)} Zeichen")
    return {
        "text": output,
        "structured": extract_json_block(output),
    }


def extract_json_block(text: str) -> dict | None:
    """Extrahiert den JSON-Block aus Claudes Antwort."""
    pattern = r"```json\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        try:
            return json.loads(matches[-1])
        except json.JSONDecodeError as e:
            logger.error(f"JSON-Parse-Fehler: {e}")
    return None


def strip_json_block(text: str) -> str:
    """Entfernt den JSON-Block aus dem Text (für Telegram)."""
    pattern = r"\n*```json\s*\n.*?\n\s*```\s*$"
    return re.sub(pattern, "", text, flags=re.DOTALL).strip()
