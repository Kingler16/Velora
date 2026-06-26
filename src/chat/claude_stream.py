"""Claude Code CLI Subprocess mit stream-json Parsing.

Startet die CLI im Non-Interactive-Modus (--print), lässt sie NDJSON emittieren,
und yielded parsed Events (text-deltas, tool-calls, tool-results, done).
Session-Persistenz via --session-id / --resume, sodass Folge-Messages die
History nicht erneut im Prompt transportieren müssen.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from src.analysis.claude import _LOCK_PATH, build_claude_env

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.json"


def _find_claude_bin() -> str:
    """Claude-CLI finden: Settings > shutil.which > bekannte Pfade."""
    try:
        with open(SETTINGS_PATH) as f:
            configured = json.load(f).get("claude", {}).get("command", "claude")
    except Exception:
        configured = "claude"

    if configured != "claude" and Path(configured).is_absolute():
        return configured

    found = shutil.which("claude")
    if found:
        return found

    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude",
        home / ".npm-global" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/usr/bin/claude"),
    ]
    nvm_dir = home / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        for node_ver in sorted(nvm_dir.iterdir(), reverse=True):
            candidates.append(node_ver / "bin" / "claude")

    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)

    return "claude"


@dataclass
class StreamEvent:
    """Parsed Event aus dem stream-json Output."""
    type: str
    data: dict


def _extract_text_deltas(raw: dict) -> list[str]:
    """Aus einem assistant/stream-event alle Text-Deltas ziehen."""
    out: list[str] = []
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    # Fall 1: partielle delta-events (mit --include-partial-messages)
    if raw.get("type") == "stream_event":
        ev = raw.get("event") or {}
        delta = ev.get("delta") or {}
        if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
            out.append(delta["text"])
        return out
    # Fall 2: vollständige assistant-messages
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    out.append(t)
    return out


def _extract_tool_use(raw: dict) -> Optional[dict]:
    """Gibt {'id', 'name', 'input'} zurück, falls ein tool_use-Block im Event ist."""
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input") or {},
                }
    return None


def _extract_tool_result(raw: dict) -> Optional[dict]:
    """Gibt {'tool_use_id', 'content'} zurück, falls tool_result-Block im Event ist."""
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                c = block.get("content")
                if isinstance(c, list):
                    texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                    c = "\n".join(texts)
                return {"tool_use_id": block.get("tool_use_id"), "content": c}
    return None


async def stream_chat(
    *,
    user_prompt: str,
    system_prompt: str,
    session_id: Optional[str] = None,
    resume_session_id: Optional[str] = None,
    mcp_config_path: Optional[str] = None,
    allowed_tools: Optional[list[str]] = None,
    model: str = "claude-opus-4-8",
    effort: str = "high",
    cwd: Optional[str] = None,
) -> AsyncIterator[StreamEvent]:
    """Ruft die Claude CLI auf und yielded parsed Events.

    Yields:
        StreamEvent(type='text_delta', data={'text': ...})
        StreamEvent(type='assistant_message', data={'text': ...})
        StreamEvent(type='tool_use', data={'id', 'name', 'input'})
        StreamEvent(type='tool_result', data={'tool_use_id', 'content'})
        StreamEvent(type='done', data={'session_id', 'total_cost', 'usage'})
        StreamEvent(type='error', data={'message'})
    """
    claude_bin = _find_claude_bin()

    cmd: list[str] = [
        claude_bin,
        "--print",
        "--system-prompt", system_prompt,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",  # stream-json benötigt verbose, sonst Fehler
        "--model", model,
        "--effort", effort,
    ]

    if mcp_config_path:
        cmd += ["--mcp-config", mcp_config_path, "--strict-mcp-config"]

    if allowed_tools is not None:
        # Permission-Mode: akzeptiert unsere whitelisted Tools ohne Prompt,
        # andere werden automatisch verweigert (da wir dontAsk verwenden).
        cmd += ["--allowedTools", ",".join(allowed_tools), "--permission-mode", "dontAsk"]
    else:
        # Ohne MCP: alle Tools deaktivieren (Phase 1)
        cmd += ["--tools", ""]

    if resume_session_id:
        cmd += ["--resume", resume_session_id]
    elif session_id:
        cmd += ["--session-id", session_id]

    logger.info("Claude CLI start: session=%s resume=%s tools=%s",
                session_id, resume_session_id, allowed_tools)

    # Denselben File-Lock wie ask_claude (src/analysis/claude.py) nur um den
    # Subprozess-START nehmen: der OAuth-Token-Refresh passiert beim CLI-Start,
    # und ohne Serialisierung korrumpieren parallele Refreshes die .credentials.json
    # (z.B. Web-Chat während ein Cron-Briefing läuft). Der Lock wird SOFORT nach
    # dem Spawn freigegeben — nicht über die minutenlange Stream-Dauer gehalten,
    # sonst würden Briefings blockieren.
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=build_claude_env(),
        )
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()

    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(user_prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_task = asyncio.create_task(proc.stderr.read())

    emitted_text_ids: set[str] = set()  # block-IDs deren Text wir via delta bereits gestreamt haben
    try:
        async for line_bytes in proc.stdout:
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Non-JSON line from CLI: %s", line[:200])
                continue

            t = raw.get("type")

            # Partial text deltas
            if t == "stream_event":
                ev = raw.get("event") or {}
                et = ev.get("type")
                if et == "content_block_start":
                    block = ev.get("content_block") or {}
                    if block.get("type") == "text" and ev.get("index") is not None:
                        emitted_text_ids.add(f"idx_{ev['index']}")
                elif et == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield StreamEvent("text_delta", {"text": text})
                continue

            # Vollständige assistant-message (enthält sowohl text als auch tool_use-Blöcke)
            if t == "assistant":
                tool_use = _extract_tool_use(raw)
                if tool_use:
                    yield StreamEvent("tool_use", tool_use)
                # Falls keine deltas emittiert wurden (z.B. ohne --include-partial-messages),
                # finale Text-Blöcke senden
                if not emitted_text_ids:
                    for text in _extract_text_deltas(raw):
                        yield StreamEvent("assistant_message", {"text": text})
                continue

            # Tool-Results kommen als "user"-Events
            if t == "user":
                tool_result = _extract_tool_result(raw)
                if tool_result:
                    yield StreamEvent("tool_result", tool_result)
                continue

            if t == "result":
                yield StreamEvent("done", {
                    "session_id": raw.get("session_id"),
                    "total_cost_usd": raw.get("total_cost_usd"),
                    "usage": raw.get("usage"),
                    "num_turns": raw.get("num_turns"),
                    "is_error": raw.get("is_error", False),
                })
                continue

            if t == "system":
                # Enthält initiale Session-Info — kann an Frontend weitergegeben werden
                yield StreamEvent("system", {
                    "session_id": raw.get("session_id"),
                    "model": raw.get("model"),
                })
                continue

            # Unbekanntes Event: durchreichen für Debugging
            yield StreamEvent("raw", raw)

    finally:
        rc = await proc.wait()
        stderr = (await stderr_task).decode("utf-8", errors="replace")
        if rc != 0:
            logger.error("Claude CLI exit %d. stderr: %s", rc, stderr[:2000])
            yield StreamEvent("error", {
                "message": f"Claude CLI Exit-Code {rc}",
                "stderr": stderr[-2000:],
            })
        elif stderr.strip():
            logger.debug("Claude stderr (exit 0): %s", stderr[:1000])
