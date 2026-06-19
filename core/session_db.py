"""Session database — SQLite-backed chat session management for the TUI.

Each session maps 1:1 to a Band chatroom. Messages are stored per-session
so Supa can receive context from prior messages in the same session.

Schema:
  sessions  — id, name, band_chat_id, created_at, last_active
  messages  — id, session_id, role, content, timestamp, band_msg_id
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "sessions.db"

# Thread-local connection — SQLite needs per-thread connections
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL DEFAULT 'default',
            band_chat_id TEXT,
            created_at  TEXT NOT NULL,
            last_active TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,          -- 'user', 'supa', 'system'
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            band_msg_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);
    """)
    conn.commit()


class SessionDB:
    """High-level interface for session and message management."""

    def __init__(self):
        init_db()

    # ── Sessions ────────────────────────────────────────────────

    def create_session(self, session_id: str, name: str = "default",
                       band_chat_id: str = "") -> dict:
        """Create a new session record."""
        now = datetime.now().isoformat()
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (id, name, band_chat_id, created_at, last_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, name, band_chat_id, now, now),
        )
        conn.commit()
        return {"id": session_id, "name": name, "band_chat_id": band_chat_id}

    def get_session(self, session_id: str) -> Optional[dict]:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS msg_count "
            "FROM sessions s ORDER BY s.last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id: str, **fields):
        """Update session fields (e.g. band_chat_id, name)."""
        allowed = {"name", "band_chat_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [datetime.now().isoformat(), session_id]
        conn = _get_conn()
        conn.execute(
            f"UPDATE sessions SET {sets}, last_active = ? WHERE id = ?",
            vals,
        )
        conn.commit()

    def touch_session(self, session_id: str):
        """Update last_active timestamp."""
        conn = _get_conn()
        conn.execute(
            "UPDATE sessions SET last_active = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id),
        )
        conn.commit()

    def delete_session(self, session_id: str):
        conn = _get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

    # ── Messages ────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str,
                    band_msg_id: str = "") -> int:
        """Insert a message. Returns the message row ID."""
        now = datetime.now().isoformat()
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp, band_msg_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, now, band_msg_id),
        )
        conn.commit()
        self.touch_session(session_id)
        return cur.lastrowid

    def get_messages(self, session_id: str, limit: int = 100,
                     offset: int = 0) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? "
            "ORDER BY id ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_context(self, session_id: str, max_messages: int = 10) -> str:
        """Return a formatted context string of the last N messages.
        This is injected into messages sent to Supa so it has prior context."""
        msgs = self.get_messages(session_id, limit=max_messages)
        # Take the last max_messages
        msgs = msgs[-max_messages:] if len(msgs) > max_messages else msgs
        if not msgs:
            return ""
        lines = ["[Previous conversation context]"]
        for m in msgs:
            role = m["role"].capitalize()
            # Truncate long messages in context
            content = m["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"{role}: {content}")
        lines.append("[End of context]")
        return "\n".join(lines)

    def get_last_band_msg_id(self, session_id: str) -> Optional[str]:
        """Get the band_msg_id of the last Supa message (for polling dedup)."""
        conn = _get_conn()
        row = conn.execute(
            "SELECT band_msg_id FROM messages "
            "WHERE session_id = ? AND role = 'supa' AND band_msg_id != '' "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return row["band_msg_id"] if row else None

    def get_message_count(self, session_id: str) -> int:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as n FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["n"]) if row else 0
