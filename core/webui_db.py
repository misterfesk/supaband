"""WebUI database — project tracking, production items, todos, task updates.

SQLite-backed (WAL mode for concurrent access from agents + web server).

Tables:
  projects         — project-level tracking
  production_items — agent-produced final deliverables (Production section)
  todos            — task approval queue (Todo section)
  task_updates     — real-time updates from Supa (SSE feed)
  agent_activity   — agent action log (dashboard + profiles)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "webui.db"

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
    """Create all tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            status      TEXT DEFAULT 'active',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS production_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  TEXT NOT NULL,
            agent_name  TEXT NOT NULL,
            item_type   TEXT NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            metadata    TEXT DEFAULT '{}',
            status      TEXT DEFAULT 'published',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS todos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  TEXT NOT NULL,
            agent_name  TEXT NOT NULL,
            task        TEXT NOT NULL,
            priority    TEXT DEFAULT 'normal',
            status      TEXT DEFAULT 'pending',
            resolution_note TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS task_updates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  TEXT,
            session_id  TEXT,
            update_type TEXT NOT NULL,
            content     TEXT NOT NULL,
            agent_name  TEXT DEFAULT 'supa',
            delivered   INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_activity (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name  TEXT NOT NULL,
            action      TEXT NOT NULL,
            detail      TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_prod_project ON production_items(project_id);
        CREATE INDEX IF NOT EXISTS idx_prod_agent ON production_items(agent_name);
        CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project_id);
        CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
        CREATE INDEX IF NOT EXISTS idx_updates_session ON task_updates(session_id);
        CREATE INDEX IF NOT EXISTS idx_updates_delivered ON task_updates(delivered);
        CREATE INDEX IF NOT EXISTS idx_activity_agent ON agent_activity(agent_name);
    """)
    conn.commit()


class WebUIDB:
    """High-level interface for WebUI data."""

    # Default project ID for the demo
    DEMO_PROJECT_ID = "proj-demo-001"

    def __init__(self):
        init_db()

    # ── Projects ───────────────────────────────────────────────

    def create_project(self, name: str, description: str = "",
                       project_id: str = "") -> dict:
        pid = project_id or f"proj-{datetime.now():%Y%m%d-%H%M%S}"
        now = datetime.now().isoformat()
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO projects (id, name, description, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (pid, name, description, now),
        )
        conn.commit()
        return {"id": pid, "name": name, "description": description}

    def list_projects(self) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM projects WHERE status='active' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_project(self, project_id: str) -> Optional[dict]:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_project_stats(self, project_id: str) -> dict:
        """Aggregated dashboard stats for a project."""
        conn = _get_conn()
        prod_count = conn.execute(
            "SELECT COUNT(*) as n FROM production_items WHERE project_id=?",
            (project_id,)
        ).fetchone()["n"]
        todo_pending = conn.execute(
            "SELECT COUNT(*) as n FROM todos WHERE project_id=? AND status='pending'",
            (project_id,)
        ).fetchone()["n"]
        todo_approved = conn.execute(
            "SELECT COUNT(*) as n FROM todos WHERE project_id=? AND status='approved'",
            (project_id,)
        ).fetchone()["n"]
        updates_count = conn.execute(
            "SELECT COUNT(*) as n FROM task_updates WHERE project_id=?",
            (project_id,)
        ).fetchone()["n"]
        recent_activity = conn.execute(
            "SELECT * FROM agent_activity ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        return {
            "production_count": prod_count,
            "todo_pending": todo_pending,
            "todo_approved": todo_approved,
            "updates_count": updates_count,
            "recent_activity": [dict(r) for r in recent_activity],
        }

    # ── Production Items ───────────────────────────────────────

    def add_production(self, agent_name: str, item_type: str, title: str,
                       content: str, metadata: str = "{}",
                       project_id: str = "") -> dict:
        pid = project_id or self.DEMO_PROJECT_ID
        now = datetime.now().isoformat()
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO production_items (project_id, agent_name, item_type, "
            "title, content, metadata, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'published', ?)",
            (pid, agent_name, item_type, title, content, metadata, now),
        )
        conn.commit()
        item_id = cur.lastrowid
        # Log activity
        self.log_activity(agent_name, "produced", f"{item_type}: {title}")
        return {"ok": True, "id": item_id, "title": title}

    def list_production(self, project_id: str = "",
                        agent_name: str = "",
                        item_type: str = "",
                        limit: int = 50) -> list[dict]:
        conn = _get_conn()
        query = "SELECT * FROM production_items WHERE 1=1"
        params: list = []
        if project_id:
            query += " AND project_id=?"
            params.append(project_id)
        if agent_name:
            query += " AND agent_name=?"
            params.append(agent_name)
        if item_type:
            query += " AND item_type=?"
            params.append(item_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_production(self, item_id: int) -> Optional[dict]:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM production_items WHERE id=?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── Todos ──────────────────────────────────────────────────

    def add_todo(self, agent_name: str, task: str, priority: str = "normal",
                 project_id: str = "") -> dict:
        pid = project_id or self.DEMO_PROJECT_ID
        now = datetime.now().isoformat()
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO todos (project_id, agent_name, task, priority, status, "
            "created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (pid, agent_name, task, priority, now),
        )
        conn.commit()
        todo_id = cur.lastrowid
        self.log_activity(agent_name, "todo_created", task[:100])
        return {"ok": True, "id": todo_id, "task": task}

    def list_todos(self, status: str = "", project_id: str = "",
                   limit: int = 50) -> list[dict]:
        conn = _get_conn()
        query = "SELECT * FROM todos WHERE 1=1"
        params: list = []
        if status:
            query += " AND status=?"
            params.append(status)
        if project_id:
            query += " AND project_id=?"
            params.append(project_id)
        query += " ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
        query += "WHEN 'normal' THEN 2 ELSE 3 END, created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def resolve_todo(self, todo_id: int, status: str,
                     resolution_note: str = "") -> dict:
        """Approve or reject a todo. status='approved' or 'rejected'."""
        now = datetime.now().isoformat()
        conn = _get_conn()
        conn.execute(
            "UPDATE todos SET status=?, resolution_note=?, resolved_at=? WHERE id=?",
            (status, resolution_note, now, todo_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        if row:
            self.log_activity(row["agent_name"], f"todo_{status}",
                              row["task"][:100])
        return {"ok": True, "id": todo_id, "status": status}

    # ── Task Updates (SSE feed) ────────────────────────────────

    def add_update(self, update_type: str, content: str,
                   agent_name: str = "supa", session_id: str = "",
                   project_id: str = "") -> dict:
        pid = project_id or self.DEMO_PROJECT_ID
        now = datetime.now().isoformat()
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO task_updates (project_id, session_id, update_type, "
            "content, agent_name, delivered, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (pid, session_id, update_type, content, agent_name, now),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "update_type": update_type}

    def get_updates_since(self, session_id: str, last_id: int = 0,
                          limit: int = 50) -> list[dict]:
        """Get task updates newer than last_id. For SSE polling.
        Includes global updates (empty session_id) + session-specific ones."""
        conn = _get_conn()
        if session_id:
            rows = conn.execute(
                "SELECT * FROM task_updates WHERE id > ? "
                "AND (session_id=? OR session_id='' OR session_id IS NULL) "
                "ORDER BY id ASC LIMIT ?",
                (last_id, session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_updates WHERE id > ? "
                "ORDER BY id ASC LIMIT ?",
                (last_id, limit)
            ).fetchall()
        # Mark as delivered
        for r in rows:
            conn.execute(
                "UPDATE task_updates SET delivered=1 WHERE id=?", (r["id"],)
            )
        conn.commit()
        return [dict(r) for r in rows]

    def get_updates(self, session_id: str = "", limit: int = 50) -> list[dict]:
        """Get recent task updates (for history view)."""
        conn = _get_conn()
        if session_id:
            rows = conn.execute(
                "SELECT * FROM task_updates WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_updates ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Agent Activity ─────────────────────────────────────────

    def log_activity(self, agent_name: str, action: str,
                     detail: str = "") -> dict:
        now = datetime.now().isoformat()
        conn = _get_conn()
        conn.execute(
            "INSERT INTO agent_activity (agent_name, action, detail, created_at) "
            "VALUES (?, ?, ?, ?)",
            (agent_name, action, detail, now),
        )
        conn.commit()
        return {"ok": True}

    def get_agent_activity(self, agent_name: str, limit: int = 20) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_activity WHERE agent_name=? "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_name, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_activity(self, limit: int = 50) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_activity ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Delete Operations (Supa-only) ─────────────────────────

    def delete_production(self, item_id: int) -> dict:
        """Delete a production item by ID."""
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM production_items WHERE id=?", (item_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Production item {item_id} not found"}
        conn.execute("DELETE FROM production_items WHERE id=?", (item_id,))
        conn.commit()
        self.log_activity("supa", "production_deleted", f"Deleted: {row['title']}")
        return {"ok": True, "id": item_id, "title": row["title"]}

    def delete_todo(self, todo_id: int) -> dict:
        """Delete a todo by ID (regardless of status)."""
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM todos WHERE id=?", (todo_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Todo {todo_id} not found"}
        conn.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        conn.commit()
        self.log_activity("supa", "todo_deleted", f"Deleted: {row['task'][:100]}")
        return {"ok": True, "id": todo_id, "task": row["task"]}

    def find_production(self, title_query: str = "", agent_name: str = "",
                        item_type: str = "", limit: int = 20) -> list[dict]:
        """Search production items by title, agent, or type."""
        conn = _get_conn()
        query = "SELECT * FROM production_items WHERE 1=1"
        params: list = []
        if title_query:
            query += " AND title LIKE ?"
            params.append(f"%{title_query}%")
        if agent_name:
            query += " AND agent_name=?"
            params.append(agent_name)
        if item_type:
            query += " AND item_type=?"
            params.append(item_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── Demo Data ──────────────────────────────────────────────

    def init_demo_data(self):
        """Seed the demo project if it doesn't exist."""
        conn = _get_conn()
        existing = conn.execute(
            "SELECT id FROM projects WHERE id=?", (self.DEMO_PROJECT_ID,)
        ).fetchone()
        if not existing:
            self.create_project(
                name="Supaband Demo",
                description="AI-powered multi-agent organization — marketing, research, and operations working together through Band.",
                project_id=self.DEMO_PROJECT_ID,
            )


# ── Singleton ────────────────────────────────────────────────────

_wdb: WebUIDB | None = None


def get_webui_db() -> WebUIDB:
    global _wdb
    if _wdb is None:
        _wdb = WebUIDB()
    return _wdb
