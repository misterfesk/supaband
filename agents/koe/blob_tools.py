"""Koe blob tools — orchestrate Blob shadow-testing sessions.

Koe uses these tools to:
  1. Set consumer personalities for each blob worker
  2. Launch blob worker processes
  3. Create and seed a Band discussion chatroom
  4. Monitor message count until threshold
  5. Kill workers and return export path for analysis

Blob orchestration workflow (Koe's LLM calls these in order):
  blob_set_personality(blobw1, "...")   ← write each personality
  blob_set_personality(blobw2, "...")
  blob_set_personality(blobw3, "...")
  blob_launch_workers()                 ← start blob processes
  band_create_chatroom(...)             ← from shared tools — create discussion room
  blob_set_active_chat(chat_id)         ← register the room for monitoring
  band_add_participant(blobw1/2/3)      ← shared tool — add blobs to room
  band_send_message(chat_id, brief)     ← shared tool — seed the discussion
  blob_monitor()                        ← poll until threshold reached
  blob_kill_workers()                   ← terminate blobs
  band_export_chat(chat_id, ...)        ← shared tool — export transcript
  [analyze transcript via LLM]
  research_save(verdict)                ← from koe tools — persist result
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from core.config import load_agent_config, get_agent_entry, PROJECT_ROOT

# ── Paths ─────────────────────────────────────────────────────────────

BLOB_DIR = PROJECT_ROOT / "blob"
KOE_EXPORTS = PROJECT_ROOT / "agents" / "koe" / "data" / "exports"
KOE_EXPORTS.mkdir(parents=True, exist_ok=True)

BLOB_AGENTS = ["blobw1", "blobw2", "blobw3"]

# ── Mutable session state (in-process, reset on koe restart) ──────────

_BLOB_STATE: dict = {
    "pids": {},          # agent_name → pid (int)
    "active_chat": None, # active blob chatroom ID (str | None)
    "started_at": None,  # session start timestamp
}


# ── Tools ─────────────────────────────────────────────────────────────

@tool
def blob_set_personality(agent_name: str, content: str) -> str:
    """Overwrite a blob worker's personality before starting a simulation.

    Call this for each blob agent (blobw1, blobw2, blobw3) before blob_launch_workers().
    The personality file is read by the blob agent at startup as its system prompt context.

    Args:
        agent_name: One of "blobw1", "blobw2", "blobw3"
        content: Full personality description in plain text or markdown.
                 Include: consumer archetype, income bracket, decision drivers,
                 communication style, and product attitudes relevant to the test.
    """
    name = agent_name.lower().strip()
    if name not in BLOB_AGENTS:
        return f"❌ Unknown blob agent '{agent_name}'. Valid names: {', '.join(BLOB_AGENTS)}"

    personality_path = BLOB_DIR / name / "personality.md"
    try:
        personality_path.parent.mkdir(parents=True, exist_ok=True)
        personality_path.write_text(content.strip())
        return f"✅ Personality set for {name} — {len(content)} chars written to {personality_path.relative_to(PROJECT_ROOT)}"
    except Exception as e:
        return f"❌ Failed to write {name} personality: {e}"


@tool
def blob_launch_workers() -> str:
    """Launch all 3 blob worker agents as background processes.

    Run AFTER calling blob_set_personality() for each agent.
    Waits 3 seconds for agents to initialize and connect to Band before returning.

    Returns:
        Status of each launch attempt with PIDs.
    """
    results = []

    for name in BLOB_AGENTS:
        agent_py = BLOB_DIR / name / "agent.py"
        if not agent_py.exists():
            results.append(f"❌ {name}: agent.py not found at blob/{name}/agent.py")
            continue

        # Kill any existing stale process for this blob worker
        try:
            subprocess.run(
                ["pkill", "-f", f"blob/{name}/agent.py"],
                capture_output=True, timeout=3
            )
            time.sleep(0.2)
        except Exception:
            pass

        # Launch fresh process (use sys.executable for correct venv)
        try:
            process = subprocess.Popen(
                [sys.executable, str(agent_py)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _BLOB_STATE["pids"][name] = process.pid
            results.append(f"✅ {name} — PID {process.pid}")
        except Exception as e:
            results.append(f"❌ {name} launch failed: {e}")

    _BLOB_STATE["started_at"] = datetime.now().isoformat()

    # Give agents time to initialize + connect to Band
    time.sleep(3.0)

    summary = "\n".join(results)
    launched = sum(1 for r in results if r.startswith("✅"))
    return (
        f"🫧 Blob workers launched: {launched}/{len(BLOB_AGENTS)}\n"
        f"{summary}\n\n"
        f"⏳ Waited 3s for Band connection. Next step:\n"
        f"  1. band_create_chatroom(title='Blob — <product>', add_agents='blobw1,blobw2,blobw3')\n"
        f"  2. blob_set_active_chat(<chat_id>)\n"
        f"  3. band_send_message(<chat_id>, <product_brief>, mention_names='blobw1,blobw2,blobw3')"
    )


@tool
def blob_kill_workers() -> str:
    """Terminate all running blob worker processes.

    Call after blob_monitor() reports threshold reached and after band_export_chat() completes.
    Clears the active session state.
    """
    results = []

    # Kill by tracked PIDs
    for name, pid in list(_BLOB_STATE["pids"].items()):
        try:
            os.kill(pid, 15)  # SIGTERM — graceful shutdown
            results.append(f"✅ {name} (PID {pid}) terminated")
        except ProcessLookupError:
            results.append(f"⚠️ {name} (PID {pid}) already gone")
        except Exception as e:
            results.append(f"❌ {name}: {e}")

    _BLOB_STATE["pids"].clear()

    # Belt-and-suspenders: kill any blob processes by name pattern
    try:
        subprocess.run(
            ["pkill", "-f", "blob/blobw"],
            capture_output=True, timeout=3
        )
    except Exception:
        pass

    _BLOB_STATE["active_chat"] = None
    _BLOB_STATE["started_at"] = None

    return "\n".join(results) if results else "No tracked blob processes to kill."


@tool
def blob_set_active_chat(chat_id: str) -> str:
    """Register the blob discussion chatroom ID for monitoring.

    Call this immediately after band_create_chatroom() returns the chat_id.
    blob_monitor() will use this ID if none is passed directly.

    Args:
        chat_id: The Band chatroom UUID returned by band_create_chatroom()
    """
    if not chat_id or len(chat_id) < 8:
        return "❌ Invalid chat_id — must be a Band UUID string."
    _BLOB_STATE["active_chat"] = chat_id
    return f"✅ Active blob chat registered: {chat_id}"


@tool
def blob_monitor(chat_id: str = "") -> str:
    """Count total messages in the blob discussion chatroom.

    Use this to decide when to stop the simulation.
    Target threshold: 20–30 messages.

    Call periodically while blob agents are discussing. When threshold is reached,
    call blob_kill_workers() then band_export_chat().

    Args:
        chat_id: Band chatroom UUID. If empty, uses the registered active chat.

    Returns:
        Message count, threshold status, and recommended next action.
    """
    target = chat_id.strip() if chat_id.strip() else _BLOB_STATE.get("active_chat")
    if not target:
        return (
            "❌ No chat_id provided and no active blob chat registered.\n"
            "   Call blob_set_active_chat(chat_id) first."
        )

    try:
        config = load_agent_config()
        entry = get_agent_entry(config, "research_manager")
        api_key = entry.get("api_key", "")
        if not api_key or api_key.startswith("PLACEHOLDER"):
            return "❌ Koe's Band API key is missing or placeholder — check agent_config.yaml."

        from thenvoi_rest import RestClient
        client = RestClient(
            api_key=api_key,
            base_url="https://app.band.ai",
            timeout=30.0,
        )
        resp = client.agent_api_messages.list_agent_messages(
            chat_id=target, status="all", page_size=200
        )
        msgs = resp.data if hasattr(resp, "data") else []
        count = len(msgs) if msgs else 0

    except Exception as e:
        return f"❌ blob_monitor failed: {e}"

    # Threshold logic (test phase: 6 messages is sufficient)
    if count >= 12:
        status = "🔴 STOP — threshold exceeded (≥12 messages)"
        action = "Call blob_kill_workers() then export_to_topic() immediately."
    elif count >= 6:
        status = "🟡 THRESHOLD REACHED — discussion complete (≥6 messages)"
        action = "Call blob_kill_workers() then export_to_topic(topic, chat_id) to export and analyze."
    elif count >= 3:
        status = f"🟢 Discussion active — {count} messages (target: 6)"
        action = "Continue monitoring. Call blob_monitor() again in 30 seconds."
    else:
        status = f"🟢 Discussion just started — {count} messages"
        action = "Agents are warming up. Check again in 30 seconds."

    uptime = ""
    if _BLOB_STATE.get("started_at"):
        try:
            start = datetime.fromisoformat(_BLOB_STATE["started_at"])
            elapsed = int((datetime.now() - start).total_seconds())
            uptime = f"\n   Session uptime: {elapsed}s"
        except Exception:
            pass

    return (
        f"📊 Blob Discussion Monitor\n"
        f"   Room: {target[:12]}...{uptime}\n"
        f"   Messages: {count}\n"
        f"   Status: {status}\n"
        f"   Next: {action}"
    )


@tool
def blob_status() -> str:
    """Show the current status of blob worker processes and active session.

    Use to check if blob agents are still running before monitoring or after a restart.
    """
    lines = ["🫧 Blob Session Status:"]

    if not _BLOB_STATE["pids"]:
        lines.append("  Workers: none running")
    else:
        for name, pid in _BLOB_STATE["pids"].items():
            try:
                os.kill(pid, 0)
                alive = "🟢 alive"
            except (ProcessLookupError, PermissionError):
                alive = "🔴 dead"
            lines.append(f"  {name}: PID {pid} — {alive}")

    chat = _BLOB_STATE.get("active_chat")
    lines.append(f"  Active chat: {chat or 'none'}")

    started = _BLOB_STATE.get("started_at")
    if started:
        try:
            start = datetime.fromisoformat(started)
            elapsed = int((datetime.now() - start).total_seconds())
            lines.append(f"  Session started: {started} ({elapsed}s ago)")
        except Exception:
            lines.append(f"  Session started: {started}")

    return "\n".join(lines)


# ── Tool list exported to koe ─────────────────────────────────────────

BLOB_TOOLS = [
    blob_set_personality,
    blob_launch_workers,
    blob_kill_workers,
    blob_set_active_chat,
    blob_monitor,
    blob_status,
]
