"""SQLite-Persistenz für Web-Chat: Threads, Messages, Pinned-Memories."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent.parent / "memory" / "chat.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    session_id TEXT,
    message_count INTEGER DEFAULT 0,
    is_pinned INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_name TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pinned_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    pinned_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    thread_id TEXT,
    tool_name TEXT NOT NULL,
    params TEXT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    last_used TEXT,
    active INTEGER DEFAULT 1
);

-- iOS-App: APNs-Gerätetokens (environment: production = TestFlight/App Store, sandbox = Xcode-Build)
CREATE TABLE IF NOT EXISTS apns_devices (
    token TEXT PRIMARY KEY,
    environment TEXT NOT NULL DEFAULT 'production',
    device_name TEXT,
    app_version TEXT,
    created_at TEXT NOT NULL,
    last_used TEXT,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    category TEXT PRIMARY KEY,
    telegram_enabled INTEGER DEFAULT 1,
    push_enabled INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pinned_thread ON pinned_memories(thread_id);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status, created_at);
CREATE INDEX IF NOT EXISTS idx_push_active ON push_subscriptions(active);
"""

# Default-Kategorien für neue Installationen / neue Kategorien nach Update.
DEFAULT_NOTIFICATION_CATEGORIES = [
    "briefings",         # Mo/Do-Briefings + Monthly Report
    "trade_confirmed",   # Trade erfolgreich geloggt
    "pending_action",    # Velora hat Write-Action vorbereitet und braucht OK
    "recommendation_closed",  # Empfehlung wurde automatisch/manuell geschlossen
    "market_alert",      # starke Marktbewegung, VIX-Spike etc.
    "chat_reply",        # Velora-Antwort fertig, während die App nicht offen war
    "system_error",      # Briefing/Report fehlgeschlagen, Claude-Login defekt
]

# Kategorien, die beim ersten Anlegen NICHT per Telegram gehen: Chat-Antworten
# gab es dort nie, Systemfehler gehen nur als Notnagel hin, wenn kein Push ankam.
_TELEGRAM_OFF_BY_DEFAULT = {"chat_reply", "system_error"}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        # Seed Default-Kategorien (idempotent)
        now = _now()
        for cat in DEFAULT_NOTIFICATION_CATEGORIES:
            conn.execute(
                """INSERT OR IGNORE INTO notification_preferences
                   (category, telegram_enabled, push_enabled, updated_at) VALUES (?, ?, 1, ?)""",
                (cat, 0 if cat in _TELEGRAM_OFF_BY_DEFAULT else 1, now),
            )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Threads ───────────────────────────────────────────────────

def create_thread(title: str = "Neuer Chat") -> dict:
    thread_id = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (thread_id, title, now, now),
        )
    return {"id": thread_id, "title": title, "created_at": now, "updated_at": now,
            "session_id": None, "message_count": 0, "is_pinned": 0, "summary": None}


def get_thread(thread_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    return dict(row) if row else None


def list_threads(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM threads ORDER BY is_pinned DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_thread(thread_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE threads SET {cols} WHERE id = ?", (*fields.values(), thread_id))


def delete_thread(thread_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))


def set_thread_session(thread_id: str, session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE threads SET session_id = ?, updated_at = ? WHERE id = ?",
            (session_id, _now(), thread_id),
        )


# ── Messages ──────────────────────────────────────────────────

def add_message(
    thread_id: str,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
) -> int:
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages (thread_id, role, content, tool_name, tokens_in, tokens_out, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (thread_id, role, content, tool_name, tokens_in, tokens_out, now),
        )
        conn.execute(
            "UPDATE threads SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        return cur.lastrowid


def get_messages(thread_id: str, limit: int = 500) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_user_assistant_messages(thread_id: str, limit: int = 20) -> list[dict]:
    """Nur 'user' und 'assistant' Rollen — für Prompt-History ohne Tool-Noise."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM messages WHERE thread_id = ? AND role IN ('user','assistant')
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (thread_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── Pinned Memories ──────────────────────────────────────────

def add_pinned_memory(key: str, value: str, thread_id: Optional[str] = None, pinned_by: str = "user") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO pinned_memories (thread_id, key, value, pinned_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, key, value, pinned_by, _now()),
        )
        return cur.lastrowid


def get_pinned_memories(thread_id: Optional[str] = None, include_global: bool = True) -> list[dict]:
    with _connect() as conn:
        if thread_id and include_global:
            rows = conn.execute(
                "SELECT * FROM pinned_memories WHERE thread_id = ? OR thread_id IS NULL ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()
        elif thread_id:
            rows = conn.execute(
                "SELECT * FROM pinned_memories WHERE thread_id = ? ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pinned_memories WHERE thread_id IS NULL ORDER BY created_at ASC"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_pinned_memory(memory_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM pinned_memories WHERE id = ?", (memory_id,))


# ── Pending Actions (für Write-Tool-Confirmation) ───────────

def create_pending_action(tool_name: str, params: dict, summary: str, thread_id: Optional[str] = None) -> str:
    action_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pending_actions (id, thread_id, tool_name, params, summary, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (action_id, thread_id, tool_name, json.dumps(params, ensure_ascii=False), summary, _now()),
        )
    return action_id


def get_pending_action(action_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["params"] = json.loads(d["params"])
    except Exception:
        pass
    return d


def resolve_pending_action(action_id: str, status: str, result: Optional[dict] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = ?, resolved_at = ?, result = ? WHERE id = ?",
            (status, _now(), json.dumps(result, ensure_ascii=False) if result else None, action_id),
        )


def list_pending_actions(thread_id: Optional[str] = None, status: str = "pending") -> list[dict]:
    with _connect() as conn:
        if thread_id:
            rows = conn.execute(
                "SELECT * FROM pending_actions WHERE thread_id = ? AND status = ? ORDER BY created_at DESC",
                (thread_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pending_actions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d["params"])
        except Exception:
            pass
        out.append(d)
    return out


# ── Push Subscriptions ───────────────────────────────────────

def upsert_push_subscription(endpoint: str, p256dh: str, auth: str, user_agent: Optional[str] = None) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, created_at, last_used, active)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(endpoint) DO UPDATE SET
                 p256dh = excluded.p256dh,
                 auth = excluded.auth,
                 user_agent = excluded.user_agent,
                 last_used = excluded.last_used,
                 active = 1""",
            (endpoint, p256dh, auth, user_agent, now, now),
        )


def deactivate_push_subscription(endpoint: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE push_subscriptions SET active = 0 WHERE endpoint = ?", (endpoint,))


def get_active_push_subscriptions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def touch_push_subscription(endpoint: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE push_subscriptions SET last_used = ? WHERE endpoint = ?",
            (_now(), endpoint),
        )


# ── APNs-Geräte (iOS-App) ────────────────────────────────────

def upsert_apns_device(token: str, environment: str, device_name: Optional[str] = None,
                       app_version: Optional[str] = None) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO apns_devices (token, environment, device_name, app_version, created_at, last_used, active)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(token) DO UPDATE SET
                 environment = excluded.environment,
                 device_name = excluded.device_name,
                 app_version = excluded.app_version,
                 last_used = excluded.last_used,
                 active = 1""",
            (token, environment, device_name, app_version, now, now),
        )


def deactivate_apns_device(token: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE apns_devices SET active = 0 WHERE token = ?", (token,))


def get_active_apns_devices() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT token, environment, device_name FROM apns_devices WHERE active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def touch_apns_device(token: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE apns_devices SET last_used = ? WHERE token = ?", (_now(), token))


# ── Notification Preferences ─────────────────────────────────

def get_notification_preferences() -> dict[str, dict]:
    """Liefert {category: {telegram_enabled, push_enabled}} — alle Kategorien."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT category, telegram_enabled, push_enabled FROM notification_preferences"
        ).fetchall()
    return {
        r["category"]: {
            "telegram_enabled": bool(r["telegram_enabled"]),
            "push_enabled": bool(r["push_enabled"]),
        }
        for r in rows
    }


def set_notification_preference(category: str, telegram_enabled: bool, push_enabled: bool) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO notification_preferences (category, telegram_enabled, push_enabled, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(category) DO UPDATE SET
                 telegram_enabled = excluded.telegram_enabled,
                 push_enabled = excluded.push_enabled,
                 updated_at = excluded.updated_at""",
            (category, 1 if telegram_enabled else 0, 1 if push_enabled else 0, _now()),
        )


def is_channel_enabled(category: str, channel: str) -> bool:
    """channel: 'telegram' | 'push'.  Unbekannte Kategorie → True (fail-open)."""
    col = "telegram_enabled" if channel == "telegram" else "push_enabled"
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {col} FROM notification_preferences WHERE category = ?",
            (category,),
        ).fetchone()
    if row is None:
        return True
    return bool(row[0])
