"""Slash command handlers for the TUI.

Commands are dispatched by the main app. Each handler receives the
TUIApp instance and the raw argument string, and returns a string
result (or None for side-effect-only commands).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui.app import TUIApp

from core import fleet
from core.config import PROJECT_ROOT

# Health endpoint ports
AGENT_PORTS = fleet.AGENT_PORTS

# All agents and blob workers
ALL_AGENTS = fleet.FLEET_AGENTS
BLOB_AGENTS = ["blobw1", "blobw2", "blobw3"]
MANAGER_AGENTS = ["supa", "koe", "mave", "forge"]


def _http_get(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ── Command: /help ──────────────────────────────────────────────

def cmd_help(app: "TUIApp", args: str) -> str:
    return (
        "── Commands ──────────────────────────────────────\n"
        "  /new [name]       Create new session (optional name)\n"
        "  /sessions         List all sessions\n"
        "  /switch <id>      Switch to a session by ID\n"
        "  /status           Show fleet agent status\n"
        "  /awake <agent>    Start an agent (e.g. koe, supa)\n"
        "  /kill <agent>     Stop an agent (or 'all', 'blobs')\n"
        "  /restart <agent>  Restart an agent\n"
        "  /context          Show current session context\n"
        "  /history          Show full message history\n"
        "  /chats            List Band chatrooms\n"
        "  /clear            Clear screen\n"
        "  /help             Show this help\n"
        "  /quit             Exit TUI\n"
        "──────────────────────────────────────────────────"
    )


# ── Command: /new ───────────────────────────────────────────────

def cmd_new(app: "TUIApp", args: str) -> str:
    name = args.strip() or f"session-{datetime.now():H%M%S}"
    session_id = f"s-{datetime.now():%Y%m%d-%H%M%S}"

    # Create DB session (no Band chatroom needed — direct HTTP chat)
    app.db.create_session(session_id, name, "")
    app.current_session = session_id

    return f"New session: {name} (id={session_id})"


# ── Command: /sessions ──────────────────────────────────────────

def cmd_sessions(app: "TUIApp", args: str) -> str:
    sessions = app.db.list_sessions()
    if not sessions:
        return "No sessions found."

    lines = ["── Sessions ─────────────────────────────────────"]
    for s in sessions:
        marker = " >" if s["id"] == app.current_session else "  "
        msg_count = s.get("msg_count", 0)
        last = s.get("last_active", "")[:19]
        lines.append(f"{marker} {s['id']}  {s['name']:20s}  {msg_count:3d} msgs  {last}")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Command: /switch ────────────────────────────────────────────

def cmd_switch(app: "TUIApp", args: str) -> str:
    session_id = args.strip()
    if not session_id:
        return "Usage: /switch <session-id>"

    session = app.db.get_session(session_id)
    if not session:
        return f"Session not found: {session_id}"

    app.current_session = session_id

    msg_count = app.db.get_message_count(session_id)
    return f"Switched to: {session['name']} (id={session_id}, {msg_count} messages)"


# ── Command: /status ────────────────────────────────────────────

def cmd_status(app: "TUIApp", args: str) -> str:
    status = fleet.list_agent_status()
    lines = ["── Fleet Status ──────────────────────────────────"]
    for name, info in status.items():
        if info["running"]:
            health = info.get("health") or {}
            cycles = health.get("cycles", "?")
            msgs = health.get("messages_processed", "?")
            uptime = health.get("uptime_seconds", "?")
            pid = info["pid"]
            lines.append(
                f"  ● {name:8s} PID {str(pid):>6s} | cycles={cycles} msgs={msgs} up={uptime}s"
            )
        else:
            marker = "stale" if info.get("stale_removed") else "offline"
            lines.append(f"  ○ {name:8s} {marker}")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Command: /awake ─────────────────────────────────────────────

def cmd_awake(app: "TUIApp", args: str) -> str:
    name = args.strip().lower()
    if not name:
        return "Usage: /awake <agent-name> (e.g. koe, supa, blobw1)"

    if name not in ALL_AGENTS:
        return f"Unknown agent: {name}. Valid: {', '.join(ALL_AGENTS)}"

    result = fleet.launch_agent(name)
    if not result["ok"]:
        return f"Failed to start {name}: {result.get('error', 'unknown')}"
    if result.get("started"):
        return f"Started {name} — PID {result['pid']}"
    return f"{name} already running — PID {result['pid']}"


# ── Command: /kill ──────────────────────────────────────────────

def cmd_kill(app: "TUIApp", args: str) -> str:
    name = args.strip().lower()
    if not name:
        return "Usage: /kill <agent-name|all|blobs>"

    if name == "blobs":
        results = []
        for b in BLOB_AGENTS:
            r = fleet.kill_agent(b)
            results.append(f"{b}: {'stopped' if r['ok'] else r.get('error', 'failed')}")
        return "\n".join(results)

    if name == "all":
        results = []
        for a in ALL_AGENTS:
            r = fleet.kill_agent(a)
            status = "stopped" if r["ok"] else r.get("error", "not running")
            results.append(f"{a}: {status}")
        return "\n".join(results)

    if name not in ALL_AGENTS:
        return f"Unknown agent: {name}. Valid: {', '.join(ALL_AGENTS)} or 'all'/'blobs'"

    result = fleet.kill_agent(name)
    if not result["ok"]:
        return f"Failed to stop {name}: {result.get('error', 'unknown')}"
    killed = ", ".join(result.get("killed", []))
    return f"Stopped {name} ({killed})"


# ── Command: /restart ───────────────────────────────────────────

def cmd_restart(app: "TUIApp", args: str) -> str:
    name = args.strip().lower()
    if not name:
        return "Usage: /restart <agent-name>"

    if name not in ALL_AGENTS:
        return f"Unknown agent: {name}. Valid: {', '.join(ALL_AGENTS)}"

    result = fleet.restart_agent(name)
    kill_ok = result["kill"]["ok"]
    launch_ok = result["launch"]["ok"]
    if not launch_ok:
        return f"Restart {name} failed: kill={kill_ok}, launch error={result['launch'].get('error')}"
    return f"Restarted {name} — PID {result['launch']['pid']}"


# ── Command: /context ───────────────────────────────────────────

def cmd_context(app: "TUIApp", args: str) -> str:
    if not app.current_session:
        return "No active session."

    context = app.db.get_context(app.current_session, max_messages=10)
    if not context:
        return "No context yet — session is empty."
    return context


# ── Command: /history ───────────────────────────────────────────

def cmd_history(app: "TUIApp", args: str) -> str:
    if not app.current_session:
        return "No active session."

    msgs = app.db.get_messages(app.current_session, limit=200)
    if not msgs:
        return "No messages in this session."

    lines = [f"── History ({len(msgs)} messages) ────────────────"]
    for m in msgs:
        ts = m.get("timestamp", "")[:19]
        role = m["role"].upper()
        content = m["content"]
        # Truncate very long messages for display
        if len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"[{ts}] {role}: {content}")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Command: /chats ─────────────────────────────────────────────

def cmd_chats(app: "TUIApp", args: str) -> str:
    """List Band chatrooms (agent-to-agent rooms, not user sessions)."""
    try:
        from tui.band_interface import BandInterface
        band = BandInterface()
        chats = band.list_chats()
    except Exception as e:
        return f"Cannot connect to Band: {e}"

    if not chats:
        return "No chatrooms found."

    lines = ["── Band Chatrooms (agent-to-agent) ────────────────"]
    for c in chats[:20]:
        lines.append(f"  {c['id'][:12]}  {c['title']}")
    if len(chats) > 20:
        lines.append(f"  ... ({len(chats) - 20} more)")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Command: /clear ─────────────────────────────────────────────

def cmd_clear(app: "TUIApp", args: str) -> str:
    # Signal to the app to clear the screen
    app._clear_screen = True
    return ""


# ── Command: /quit ──────────────────────────────────────────────

def cmd_quit(app: "TUIApp", args: str) -> str:
    app._running = False
    return "Goodbye."


# ── Command Registry ────────────────────────────────────────────

COMMANDS = {
    "help": cmd_help,
    "h": cmd_help,
    "new": cmd_new,
    "sessions": cmd_sessions,
    "ls": cmd_sessions,
    "switch": cmd_switch,
    "status": cmd_status,
    "awake": cmd_awake,
    "kill": cmd_kill,
    "restart": cmd_restart,
    "context": cmd_context,
    "history": cmd_history,
    "chats": cmd_chats,
    "clear": cmd_clear,
    "quit": cmd_quit,
    "q": cmd_quit,
    "exit": cmd_quit,
}
