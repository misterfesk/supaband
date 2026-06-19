"""BaseAgent — shared polling, Band interaction, message lifecycle.

All agents (Supa, Koe, Mave, Forge, Quill, Pulse, Canvas) inherit from this.
Subclasses provide: tools, system_prompt, model tier.

Lifecycle:
  on start → write PID file, build agent, enter poll loop
  on stop  → remove PID file, graceful shutdown
  on crash → PID file lingers (cleanup handles it)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import time
import traceback
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread, Lock
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool

from core.config import load_agent_config, get_agent_entry, PROJECT_ROOT
from core import fleet

# ── Band SDK ─────────────────────────────────────────────────────────
from thenvoi_rest import RestClient
from thenvoi_rest.types.chat_message_request import ChatMessageRequest
from thenvoi_rest.types.chat_message_request_mentions_item import (
    ChatMessageRequestMentionsItem,
)
from thenvoi_rest.types.chat_room_request import ChatRoomRequest
from thenvoi_rest.types.participant_request import ParticipantRequest
from thenvoi_rest.types.chat_event_request import ChatEventRequest

# ── Sink agent (loop breaker) ────────────────────────────────────────
from core.sink_agent import get_sink_agent_id

# ── Agent UUID mapping (for @mentions + participant management) ────
# Loaded dynamically from agent_config.yaml — falls back to hardcoded values
def _load_agent_ids_from_config() -> tuple[dict[str, str], dict[str, str]]:
    """Load agent IDs and handles from agent_config.yaml."""
    ids: dict[str, str] = {}
    handles: dict[str, str] = {}
    try:
        config = load_agent_config()
        for key, entry in config.items():
            name = (entry.get("name") or key).lower().strip()
            agent_id = entry.get("agent_id", "")
            handle = entry.get("handle", "")
            if agent_id:
                ids[name] = agent_id
            if handle:
                handles[name] = handle
    except Exception:
        pass
    return ids, handles

# Initial hardcoded values (fallback if config load fails)
# ⚠️ REPLACE THESE: Run setup.sh to register agents on Band and populate agent_config.yaml
_AGENT_IDS_FALLBACK: dict[str, str] = {
    "supa": "",
    "koe": "",
    "blobw1": "",
    "blobw2": "",
    "blobw3": "",
}

_AGENT_HANDLES_FALLBACK: dict[str, str] = {
    "supa": "",
    "koe": "",
    "blobw1": "",
    "blobw2": "",
    "blobw3": "",
}

# Load from config, merge with fallbacks
_cfg_ids, _cfg_handles = _load_agent_ids_from_config()
AGENT_IDS: dict[str, str] = {**_AGENT_IDS_FALLBACK, **_cfg_ids}
AGENT_HANDLES: dict[str, str] = {**_AGENT_HANDLES_FALLBACK, **_cfg_handles}


def refresh_agent_ids():
    """Re-read agent_config.yaml and update AGENT_IDS/AGENT_HANDLES.
    Call this after creating new agents on Band."""
    global AGENT_IDS, AGENT_HANDLES
    new_ids, new_handles = _load_agent_ids_from_config()
    AGENT_IDS = {**_AGENT_IDS_FALLBACK, **new_ids}
    AGENT_HANDLES = {**_AGENT_HANDLES_FALLBACK, **new_handles}
    log.info(f"Agent IDs refreshed: {len(AGENT_IDS)} agents loaded")

# ── Void sink agent ID (loop breaker) ────────────────────────────────
# Loaded at import time; if not configured, set to empty string
try:
    VOID_AGENT_ID = get_sink_agent_id()
    AGENT_IDS["void"] = VOID_AGENT_ID
except Exception:
    VOID_AGENT_ID = ""
    log_warning = f"Void sink agent not configured — loop prevention will use self-mention fallback"

# Port mapping for HTTP health endpoints (offset from base 9100)
AGENT_PORTS: dict[str, int] = {
    "supa": 9100, "koe": 9101, "mave": 9105, "forge": 9106,
    "mave": 9105, "forge": 9106,
    # Blob workers get ports 9110–9112
    "blobw1": 9110, "blobw2": 9111, "blobw3": 9112,
}

# ── Skills System ───────────────────────────────────────────────────
def load_skill_files() -> list[dict[str, str]]:
    """Load all .md skill files from supaband/skills/ directory.
    Returns [{name, content}, ...].
    """
    skills_dir = PROJECT_ROOT / "skills"
    if not skills_dir.is_dir():
        return []
    skills = []
    for f in sorted(skills_dir.glob("*.md")):
        try:
            content = f.read_text().strip()
            name = f.stem.replace("-", " ").replace("_", " ").title()
            skills.append({"name": name, "content": content})
        except Exception:
            pass
    return skills


# ══════════════════════════════════════════════════════════════════════
# Band Context — shared mutable state for tool access
# ══════════════════════════════════════════════════════════════════════

class BandContext:
    """Single-thread safe — all LangGraph tool calls are sequential
    within one agent.invoke() call."""

    def __init__(self):
        self.chat_id: Optional[str] = None
        self.message_id: Optional[str] = None
        self.sender_id: Optional[str] = None
        self.sender_name: Optional[str] = None
        self.sender_type: Optional[str] = None
        self.band_client: Optional[RestClient] = None
        self.agent_handle: str = ""
        self.agent_name: str = ""


# ══════════════════════════════════════════════════════════════════════
# Shared Band Tools
# ══════════════════════════════════════════════════════════════════════

log = logging.getLogger("agent")


def make_shared_band_tools(ctx: BandContext) -> list:
    """Tools that every agent has: Band communication + participant management."""

    # ── Void mention cache (per chatroom) ───────────────────────
    _void_target_cache: dict[str, dict] = {}

    def _resolve_void_target() -> dict | None:
        """Find a dead-end mention target (human user) to break echo loops.
        Returns {id, name} or None if no user found."""
        if not ctx.band_client or not ctx.chat_id:
            return None
        if ctx.chat_id in _void_target_cache:
            return _void_target_cache[ctx.chat_id]
        try:
            resp = ctx.band_client.agent_api_participants.list_agent_chat_participants(
                chat_id=ctx.chat_id)
            parts = resp.data if hasattr(resp, "data") else []
            for p in (parts or []):
                ptype = str(p.type).lower() if hasattr(p, "type") else ""
                if ptype == "user":
                    entry = {"id": p.id, "name": getattr(p, "name", None) or "user"}
                    _void_target_cache[ctx.chat_id] = entry
                    return entry
        except Exception:
            pass
        # Fallback: self-mention (Band requires at least one mention, but self won't trigger loop
        # because self-echo detection in poll_and_process blocks it)
        return None

    @tool
    def band_respond(content: str, echo: bool = True) -> str:
        """Send your response to the current Band chatroom.
        Use this as your FINAL step to deliver output to whoever messaged you.

        CRITICAL — echo parameter:
        - echo=True (default): mentions the original sender so they get notified.
          Use for substantive responses, task deliverables, questions that need a reply.
        - echo=False: mentions the Void sink agent instead of the calling agent.
          Void never responds, so NO loop is created.
          Use for: acknowledgments ("okay", "done", "noted"), status updates,
          final reports, or any message that should NOT trigger a reply.

        IMPORTANT LOOP PREVENTION:
        - If your response is an acknowledgment or status update, ALWAYS use echo=False.
        - If your response is a task deliverable or question, use echo=True.
        - NEVER send a message that just says "Standing by" or "Ready" with echo=True.

        Args:
            content: Your complete response (markdown supported)
            echo: True = mention sender (triggers reply). False = mention Void (no reply).
        """
        if not ctx.band_client or not ctx.chat_id:
            return "⚠️ No active Band chatroom context — cannot respond."
        try:
            mentions = []
            if echo and ctx.sender_id:
                # Normal: mention the calling agent so they see the response
                mentions.append(ChatMessageRequestMentionsItem(
                    id=ctx.sender_id, name=ctx.sender_name or None))
            elif not echo:
                # Dead-end: mention Void sink agent (never responds → no loop)
                if VOID_AGENT_ID:
                    mentions.append(ChatMessageRequestMentionsItem(
                        id=VOID_AGENT_ID, name="void"))
                else:
                    # Fallback: try human user, then self-mention
                    void = _resolve_void_target()
                    if void:
                        mentions.append(ChatMessageRequestMentionsItem(
                            id=void["id"], name=void.get("name") or None))
                    else:
                        own_id = AGENT_IDS.get(ctx.agent_name.lower(), "")
                        if own_id:
                            mentions.append(ChatMessageRequestMentionsItem(
                                id=own_id, name=ctx.agent_name.lower()))
            # Band requires ≥1 mention — if somehow empty, mention Void or self
            if not mentions:
                if VOID_AGENT_ID:
                    mentions.append(ChatMessageRequestMentionsItem(
                        id=VOID_AGENT_ID, name="void"))
                else:
                    own_id = AGENT_IDS.get(ctx.agent_name.lower(), "")
                    if own_id:
                        mentions.append(ChatMessageRequestMentionsItem(
                            id=own_id, name=ctx.agent_name.lower()))
            msg = ChatMessageRequest(content=content, mentions=mentions)
            ctx.band_client.agent_api_messages.create_agent_chat_message(
                chat_id=ctx.chat_id, message=msg)
            return "✅ Response sent."
        except Exception as e:
            return f"❌ Send failed: {e}"

    @tool
    def band_post_event(content: str, message_type: str = "task") -> str:
        """Post an event to the current Band chatroom.

        Events do NOT require @mentions and do NOT trigger other agents.
        Use this to share status updates, tool results, or thoughts WITHOUT
        creating a conversation loop.

        Event types:
        - "task": Task status or progress update (DEFAULT)
        - "thought": Your internal reasoning or thinking process
        - "tool_call": You are calling a tool (content = tool description)
        - "tool_result": Result from a tool execution
        - "error": Error messages and failure notifications

        USE EVENTS WHEN:
        - Posting a status update ("Researching...", "Blob test started")
        - Sharing tool results that don't need a reply
        - Recording what you're doing without triggering other agents
        - Final completion notice ("Task complete — report delivered above")

        Args:
            content: Human-readable event content
            message_type: One of: task, thought, tool_call, tool_result, error
        """
        if not ctx.band_client or not ctx.chat_id:
            return "⚠️ No active Band chatroom context — cannot post event."
        try:
            event = ChatEventRequest(content=content, message_type=message_type)
            ctx.band_client.agent_api_events.create_agent_chat_event(
                chat_id=ctx.chat_id, event=event)
            return f"✅ Event posted ({message_type})."
        except Exception as e:
            return f"❌ Event failed: {e}"

    @tool
    def band_send_message(chat_id: str, content: str,
                          mention_names: str = "") -> str:
        """Send a message to ANY Band chatroom, with @mentions.
        Use this to delegate tasks to other agents.

        Args:
            chat_id: The Band chatroom UUID
            content: Message content (task description, instructions, etc.)
            mention_names: Comma-separated agent NAMES (e.g. "koe,mave")
        """
        if not ctx.band_client:
            return "⚠️ No Band client."
        try:
            mentions = []
            if mention_names:
                for name in mention_names.split(","):
                    name = name.strip().lower()
                    agent_id = AGENT_IDS.get(name)
                    if agent_id:
                        mentions.append(ChatMessageRequestMentionsItem(
                            id=agent_id, name=name))
            msg = ChatMessageRequest(content=content, mentions=mentions)
            ctx.band_client.agent_api_messages.create_agent_chat_message(
                chat_id=chat_id, message=msg)
            who = f" (@{mention_names})" if mention_names else ""
            return f"✅ Message sent to chat {chat_id[:8]}...{who}"
        except Exception as e:
            return f"❌ Send failed: {e}"

    @tool
    def band_create_chatroom(title: str = "", add_agents: str = "") -> str:
        """Create a new Band chatroom and add agents as participants.

        Use this when starting a new task that needs agent collaboration.
        Always add the needed agents as participants.

        Args:
            title: Descriptive label for your reference
            add_agents: Comma-separated agent NAMES (e.g. "koe,mave")
        Returns:
            chat_id of the new chatroom
        """
        if not ctx.band_client:
            return "⚠️ No Band client."
        try:
            req = ChatRoomRequest()
            resp = ctx.band_client.agent_api_chats.create_agent_chat(chat=req)
            chat_id = resp.data.id if hasattr(resp, "data") else str(resp)
            log.info(f"Created chatroom: {chat_id}")

            added = []
            if add_agents:
                for name in add_agents.split(","):
                    name = name.strip().lower()
                    agent_id = AGENT_IDS.get(name)
                    if agent_id:
                        try:
                            ctx.band_client.agent_api_participants.add_agent_chat_participant(
                                chat_id=chat_id,
                                participant=ParticipantRequest(participant_id=agent_id))
                            added.append(name)
                        except Exception as e:
                            log.warning(f"Failed to add {name}: {e}")

            # Always add Void sink agent to the room (for echo=False mentions)
            if VOID_AGENT_ID:
                try:
                    ctx.band_client.agent_api_participants.add_agent_chat_participant(
                        chat_id=chat_id,
                        participant=ParticipantRequest(participant_id=VOID_AGENT_ID))
                    added.append("void")
                except Exception:
                    pass  # Already in room or error — non-critical

            msg = f"✅ Chatroom created — ID: {chat_id}"
            if added:
                msg += f"\n   Participants: {', '.join(added)}"
            return msg
        except Exception as e:
            return f"❌ Chatroom creation failed: {e}"

    @tool
    def band_add_participant(chat_id: str, agent_name: str) -> str:
        """Add an agent to a Band chatroom. Required before @mentioning.

        Args:
            chat_id: The chatroom UUID
            agent_name: Agent name (supa, koe, mave, forge)
        """
        if not ctx.band_client:
            return "⚠️ No Band client."
        agent_id = AGENT_IDS.get(agent_name.lower().strip())
        if not agent_id:
            return f"❌ Unknown agent '{agent_name}'."
        try:
            ctx.band_client.agent_api_participants.add_agent_chat_participant(
                chat_id=chat_id,
                participant=ParticipantRequest(participant_id=agent_id))
            return f"✅ {agent_name} added to chat {chat_id[:8]}..."
        except Exception as e:
            return f"❌ Add failed: {e}"

    @tool
    def band_remove_participant(chat_id: str, agent_name: str) -> str:
        """Remove an agent from a Band chatroom. The agent stops receiving messages from that room.

        Use to clean up after completed tasks, leave old rooms, or remove agents
        from a blob test room after exporting results. Can remove yourself.

        Args:
            chat_id: The chatroom UUID
            agent_name: Agent name to remove (supa, koe, mave, forge, blobw1, blobw2, blobw3)
        """
        if not ctx.band_client:
            return "⚠️ No Band client."
        agent_id = AGENT_IDS.get(agent_name.lower().strip())
        if not agent_id:
            return f"❌ Unknown agent '{agent_name}'."
        try:
            ctx.band_client.agent_api_participants.remove_agent_chat_participant(
                chat_id=chat_id, id=agent_id)
            return f"✅ {agent_name} removed from chat {chat_id[:8]}..."
        except Exception as e:
            return f"❌ Remove failed: {e}"

    @tool
    def band_cleanup_chatroom(chat_id: str, remove_agents: str = "", export_first: bool = True) -> str:
        """Remove all worker/manager agents from a chatroom after a job is complete.

        This is the CHATROOM LIFECYCLE COMPLETION tool. Use it after:
        - A campaign is fully delivered
        - A research project is complete with results exported
        - A cross-department coordination task is resolved
        - A blob shadow test is finished and exported

        What it does:
        1. Optionally exports the chat transcript first (for record-keeping)
        2. Removes all specified agents from the room
        3. Leaves only human users and Void in the room

        CRITICAL: Always call this as the FINAL step of any completed task.
        An idle chatroom with agents still in it causes message loops and wasted cycles.

        Args:
            chat_id: The chatroom UUID to clean up
            remove_agents: Comma-separated agent names to remove (e.g., "quill,pulse,canvas,blobw1,blobw2,blobw3")
                           If empty, removes ALL known worker/blob agents from the room.
            export_first: Whether to export the chat transcript before cleanup (default True)

        Returns:
            Summary of what was removed
        """
        if not ctx.band_client:
            return "⚠️ No Band client."

        results = []

        # Export chat first if requested
        if export_first:
            try:
                resp = ctx.band_client.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, status="all", page_size=200)
                msgs = resp.data if hasattr(resp, "data") else []
                if msgs:
                    name = f"chat-cleanup-{datetime.now():%Y%m%d-%H%M%S}"
                    path = PROJECT_ROOT / "agents" / ctx.agent_name.lower() / "data" / "exports"
                    path.mkdir(parents=True, exist_ok=True)
                    filepath = path / f"{name}.md"
                    lines = [f"# Chat Export (Cleanup) — {chat_id}",
                             f"Exported: {datetime.now():%Y-%m-%d %H:%M:%S}",
                             f"Agent: {ctx.agent_name}\n"]
                    for m in msgs:
                        sender = m.sender_name or "unknown"
                        ts = m.inserted_at or ""
                        lines.append(f"## {sender} ({ts})")
                        lines.append(m.content or "")
                        lines.append("")
                    filepath.write_text("\n".join(lines))
                    results.append(f"📄 Exported {len(msgs)} messages → {filepath.name}")
            except Exception as e:
                results.append(f"⚠️ Export skipped: {e}")

        # Determine which agents to remove
        if remove_agents.strip():
            targets = [a.strip() for a in remove_agents.split(",") if a.strip()]
        else:
            # Default: remove all workers and blob agents
            targets = ["quill", "pulse", "canvas",
                       "blobw1", "blobw2", "blobw3"]

        removed = []
        failed = []
        for agent_name in targets:
            agent_id = AGENT_IDS.get(agent_name.lower().strip())
            if not agent_id:
                failed.append(f"{agent_name}(unknown)")
                continue
            try:
                ctx.band_client.agent_api_participants.remove_agent_chat_participant(
                    chat_id=chat_id, id=agent_id)
                removed.append(agent_name)
            except Exception as e:
                failed.append(f"{agent_name}({str(e)[:30]})")

        if removed:
            results.append(f"🚪 Removed: {', '.join(removed)}")
        if failed:
            results.append(f"⚠️ Failed: {', '.join(failed)}")

        if not removed and not failed:
            results.append("ℹ️ No agents to remove.")

        return "\n".join(results)

    @tool
    def band_list_chats() -> str:
        """List all Band chatrooms this agent can see."""
        if not ctx.band_client:
            return "⚠️ No Band client."
        try:
            resp = ctx.band_client.agent_api_chats.list_agent_chats(page_size=50)
            chats = resp.data if hasattr(resp, "data") else []
            if not chats:
                return "No chatrooms."
            lines = [f"📋 {len(chats)} chatrooms:"]
            for c in chats[:30]:
                cid = (c.id or "?")[:12]
                title = c.title or "(untitled)"
                lines.append(f"  {cid} — {title}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Failed: {e}"

    @tool
    def band_export_chat(chat_id: str, save_name: str = "") -> str:
        """Export ALL messages from a Band chatroom to a markdown file.

        Args:
            chat_id: The chatroom UUID
            save_name: Optional filename prefix
        Returns:
            Path to the saved file
        """
        if not ctx.band_client:
            return "⚠️ No Band client."
        try:
            resp = ctx.band_client.agent_api_messages.list_agent_messages(
                chat_id=chat_id, status="all", page_size=200)
            msgs = resp.data if hasattr(resp, "data") else []
            if not msgs:
                return "No messages to export."

            name = save_name or f"chat-export-{datetime.now():%Y%m%d-%H%M%S}"
            path = PROJECT_ROOT / "agents" / ctx.agent_name.lower() / "data" / "exports"
            path.mkdir(parents=True, exist_ok=True)
            filepath = path / f"{name}.md"

            lines = [f"# Band Chat Export — {chat_id}",
                     f"Exported: {datetime.now():%Y-%m-%d %H:%M:%S}",
                     f"Agent: {ctx.agent_name}\n"]
            for m in msgs:
                sender = m.sender_name or "unknown"
                ts = m.inserted_at or ""
                lines.append(f"## {sender} ({ts})")
                lines.append(m.content or "")
                lines.append("")

            filepath.write_text("\n".join(lines))
            return f"✅ Exported {len(msgs)} messages → {filepath}"
        except Exception as e:
            return f"❌ Export failed: {e}"

    @tool
    def band_get_chat_id() -> str:
        """Debug: show current chat and message IDs."""
        return f"Chat: {ctx.chat_id or 'none'}, Msg: {ctx.message_id or 'none'}"

    return [
        band_respond, band_post_event, band_send_message, band_create_chatroom,
        band_add_participant, band_remove_participant, band_cleanup_chatroom,
        band_list_chats, band_export_chat, band_get_chat_id,
    ]


# ══════════════════════════════════════════════════════════════════════
# Health HTTP Server (runs on a separate thread)
# ══════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    agent_ref: "BaseAgent" = None  # Set before starting server

    def log_message(self, format, *args):
        pass  # Silence HTTP logs

    def do_GET(self):
        if self.path == "/health":
            agent = self.agent_ref
            status = {
                "agent": agent.name,
                "handle": agent.handle,
                "model": agent.MODEL,
                "running": agent._running,
                "pid": os.getpid(),
                "cycles": agent._cycle_count,
                "messages_processed": agent._total_processed,
                "uptime_seconds": int(time.time() - agent._start_time) if agent._start_time else 0,
            }
            self._json(200, status)
        elif self.path == "/stop":
            self._json(200, {"status": "stopping"})
            Thread(target=self._delayed_stop, daemon=True).start()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        """Handle direct chat messages from TUI (bypasses Band)."""
        if self.path == "/chat":
            self._handle_chat()
        else:
            self._json(404, {"error": "not found"})

    def _handle_chat(self):
        """Process a direct chat message and return the agent's response."""
        agent = self.agent_ref
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            message = data.get("message", "")
            context = data.get("context", "")
            session_id = data.get("session_id", "direct")

            if not message.strip():
                self._json(400, {"error": "empty message"})
                return

            # Process directly through the LangGraph agent (no Band)
            response = agent.process_direct_message(
                content=message,
                context=context,
                session_id=session_id,
            )
            self._json(200, {"response": response, "status": "ok"})

        except Exception as e:
            log.error(f"Direct chat error: {e}")
            self._json(500, {"error": str(e), "status": "error"})

    def _delayed_stop(self):
        time.sleep(0.1)
        if self.agent_ref:
            self.agent_ref.stop()

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


def start_health_server(agent: "BaseAgent"):
    """Start a tiny HTTP health/stop server on agent's port."""
    port = AGENT_PORTS.get(agent.name.lower(), 0)
    if port == 0:
        return None

    HealthHandler.agent_ref = agent
    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True, name=f"health-{agent.name}")
    thread.start()
    log.info(f"Health server on http://127.0.0.1:{port}")
    return server


# ══════════════════════════════════════════════════════════════════════
# Base Agent
# ══════════════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    """Persistent polling agent. Always alive until explicitly stopped."""

    # ── Subclass overrides ────────────────────────────────────────
    CONFIG_KEY: str = ""
    MODEL: str = ""                     # Override in subclass or set SUPABAND_MODEL env var
    TEMPERATURE: float = 0.3
    POLL_INTERVAL: float = 3.0          # Seconds between poll cycles
    ERROR_BACKOFF_BASE: float = 1.0     # Exponential backoff base on errors
    ERROR_BACKOFF_MAX: float = 60.0     # Max backoff
    STALE_THRESHOLD_SEC: int = 300      # Messages older than this (5 min) are skipped

    # Flood/Loop prevention
    AGENT_LOOP_GUARD: int = 4           # Skip if last N messages are agent-only

    # Parallelism / performance
    MAX_WORKERS: int = 10               # Thread pool size for parallel API calls

    # Fleet management (override in supervisor)
    AUTO_START_MANAGERS: list[str] = [] # Agents to auto-start when this agent wakes
    WATCHDOG_INTERVAL_CYCLES: int = 10  # Check manager health every N cycles

    def __init__(self):
        load_dotenv(PROJECT_ROOT / ".env")
        config = load_agent_config()
        entry = get_agent_entry(config, self.CONFIG_KEY)

        self.name: str = entry["name"]
        self.handle: str = entry.get("handle", "")
        self.agent_id: str = entry.get("agent_id", "")
        self.api_key: str = entry.get("api_key", "")
        self.role: str = entry.get("role", "")

        if not self.api_key:
            raise ValueError(f"{self.name}: No api_key in agent_config.yaml")

        self.llm_api_key: str = os.getenv("OPENAI_API_KEY", "")
        if not self.llm_api_key:
            raise ValueError(f"{self.name}: OPENAI_API_KEY not found in .env")
        self.llm_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        # Resolve model: subclass override > SUPABAND_MODEL env var > raise error
        if not self.MODEL:
            self.MODEL = os.getenv("SUPABAND_MODEL", "")
        if not self.MODEL:
            raise ValueError(
                f"{self.name}: No model configured. Set SUPABAND_MODEL in .env "
                f"or override MODEL in the agent subclass."
            )

        # PID file
        self.pid_file: Path = PROJECT_ROOT / "agents" / self.name.lower() / "data" / "agent.pid"

        # Band REST client
        self.band = RestClient(
            api_key=self.api_key,
            base_url="https://app.band.ai",
            timeout=30.0,
        )

        # Agent directory
        self.agent_dir: Path = PROJECT_ROOT / "agents" / self.name.lower()
        self.log_dir: Path = self.agent_dir / "data" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # LangGraph state
        self._agent = None
        self._checkpointer = None
        self._thread_id: str = f"{self.name.lower()}-{datetime.now():%H%M%S}"
        self._processed_ids: set[str] = set()
        self._running: bool = False
        self._prompt_injected: bool = False

        # Statistics
        self._start_time: float = 0.0
        self._cycle_count: int = 0
        self._total_processed: int = 0
        self._error_backoff: float = 0.0

        # Fleet watchdog
        self._watchdog_running: bool = False

        # ── Flood/Loop Prevention State ──────────────────────────
        # Per-chatroom: last sender handle (to detect self-echo)
        self._last_sender: dict[str, str] = {}
        # Per-chatroom: last N sender types (to detect agent-only spirals)
        self._sender_history: dict[str, list[str]] = {}
        # Per-chatroom: last processed timestamp (cooldown)
        self._last_processed_at: dict[str, float] = {}

        # Clear stale stop file from previous runs
        self.data_dir = self.agent_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "stop").unlink(missing_ok=True)

        # Band context for tools
        self.band_ctx = BandContext()
        self.band_ctx.agent_handle = self.handle
        self.band_ctx.agent_name = self.name
        self.band_ctx.band_client = self.band

        # Logging
        self._setup_logging()

        log.info(f"{self.name} initialized: handle={self.handle}, "
                 f"agent_id={self.agent_id}, model={self.MODEL}")

    def _setup_logging(self):
        log_file = self.log_dir / f"{self.name.lower()}-{datetime.now():%Y%m%d}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
            force=True,
        )

    # ── PID Management ───────────────────────────────────────────

    def _write_pid(self):
        """Write PID file so external tools can find us."""
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))

    def _remove_pid(self):
        try:
            self.pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Tool assembly ────────────────────────────────────────────

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the agent's system prompt.

        Checks for a prompt_override.md file first (set by agent_edit_prompt tool).
        Falls back to the subclass's own prompt if no override exists.
        """
        override_path = self.agent_dir / "prompt_override.md"
        if override_path.exists():
            return override_path.read_text().strip()
        # Fall back to subclass implementation — subclass must override this method
        return ""

    def get_extra_tools(self) -> list:
        """Override to add agent-specific tools."""
        return []

    # ── Direct chat (bypasses Band — for TUI) ──────────────────────

    _direct_lock = None  # Class-level threading lock

    def process_direct_message(self, content: str, context: str = "",
                               session_id: str = "direct") -> str:
        """Process a message directly through the LLM without Band.

        Called by the /chat HTTP endpoint when the TUI sends a message.
        Returns the agent's text response.

        This is synchronous — the caller (HTTP handler) blocks until done.
        A lock prevents concurrent processing with Band poll messages.
        """
        import threading
        if BaseAgent._direct_lock is None:
            BaseAgent._direct_lock = threading.Lock()

        with BaseAgent._direct_lock:
            # Build message with context
            full_content = content
            if context:
                full_content = f"[Previous conversation context]\n{context}\n\n[New message]\n{content}"

            # Use a separate thread_id for direct chat sessions
            thread_id = f"direct-{session_id}"
            config = {"configurable": {"thread_id": thread_id}}

            messages = []
            if not self._prompt_injected:
                messages.append(SystemMessage(content=self._system_prompt))
                self._prompt_injected = True

            messages.append(HumanMessage(
                content=f"[Direct chat from user]\n{full_content}"))

            try:
                result = self._agent.invoke(
                    {"messages": messages}, config=config)
                output_msgs = result.get("messages", [])
                response = ""
                for msg in reversed(output_msgs):
                    if isinstance(msg, AIMessage) and msg.content:
                        if (hasattr(msg, "tool_calls")
                                and msg.tool_calls and not msg.content):
                            continue
                        response = msg.content
                        break

                if not response:
                    response = "Processed — no text output."

                log.info(f"{self.name} direct chat: "
                         f"in={len(content)}→out={len(response)}")
                self._total_processed += 1
                return response

            except Exception as e:
                log.error(f"{self.name} direct chat error: {e}")
                return f"Error processing message: {e}"

    def _build_agent(self):
        """Build the LangGraph ReAct agent with all tools."""
        shared_tools = make_shared_band_tools(self.band_ctx)
        extra = self.get_extra_tools()
        all_tools = [*shared_tools, *extra]

        # AI/ML API — OpenAI-compatible, generous concurrency
        llm = ChatOpenAI(
            model=self.MODEL,
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            temperature=self.TEMPERATURE,
        )

        checkpointer = MemorySaver()
        agent = create_react_agent(
            model=llm, tools=all_tools, checkpointer=checkpointer)

        self._agent = agent
        self._checkpointer = checkpointer
        self._system_prompt = self.get_system_prompt()
        self._prompt_injected = False

        log.info(f"{self.name} agent built: {len(all_tools)} tools, "
                 f"model={self.MODEL}")

    # ── Message Processing ───────────────────────────────────────

    def process_message(self, chat_id: str, message_id: str,
                        sender_id: str, sender_name: str,
                        sender_type: str, content: str) -> str:
        """Process one message through the LangGraph agent."""
        if not self._agent:
            self._build_agent()

        # Set Band context
        self.band_ctx.chat_id = chat_id
        self.band_ctx.message_id = message_id
        self.band_ctx.sender_id = sender_id
        self.band_ctx.sender_name = sender_name
        self.band_ctx.sender_type = sender_type

        config = {"configurable": {"thread_id": self._thread_id}}
        messages = []

        if not self._prompt_injected:
            messages.append(SystemMessage(content=self._system_prompt))
            self._prompt_injected = True

        messages.append(HumanMessage(
            content=f"[From: {sender_name} in chat {chat_id[:8]}]\n\n{content}"))

        try:
            result = self._agent.invoke(
                {"messages": messages}, config=config)
            output_msgs = result.get("messages", [])
            response = ""
            for msg in reversed(output_msgs):
                if isinstance(msg, AIMessage) and msg.content:
                    if (hasattr(msg, "tool_calls")
                            and msg.tool_calls and not msg.content):
                        continue
                    response = msg.content
                    break

            if not response:
                response = "Processed — no text output."

            log.info(f"{self.name} processed {message_id}: "
                     f"in={len(content)}→out={len(response)}")

            # Auto-respond via Band (fallback if agent didn't call band_respond)
            if getattr(self, "AUTO_RESPOND", True):
                # Check if blob worker wants to route to next agent
                override_target = getattr(self, "AUTO_RESPOND_TARGET", "")
                try:
                    if override_target:
                        # Blob worker: mention the NEXT agent in chain
                        target_id = AGENT_IDS.get(override_target, "")
                        mentions = [ChatMessageRequestMentionsItem(
                            id=target_id, name=override_target)] if target_id else []
                    elif self._is_terminal_response(response) and sender_type != "User":
                        # Terminal response from an agent: mention Void to prevent loop
                        if VOID_AGENT_ID:
                            mentions = [ChatMessageRequestMentionsItem(
                                id=VOID_AGENT_ID, name="void")]
                        else:
                            void = self._resolve_void_mention(chat_id)
                            if void:
                                mentions = [ChatMessageRequestMentionsItem(
                                    id=void["id"], name=void.get("name") or None)]
                            else:
                                own_id = AGENT_IDS.get(self.name.lower(), "")
                                mentions = [ChatMessageRequestMentionsItem(
                                    id=own_id, name=self.name.lower())] if own_id else []
                    else:
                        # Normal user message: mention the sender (user) if available,
                        # otherwise mention Void or self. Band REQUIRES at least 1 mention.
                        if sender_id:
                            mentions = [ChatMessageRequestMentionsItem(
                                id=sender_id, name=sender_name or None)]
                        elif VOID_AGENT_ID:
                            mentions = [ChatMessageRequestMentionsItem(
                                id=VOID_AGENT_ID, name="void")]
                        else:
                            own_id = AGENT_IDS.get(self.name.lower(), "")
                            mentions = [ChatMessageRequestMentionsItem(
                                id=own_id, name=self.name.lower())] if own_id else []
                    msg = ChatMessageRequest(content=response, mentions=mentions)
                    # Safety net: Band requires at least 1 mention per message
                    if not mentions:
                        if VOID_AGENT_ID:
                            mentions = [ChatMessageRequestMentionsItem(
                                id=VOID_AGENT_ID, name="void")]
                        else:
                            own_id = AGENT_IDS.get(self.name.lower(), "")
                            if own_id:
                                mentions = [ChatMessageRequestMentionsItem(
                                    id=own_id, name=self.name.lower())]
                    if not mentions:
                        log.warning("Auto-send: no mention target available, skipping send")
                    else:
                        msg = ChatMessageRequest(content=response, mentions=mentions)
                        self.band.agent_api_messages.create_agent_chat_message(
                            chat_id=chat_id, message=msg)
                    log.info(f"📤 Auto-sent → {len(response)} chars (target={override_target or 'sender'})")
                except Exception as e:
                    log.error(f"Auto-send failed: {e}")

            return response

        except Exception as e:
            log.error(f"Agent error on {message_id}: {e}")
            traceback.print_exc()
            return f"⚠️ Internal error: {str(e)[:300]}"

    # ── Polling ──────────────────────────────────────────────────

    def _is_stale(self, msg) -> bool:
        """Check if a message is older than STALE_THRESHOLD."""
        if not self.STALE_THRESHOLD_SEC:
            return False
        if not hasattr(msg, "inserted_at") or not msg.inserted_at:
            return False
        try:
            age = (datetime.now() - msg.inserted_at.replace(tzinfo=None)).total_seconds()
            return age > self.STALE_THRESHOLD_SEC
        except Exception:
            return False

    def _should_skip_for_loop_prevention(self, chat_id: str,
                                          sender_name: str,
                                          sender_type: str) -> str | None:
        """Return reason string if this message should be skipped (loop prevention).
        Returns None if the message should be processed normally."""
        own_name = self.name.lower()

        # 1. Self-echo: agent responding to its own message
        last = self._last_sender.get(chat_id)
        if last and last.lower() == sender_name.lower() and sender_name.lower() == own_name:
            return f"self-echo (last sender was also {own_name})"

        # 2. Agent-only spiral: last N messages all from agents, no human
        history = self._sender_history.get(chat_id, [])
        if len(history) >= self.AGENT_LOOP_GUARD:
            recent = history[-self.AGENT_LOOP_GUARD:]
            if all(t.lower() == "agent" for t in recent):
                if sender_type.lower() == "agent":
                    return f"agent-loop guard: last {self.AGENT_LOOP_GUARD} msgs all agent"

        return None  # OK to process

    # ── Terminal Response Detection ─────────────────────────────

    TERMINAL_PATTERNS = [
        "okay", "ok", "done", "completed", "finished",
        "acknowledged", "noted", "received", "understood",
        "stopping", "stopped", "shutting down", "shutdown",
        "will do", "on it", "got it", "roger",
        "thank", "thanks", "goodbye", "bye",
        "no problem", "sure thing",
    ]

    def _is_terminal_response(self, text: str) -> bool:
        """Detect dead-end responses that should not trigger agent replies.
        Short messages containing acknowledgment words = terminal."""
        t = text.strip().lower()
        if len(t) > 300:   # Long messages are substantive
            return False
        for pat in self.TERMINAL_PATTERNS:
            if pat in t:
                return True
        return False

    # ── Void Mention Resolution (dead-end target for no-echo msgs)

    _void_cache: dict[str, dict] = {}

    def _resolve_void_mention(self, chat_id: str) -> dict | None:
        """Find a human user in a chatroom to use as dead-end mention target.
        Cached per chatroom. Returns {id, name} or None."""
        if chat_id in self._void_cache:
            return self._void_cache[chat_id]
        try:
            resp = self.band.agent_api_participants.list_agent_chat_participants(
                chat_id=chat_id)
            parts = resp.data if hasattr(resp, "data") else []
            for p in (parts or []):
                ptype = str(p.type).lower() if hasattr(p, "type") else ""
                if ptype == "user":
                    entry = {"id": p.id, "name": getattr(p, "name", None) or "user"}
                    self._void_cache[chat_id] = entry
                    return entry
        except Exception:
            pass
        return None

    def _startup_purge_stale_messages(self):
        """On startup, bulk-mark all stale messages as processed in parallel across rooms.
        Prevents flood of old messages when agent comes online."""
        log.info(f"Purging stale messages (> {self.STALE_THRESHOLD_SEC}s old)...")
        try:
            resp = self.band.agent_api_chats.list_agent_chats(page_size=50)
            chats = resp.data if hasattr(resp, "data") else []
        except Exception as e:
            log.warning(f"Startup purge: chat list failed ({e}), skipping")
            return

        if not chats:
            log.info("Startup purge: no chatrooms")
            return

        def _purge_room(chat):
            chat_id = chat.id
            title = (chat.title or chat_id)[:30]
            try:
                msgs_resp = self.band.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, status="all", page_size=100)
                msgs = msgs_resp.data if hasattr(msgs_resp, "data") else []
            except Exception:
                return (0, title)

            purged = 0
            for msg in (msgs or []):
                if self._is_stale(msg):
                    msg_id = msg.id
                    try:
                        self.band.agent_api_messages.mark_agent_message_processing(
                            chat_id=chat_id, id=msg_id)
                        self.band.agent_api_messages.mark_agent_message_processed(
                            chat_id=chat_id, id=msg_id)
                    except Exception:
                        pass
                    purged += 1
            return (purged, title)

        purged_total = 0
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {executor.submit(_purge_room, c): c for c in chats}
            for future in as_completed(futures):
                try:
                    n, title = future.result()
                    if n:
                        log.info(f"  Purged {n} stale from [{title}]")
                        purged_total += n
                except Exception:
                    pass

        if purged_total:
            log.info(f"Startup purge complete: {purged_total} stale messages skipped")
        else:
            log.info("Startup purge: no stale messages found")

    def _remove_other_agents_from_room(self, chat_id: str) -> int:
        """Remove all OTHER agent participants from a room. Keeps self + human users.
        Returns number of agents removed."""
        removed = 0
        try:
            resp = self.band.agent_api_participants.list_agent_chat_participants(
                chat_id=chat_id)
            participants = resp.data if hasattr(resp, "data") else []
            for p in participants:
                p_id = p.id
                p_type = str(p.type).lower() if hasattr(p, "type") else ""
                # Remove agents except self; leave humans
                if p_id != self.agent_id and p_type == "agent":
                    try:
                        self.band.agent_api_participants.remove_agent_chat_participant(
                            chat_id=chat_id, id=p_id)
                        p_name = getattr(p, "name", p_id[:8])
                        log.info(f"    Removed {p_name} from [{chat_id[:8]}]")
                        removed += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return removed

    def _startup_cleanup_rooms(self):
        """After stale purge, remove other agents from idle rooms in parallel.
        Keeps self + human users in the room."""
        log.info("Cleaning up idle chatrooms (removing other agents)...")
        try:
            resp = self.band.agent_api_chats.list_agent_chats(page_size=50)
            chats = resp.data if hasattr(resp, "data") else []
        except Exception as e:
            log.warning(f"Room cleanup: chat list failed ({e})")
            return

        if not chats:
            log.info("Room cleanup: no chatrooms")
            return

        def _maybe_clean_room(chat):
            chat_id = chat.id
            title = (chat.title or chat_id)[:30]
            try:
                pending = self.band.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, limit=1)
                msgs = pending.data if hasattr(pending, "data") else []
                if msgs:
                    return (None, 0, title)  # active — keep
            except Exception:
                pass

            # Idle room — remove other agents
            n = self._remove_other_agents_from_room(chat_id)
            return ("cleaned", n, title)

        kept = 0
        cleaned = 0
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {executor.submit(_maybe_clean_room, c): c for c in chats}
            for future in as_completed(futures):
                try:
                    status, n, title = future.result()
                    if status == "cleaned":
                        if n:
                            log.info(f"  Cleaned [{title}]: removed {n} agents")
                        cleaned += 1
                    else:
                        kept += 1
                except Exception:
                    pass

        log.info(f"Room cleanup: {cleaned} idle rooms cleaned, {kept} active rooms kept")

    def _fetch_next_if_pending(self, chat: Any) -> tuple[Any, Any | None]:
        """Fetch the next pending message for a chatroom. Returns (chat, msg|None)."""
        chat_id = chat.id
        try:
            next_resp = self.band.agent_api_messages.get_agent_next_message(
                chat_id=chat_id)
            msg = next_resp.data if hasattr(next_resp, "data") else None
            return (chat, msg)
        except Exception:
            return (chat, None)

    def poll_and_process(self) -> int:
        """Check all chatrooms for pending messages. Returns count processed."""
        processed = 0
        try:
            resp = self.band.agent_api_chats.list_agent_chats(page_size=50)
            chats = resp.data if hasattr(resp, "data") else []
        except Exception as e:
            log.error(f"Chat list failed: {e}")
            return 0

        if not chats:
            return 0

        # ── Phase 1: parallel fetch — check all rooms for pending messages ──
        pending: list[tuple[Any, Any]] = []  # (chat, msg)
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {}
            for chat in chats:
                futures[executor.submit(
                    self._fetch_next_if_pending, chat)] = chat

            for future in as_completed(futures):
                try:
                    chat, msg = future.result()
                    if msg is not None:
                        pending.append((chat, msg))
                except Exception:
                    pass  # Individual room fetch failed — skip

        # ── Phase 2: sequential process — LLM calls one at a time ──
        for chat, msg in pending:
            chat_id = chat.id
            msg_id = msg.id
            if msg_id in self._processed_ids:
                continue

            sender_name = msg.sender_name or "unknown"
            sender_type = msg.sender_type or "unknown"

            # ── Layer 1: Inline stale time gate ─────────────────
            if self._is_stale(msg):
                log.info(f"⏭️ Skipping stale msg {msg_id[:8]} "
                         f"[{chat.title or '?'}] from {sender_name}")
                try:
                    self.band.agent_api_messages.mark_agent_message_processing(
                        chat_id=chat_id, id=msg_id)
                    self.band.agent_api_messages.mark_agent_message_processed(
                        chat_id=chat_id, id=msg_id)
                except Exception:
                    pass
                self._processed_ids.add(msg_id)
                continue

            # ── Layer 2: Loop / echo prevention ─────────────────
            skip_reason = self._should_skip_for_loop_prevention(
                chat_id, sender_name, sender_type)
            if skip_reason:
                log.info(f"🔇 Skipping [{chat.title or '?'}] {sender_name}: {skip_reason}")
                try:
                    self.band.agent_api_messages.mark_agent_message_processing(
                        chat_id=chat_id, id=msg_id)
                    self.band.agent_api_messages.mark_agent_message_processed(
                        chat_id=chat_id, id=msg_id)
                except Exception:
                    pass
                self._processed_ids.add(msg_id)
                # Update sender history so we don't get stuck
                hist = self._sender_history.get(chat_id, [])
                hist.append(sender_type.lower())
                self._sender_history[chat_id] = hist[-10:]
                self._last_sender[chat_id] = sender_name
                continue

            log.info(f"📩 [{chat.title or '?'}] {sender_name}: "
                     f"{msg.content[:100] if msg.content else ''}")

            # Mark as processing
            try:
                self.band.agent_api_messages.mark_agent_message_processing(
                    chat_id=chat_id, id=msg_id)
            except Exception:
                pass

            # Process
            try:
                self.process_message(
                    chat_id=chat_id,
                    message_id=msg_id,
                    sender_id=msg.sender_id,
                    sender_name=sender_name,
                    sender_type=sender_type,
                    content=msg.content or "",
                )
            except Exception as e:
                log.error(f"Processing failed for {msg_id}: {e}")
                try:
                    self.band.agent_api_messages.mark_agent_message_failed(
                        chat_id=chat_id, id=msg_id, error=str(e)[:500])
                except Exception:
                    pass
                self._processed_ids.add(msg_id)
                continue

            # Mark processed
            try:
                self.band.agent_api_messages.mark_agent_message_processed(
                    chat_id=chat_id, id=msg_id)
            except Exception:
                pass

            self._processed_ids.add(msg_id)
            processed += 1

            # ── Runtime room cleanup: remove other agents if no pending work ──
            try:
                pending = self.band.agent_api_messages.list_agent_messages(
                    chat_id=chat_id, limit=1)
                remaining = pending.data if hasattr(pending, "data") else []
                if not remaining:
                    n = self._remove_other_agents_from_room(chat_id)
                    if n:
                        title = (chat.title or chat_id)[:30]
                        log.info(f"🧹 Cleaned [{title}]: removed {n} other agents")
            except Exception:
                pass  # Non-critical — room will be cleaned on next startup

            # ── Update loop prevention state ────────────────────
            self._last_sender[chat_id] = sender_name
            hist = self._sender_history.get(chat_id, [])
            hist.append(sender_type.lower())
            self._sender_history[chat_id] = hist[-10:]  # Keep last 10
            self._last_processed_at[chat_id] = time.time()

            # Trim dedup cache
            if len(self._processed_ids) > 2000:
                keep = list(self._processed_ids)[-1000:]
                self._processed_ids = set(keep)

        return processed

    # ── Fleet Management ─────────────────────────────────────────

    def _ensure_managers_running(self):
        """On startup, auto-start any configured manager agents.
        Only supervisors should set AUTO_START_MANAGERS."""
        if not self.AUTO_START_MANAGERS:
            return
        log.info(f"Ensuring managers are running: {self.AUTO_START_MANAGERS}")
        try:
            results = fleet.ensure_agents_running(self.AUTO_START_MANAGERS)
            for name, result in results.items():
                if result.get("running"):
                    log.info(f"  ✅ {name}: already running (PID {result.get('pid')})")
                elif result.get("ok"):
                    log.info(f"  🚀 {name}: started (PID {result['pid']})")
                else:
                    log.warning(f"  ❌ {name}: {result.get('error', 'failed')}")
        except Exception as e:
            log.warning(f"Manager startup failed: {e}")

    def _manager_watchdog(self):
        """Periodic health check: restart any configured manager that died.
        Runs in a background thread so it never blocks polling."""
        if not self.AUTO_START_MANAGERS or self._watchdog_running:
            return
        self._watchdog_running = True
        try:
            for name in self.AUTO_START_MANAGERS:
                if not fleet.agent_is_running(name):
                    log.warning(f"Watchdog: {name} is down — restarting")
                    result = fleet.launch_agent(name)
                    if result["ok"]:
                        log.info(f"Watchdog: {name} restarted (PID {result['pid']})")
                    else:
                        log.error(f"Watchdog: {name} restart failed: {result.get('error')}")
        finally:
            self._watchdog_running = False

    # ── Main Loop ────────────────────────────────────────────────

    @property
    def STOP_FILE(self) -> Path:
        return self.agent_dir / "data" / "stop"

    def run(self):
        """Main event loop. Polls Band forever until stopped."""
        self._running = True
        self._start_time = time.time()
        self._write_pid()

        if not self._agent:
            self._build_agent()

        # Start health HTTP endpoint
        health = start_health_server(self)

        banner = (
            f"\n{'='*60}\n"
            f"  {self.name} AWAKE — {self.handle}\n"
            f"  PID: {os.getpid()}  Model: {self.MODEL}  Poll: {self.POLL_INTERVAL}s\n"
            f"  Health: http://127.0.0.1:{AGENT_PORTS.get(self.name.lower(), '?')}/health\n"
            f"  Stop:   touch {self.STOP_FILE}  or  Ctrl+C\n"
            f"{'='*60}\n"
        )
        log.info(banner)
        print(banner, flush=True)

        # ── Startup: purge stale messages (flood prevention) ────
        try:
            self._startup_purge_stale_messages()
        except Exception as e:
            log.warning(f"Startup purge failed (continuing): {e}")

        # ── Startup: leave idle chatrooms (reduces poll overhead) ─
        try:
            self._startup_cleanup_rooms()
        except Exception as e:
            log.warning(f"Room cleanup failed (continuing): {e}")

        # ── Startup: keep manager agents awake ───────────────────
        try:
            self._ensure_managers_running()
        except Exception as e:
            log.warning(f"Manager startup failed (continuing): {e}")

        cycle = 0
        total = 0
        error_streak = 0

        while self._running:
            # Check stop file
            if self.STOP_FILE.exists():
                self.STOP_FILE.unlink(missing_ok=True)
                log.info("Stop file detected — shutting down.")
                break

            cycle += 1
            self._cycle_count = cycle

            try:
                n = self.poll_and_process()
                total += n
                self._total_processed = total
                error_streak = 0
                self._error_backoff = 0.0

                if cycle % 20 == 0:
                    log.info(f"Cycle {cycle}: {total} total processed, "
                             f"dedup cache={len(self._processed_ids)}")

                # Periodic manager health check (non-blocking thread)
                if cycle % self.WATCHDOG_INTERVAL_CYCLES == 0:
                    Thread(target=self._manager_watchdog, daemon=True).start()
            except Exception as e:
                error_streak += 1
                self._error_backoff = min(
                    self.ERROR_BACKOFF_BASE * (2 ** min(error_streak - 1, 5)),
                    self.ERROR_BACKOFF_MAX)
                log.error(f"Cycle {cycle} error (streak={error_streak}, "
                          f"backoff={self._error_backoff}s): {e}")

            # Sleep: normal interval or error backoff
            sleep_time = self._error_backoff if self._error_backoff else self.POLL_INTERVAL
            time.sleep(sleep_time)

        # Cleanup
        log.info(f"{self.name} shutting down. Total: {total} messages in {cycle} cycles.")
        self._remove_pid()
        if health:
            health.shutdown()
        self._running = False

    def stop(self):
        """Graceful stop."""
        log.info(f"{self.name} stop signal received.")
        self._running = False
        self._remove_pid()
