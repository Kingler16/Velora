"""FastAPI-Routes für den Web-Chat.

Endpoints:
  GET    /api/chat/threads            → Thread-Liste
  POST   /api/chat/threads            → Thread anlegen
  GET    /api/chat/threads/{id}       → Thread + Messages
  PATCH  /api/chat/threads/{id}       → Titel/Pin ändern
  DELETE /api/chat/threads/{id}       → Thread löschen
  POST   /api/chat/threads/{id}/message  → Message senden (SSE-Stream)

  GET    /api/chat/pins               → globale Pins listen
  POST   /api/chat/pins               → Pin anlegen (global oder thread-scope)
  DELETE /api/chat/pins/{id}          → Pin löschen
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.chat import db
from src.chat.memory import build_full_system_prompt, build_user_message_with_history, maybe_auto_summarize
from src.chat.claude_stream import stream_chat
from src.chat.mcp_config import get_mcp_config_path, VELORA_TOOLS, CONFIRMATION_REQUIRED_TOOLS
from src.chat.actions import execute_pending_action, reject_pending_action
from src.chat.slash_commands import is_slash_command, handle_slash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── Models ────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: Optional[str] = "Neuer Chat"


class ThreadPatch(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class PinCreate(BaseModel):
    key: str
    value: str
    thread_id: Optional[str] = None
    pinned_by: str = "user"


class MessageSend(BaseModel):
    message: str
    page_context: Optional[dict] = None
    effort: Optional[str] = None  # Override, default = chat-default
    model: Optional[str] = None


# ── Thread-CRUD ───────────────────────────────────────────────

@router.get("/threads")
def list_threads():
    return {"threads": db.list_threads()}


@router.post("/threads")
def create_thread(body: ThreadCreate):
    return db.create_thread(body.title or "Neuer Chat")


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str):
    thread = db.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread nicht gefunden")
    messages = db.get_messages(thread_id)
    return {"thread": thread, "messages": messages}


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: str, body: ThreadPatch):
    if not db.get_thread(thread_id):
        raise HTTPException(404, "Thread nicht gefunden")
    fields = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.is_pinned is not None:
        fields["is_pinned"] = 1 if body.is_pinned else 0
    if fields:
        db.update_thread(thread_id, **fields)
    return db.get_thread(thread_id)


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str):
    db.delete_thread(thread_id)
    return {"deleted": thread_id}


# ── Pins ──────────────────────────────────────────────────────

@router.get("/pins")
def list_pins(thread_id: Optional[str] = None):
    return {"pins": db.get_pinned_memories(thread_id=thread_id, include_global=True)}


@router.post("/pins")
def create_pin(body: PinCreate):
    pin_id = db.add_pinned_memory(
        key=body.key, value=body.value,
        thread_id=body.thread_id, pinned_by=body.pinned_by,
    )
    return {"id": pin_id}


@router.delete("/pins/{pin_id}")
def delete_pin(pin_id: int):
    db.delete_pinned_memory(pin_id)
    return {"deleted": pin_id}


# ── Confirmation (Write-Tools) ──────────────────────────────

class ConfirmRequest(BaseModel):
    action_id: str
    approved: bool


@router.post("/confirm")
def confirm_action(body: ConfirmRequest):
    if body.approved:
        return execute_pending_action(body.action_id)
    return reject_pending_action(body.action_id)


@router.get("/pending")
def list_pending(thread_id: Optional[str] = None):
    return {"pending": db.list_pending_actions(thread_id=thread_id)}


# ── Chat-Stream (SSE) ────────────────────────────────────────

def _sse(event: str, data: dict | str) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _is_user_facing_tool(name: str) -> bool:
    """Filter: nur Velora-Agent-Actions an UI durchreichen. CLI-interne Lookups
    (ToolSearch etc.) für den User uninteressant."""
    if not name:
        return False
    return name.startswith("mcp__velora__")


def _extract_action_confirmation(content) -> Optional[dict]:
    """Tool-Results von Write-Tools enthalten `status: pending_confirmation` + action_id.
    Diese Methode extrahiert die relevanten Felder."""
    if content is None:
        return None
    data = content
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    if data.get("status") != "pending_confirmation":
        return None
    return {
        "action_id": data.get("action_id"),
        "summary": data.get("summary"),
    }


@router.post("/threads/{thread_id}/message")
async def send_message(thread_id: str, body: MessageSend, request: Request):
    thread = db.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Thread nicht gefunden")

    if not body.message.strip():
        raise HTTPException(400, "Leere Nachricht")

    # User-Message persistieren
    db.add_message(thread_id, "user", body.message)

    # Wenn Thread noch keinen Titel (oder Default-Titel) hat → aus erster Nachricht ableiten
    if thread["title"] in ("Neuer Chat", "", None) and thread.get("message_count", 0) == 0:
        auto_title = body.message.strip().split("\n")[0][:60]
        db.update_thread(thread_id, title=auto_title)

    # Bei langen Threads: alte Messages zu Summary komprimieren (Hintergrund, best-effort)
    try:
        maybe_auto_summarize(thread_id)
    except Exception as e:
        logger.warning("Auto-Summary skipped: %s", e)

    async def event_stream() -> AsyncIterator[bytes]:
        system_prompt = build_full_system_prompt(thread_id, body.page_context)
        resume_id = thread.get("session_id")

        if resume_id:
            # Bei --resume reicht die neue Message alleine, Claude Code kennt die History
            user_prompt = body.message
        else:
            user_prompt = build_user_message_with_history(thread_id, body.message)

        new_session_id = str(uuid.uuid4()) if not resume_id else None

        effort = body.effort or "high"
        model = body.model or "claude-opus-4-8"

        assistant_text_parts: list[str] = []
        tool_use_log: list[dict] = []
        final_session_id: Optional[str] = None
        had_error = False

        yield _sse("start", {"thread_id": thread_id})

        if is_slash_command(body.message):
            stream = handle_slash(body.message)
        else:
            stream = stream_chat(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                session_id=new_session_id,
                resume_session_id=resume_id,
                model=model,
                effort=effort,
                mcp_config_path=get_mcp_config_path(),
                allowed_tools=VELORA_TOOLS,
            )

        try:
            async for ev in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected, cancelling stream")
                    break

                if ev.type == "system":
                    yield _sse("system", ev.data)
                elif ev.type == "text_delta":
                    assistant_text_parts.append(ev.data.get("text", ""))
                    yield _sse("token", ev.data)
                elif ev.type == "assistant_message":
                    # nur wenn keine deltas kamen
                    assistant_text_parts.append(ev.data.get("text", ""))
                    yield _sse("token", ev.data)
                elif ev.type == "tool_use":
                    name = ev.data.get("name", "")
                    if not _is_user_facing_tool(name):
                        continue
                    tool_use_log.append(ev.data)
                    db.add_message(
                        thread_id, "tool_use",
                        json.dumps(ev.data, ensure_ascii=False),
                        tool_name=name,
                    )
                    yield _sse("tool_use", ev.data)
                elif ev.type == "tool_result":
                    tid = ev.data.get("tool_use_id")
                    matched_tool = next((t for t in tool_use_log if t.get("id") == tid), None)
                    if matched_tool:
                        yield _sse("tool_result", ev.data)
                        # Wenn ein Write-Tool ein pending_confirmation zurückgegeben hat,
                        # emittiere ein confirmation_required-Event fürs Frontend.
                        if matched_tool.get("name") in CONFIRMATION_REQUIRED_TOOLS:
                            action_info = _extract_action_confirmation(ev.data.get("content"))
                            if action_info and action_info.get("action_id"):
                                pa = db.get_pending_action(action_info["action_id"])
                                try:
                                    with db._connect() as _c:
                                        _c.execute(
                                            "UPDATE pending_actions SET thread_id = ? WHERE id = ?",
                                            (thread_id, action_info["action_id"])
                                        )
                                except Exception:
                                    pass
                                yield _sse("confirmation_required", {
                                    **action_info,
                                    "tool_name": matched_tool.get("name"),
                                    "params": (pa or {}).get("params") if pa else matched_tool.get("input"),
                                })
                                # Push: wenn User grade nicht im Chat ist (App zu / anderer Tab),
                                # soll er Bescheid bekommen dass eine Bestätigung wartet.
                                try:
                                    from src.delivery.push_sender import send_push_safe
                                    summary = (action_info.get("summary") or "").strip()
                                    tool_label = matched_tool.get("name", "Action")
                                    send_push_safe(
                                        category="pending_action",
                                        title="Velora braucht dein OK",
                                        body=summary[:160] or f"{tool_label} wartet auf Bestätigung",
                                        url=f"/chat?thread={thread_id}",
                                        tag=f"confirm-{action_info['action_id']}",
                                        data={"action_id": action_info["action_id"], "tool": tool_label},
                                    )
                                except Exception:
                                    logger.exception("Push für pending_action fehlgeschlagen")
                elif ev.type == "done":
                    final_session_id = ev.data.get("session_id")
                    yield _sse("done", ev.data)
                elif ev.type == "error":
                    had_error = True
                    yield _sse("error", ev.data)
                elif ev.type == "raw":
                    logger.debug("raw stream event: %s", str(ev.data)[:300])

        except Exception as e:
            logger.exception("Fehler im Chat-Stream")
            had_error = True
            yield _sse("error", {"message": str(e)})

        # Assistant-Message persistieren
        full_text = "".join(assistant_text_parts).strip()
        if full_text:
            db.add_message(thread_id, "assistant", full_text)

        # Session-ID auf dem Thread speichern (für spätere --resume)
        if final_session_id and final_session_id != thread.get("session_id"):
            db.set_thread_session(thread_id, final_session_id)

        if had_error and not full_text:
            yield _sse("fatal", {"message": "Chat fehlgeschlagen — siehe Logs"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # für Reverse-Proxies: kein Buffering
            "Connection": "keep-alive",
        },
    )
