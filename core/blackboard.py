"""Blackboard — shared file exchange and knowledge base for all agents.

Provides a structured way for agents to:
  - Post files/documents for other agents to read (cross-department sharing)
  - Retrieve files posted by others
  - List and search shared resources
  - Track which agent posted what and when

Backed by SQLite for durability + a filesystem mirror for easy access.

Usage from tools:
  from core.blackboard import Blackboard
  bb = Blackboard()
  bb.post("campaign-brief", "Q3 Campaign Brief", "marketing", content="...")
  doc = bb.retrieve("campaign-brief")
  docs = bb.list_by_department("marketing")
  results = bb.search("coffee market")
"""

from __future__ import annotations

import sqlite3
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "blackboard.db"
FILES_DIR = PROJECT_ROOT / "data" / "blackboard_files"
FILES_DIR.mkdir(parents=True, exist_ok=True)


class Blackboard:
    """Shared knowledge base — SQLite-backed with filesystem mirror."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    department TEXT NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    file_path TEXT,
                    is_pinned INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS file_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    department TEXT NOT NULL,
                    author TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_type TEXT,
                    size_bytes INTEGER,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_docs_dept ON documents(department)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_docs_key ON documents(key)")
            c.commit()

    def post(self, key: str, title: str, department: str, author: str,
             content: str, tags: str = "") -> dict[str, Any]:
        """Post or update a document on the blackboard."""
        key = self._slug(key)
        now = datetime.now().isoformat()
        with self._conn() as c:
            existing = c.execute("SELECT id FROM documents WHERE key=?", (key,)).fetchone()
            if existing:
                c.execute("""
                    UPDATE documents SET title=?, department=?, author=?,
                        content=?, tags=?, updated_at=?
                    WHERE key=?
                """, (title, department, author, content, tags, now, key))
            else:
                c.execute("""
                    INSERT INTO documents (key, title, department, author, content, tags,
                        created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (key, title, department, author, content, tags, now, now))
            c.commit()
        return {"ok": True, "key": key, "title": title, "action": "updated" if existing else "created"}

    def retrieve(self, key: str) -> dict[str, Any]:
        """Retrieve a document by key."""
        key = self._slug(key)
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE key=?", (key,)).fetchone()
            if not row:
                return {"ok": False, "error": f"Document '{key}' not found"}
            return {"ok": True, "doc": dict(row)}

    def list_all(self, department: str = "", limit: int = 50) -> list[dict]:
        """List documents, optionally filtered by department."""
        with self._conn() as c:
            if department:
                rows = c.execute(
                    "SELECT key, title, department, author, updated_at, tags, is_pinned "
                    "FROM documents WHERE department=? ORDER BY is_pinned DESC, updated_at DESC LIMIT ?",
                    (department, limit)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT key, title, department, author, updated_at, tags, is_pinned "
                    "FROM documents ORDER BY is_pinned DESC, updated_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def list_by_department(self, department: str) -> list[dict]:
        return self.list_all(department=department)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search across all documents using LIKE patterns."""
        with self._conn() as c:
            pattern = f"%{query}%"
            rows = c.execute(
                "SELECT key, title, department, author, updated_at, "
                "substr(content, 1, 200) as excerpt "
                "FROM documents WHERE content LIKE ? OR title LIKE ? OR tags LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (pattern, pattern, pattern, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, key: str) -> dict[str, Any]:
        """Delete a document by key."""
        key = self._slug(key)
        with self._conn() as c:
            c.execute("DELETE FROM documents WHERE key=?", (key,))
            c.commit()
        return {"ok": True, "key": key, "action": "deleted"}

    def pin(self, key: str) -> dict[str, Any]:
        """Pin a document (pinned docs appear first in lists)."""
        key = self._slug(key)
        with self._conn() as c:
            c.execute("UPDATE documents SET is_pinned=1 WHERE key=?", (key,))
            c.commit()
        return {"ok": True, "key": key, "action": "pinned"}

    def unpin(self, key: str) -> dict[str, Any]:
        key = self._slug(key)
        with self._conn() as c:
            c.execute("UPDATE documents SET is_pinned=0 WHERE key=?", (key,))
            c.commit()
        return {"ok": True, "key": key, "action": "unpinned"}

    def index_file(self, key: str, title: str, department: str, author: str,
                   file_path: str, description: str = "") -> dict[str, Any]:
        """Index an existing file for cross-agent discovery.
        Copies the file to the blackboard files directory and records metadata."""
        key = self._slug(key)
        src = Path(file_path)
        if not src.is_absolute():
            src = PROJECT_ROOT / file_path
        if not src.exists():
            return {"ok": False, "error": f"File not found: {src}"}

        stored = FILES_DIR / f"{key}_{src.name}"
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_bytes(src.read_bytes())

        now = datetime.now().isoformat()
        file_type = src.suffix.lstrip(".")
        size = src.stat().st_size

        with self._conn() as c:
            existing = c.execute("SELECT id FROM file_index WHERE key=?", (key,)).fetchone()
            if existing:
                c.execute("""
                    UPDATE file_index SET title=?, department=?, author=?,
                        original_path=?, stored_path=?, file_type=?, size_bytes=?, description=?
                    WHERE key=?
                """, (title, department, author, str(src), str(stored), file_type, size, description, key))
            else:
                c.execute("""
                    INSERT INTO file_index (key, title, department, author, original_path,
                        stored_path, file_type, size_bytes, description, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (key, title, department, author, str(src), str(stored), file_type, size, description, now))
            c.commit()
        return {"ok": True, "key": key, "stored_path": str(stored), "size_bytes": size}

    def get_file(self, key: str) -> dict[str, Any]:
        """Retrieve a file's stored path and metadata by key."""
        key = self._slug(key)
        with self._conn() as c:
            row = c.execute("SELECT * FROM file_index WHERE key=?", (key,)).fetchone()
            if not row:
                return {"ok": False, "error": f"File '{key}' not found in index"}
            return {"ok": True, "file": dict(row)}

    def list_files(self, department: str = "") -> list[dict]:
        with self._conn() as c:
            if department:
                rows = c.execute(
                    "SELECT key, title, department, author, file_type, size_bytes, description "
                    "FROM file_index WHERE department=? ORDER BY created_at DESC",
                    (department,)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT key, title, department, author, file_type, size_bytes, description "
                    "FROM file_index ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _slug(s: str) -> str:
        return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


# ── Singleton ────────────────────────────────────────────────────────

_bb: Blackboard | None = None

def get_blackboard() -> Blackboard:
    global _bb
    if _bb is None:
        _bb = Blackboard()
    return _bb
