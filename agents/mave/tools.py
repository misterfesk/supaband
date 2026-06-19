"""Mave-specific tools: file management, worker factory, prompt editing, department coordination.

Mave is the Marketing & Digital Production Manager. She can:
- Create and manage worker agents (content, SEO, visual production)
- Edit worker system prompts
- Read/write files for campaign materials
- Access the blackboard for cross-department sharing
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool
from core.config import PROJECT_ROOT
from core.worker_factory import (
    create_worker as _create_worker,
    edit_worker_prompt as _edit_worker_prompt,
    get_worker_prompt as _get_worker_prompt,
    launch_worker as _launch_worker,
    kill_worker as _kill_worker,
    list_workers as _list_workers,
    credential_create as _credential_create,
)
from core import fleet


# ── File Tools ───────────────────────────────────────────────────────

@tool
def file_read(path: str) -> str:
    """Read a file within supaband/. Use to review campaign materials, research, or configs.

    Args:
        path: Relative path from supaband/ (e.g. "workers/quill/system_prompt.md")
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    if not full.exists():
        return f"❌ File not found: {path}"
    try:
        content = full.read_text()
        preview = content[:4000]
        suffix = f"\n... ({len(content) - 4000} more chars)" if len(content) > 4000 else ""
        return f"📄 {path} ({len(content)} chars):\n\n{preview}{suffix}"
    except Exception as e:
        return f"❌ Read failed: {e}"


@tool
def file_write(path: str, content: str) -> str:
    """Write a file within supaband/. Use to create campaign briefs, content drafts, or reports.

    Args:
        path: Relative path from supaband/ (e.g. "agents/mave/data/campaigns/q3-brief.md")
        content: Full file content
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return f"✅ Written {len(content)} chars → {path}"
    except Exception as e:
        return f"❌ Write failed: {e}"


@tool
def file_list(dir_path: str = "") -> str:
    """List files in a directory within supaband/.

    Args:
        dir_path: Relative directory path (default: supaband/ root)
    """
    full = (PROJECT_ROOT / dir_path).resolve() if dir_path else PROJECT_ROOT
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    if not full.is_dir():
        return f"❌ Not a directory: {dir_path}"
    entries = sorted(full.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    lines = [f"📂 {dir_path or 'supaband/'}"]
    for e in entries[:50]:
        kind = "📁" if e.is_dir() else "📄"
        lines.append(f"  {kind} {e.name}")
    if len(entries) > 50:
        lines.append(f"  ... ({len(entries) - 50} more)")
    return "\n".join(lines)


# ── Worker Factory Tools (Mave can spawn marketing workers) ──────────

@tool
def worker_create(name: str, description: str, system_prompt: str) -> str:
    """Create a new marketing worker agent. Registers on Band, creates local files.
    The worker is NOT auto-started — call worker_launch() after.

    Args:
        name: Worker name, lowercase (e.g. "social-media-writer")
        description: Short description
        system_prompt: Full system prompt defining the worker's role and behavior
    """
    result = _create_worker(name=name, description=description, system_prompt=system_prompt)
    if not result["ok"]:
        return f"❌ Worker creation failed: {result.get('error')}"
    return (
        f"✅ Worker '{result['worker_name']}' created!\n"
        f"   Agent ID: {result['agent_id'][:12]}...\n"
        f"   Handle: {result.get('handle', 'N/A')}\n"
        f"   Path: {result['path']}\n"
        f"   Next: Use worker_launch('{result['worker_name']}') to start it."
    )


@tool
def worker_launch(worker_name: str) -> str:
    """Start a worker agent as a background process."""
    result = _launch_worker(worker_name)
    if not result["ok"]:
        return f"❌ {result.get('error', 'launch failed')}"
    return f"✅ Worker '{worker_name}' launched — PID {result['pid']}"


@tool
def worker_kill(worker_name: str) -> str:
    """Stop a running worker agent."""
    result = _kill_worker(worker_name)
    if not result["ok"]:
        return f"❌ {result.get('error', 'kill failed')}"
    return result["message"]


@tool
def worker_edit_prompt(worker_name: str, system_prompt: str) -> str:
    """Edit a worker agent's system prompt. Restart the worker to apply changes."""
    result = _edit_worker_prompt(worker_name, system_prompt)
    if not result["ok"]:
        return f"❌ {result.get('error')}"
    return result["message"]


@tool
def worker_read_prompt(worker_name: str) -> str:
    """Read a worker agent's current system prompt."""
    prompt = _get_worker_prompt(worker_name)
    if prompt is None:
        return f"❌ Worker '{worker_name}' not found or no prompt file."
    return f"📄 {worker_name} system_prompt.md:\n\n{prompt[:4000]}"


@tool
def worker_list() -> str:
    """List all on-demand worker agents with running status."""
    workers = _list_workers()
    if not workers:
        return "No workers created yet."
    lines = [f"🔧 Workers ({len(workers)}):"]
    for w in workers:
        status = f"✅ PID {w['pid']}" if w["running"] else "⚫ offline"
        lines.append(f"  {w['name']:20s} — {status}")
    return "\n".join(lines)


# ── Credential Creation (Mave can request credentials from Supa) ────

@tool
def credential_create(name: str, purpose: str) -> str:
    """Create Band credentials for a new agent without creating local files.
    Returns UUID, API key, and handle. Useful when someone needs to connect
    an external agent to Band.

    Args:
        name: Agent display name (leave empty for random)
        purpose: What the agent will do
    """
    result = _credential_create(name=name, purpose=purpose)
    if not result["ok"]:
        return f"❌ Credential creation failed: {result.get('error')}"
    return (
        f"✅ Credentials created for '{result['name']}':\n"
        f"   UUID: {result['agent_id']}\n"
        f"   API Key: {result['api_key']}\n"
        f"   Handle: {result['handle']}\n"
        f"   Config Key: {result['config_key']}"
    )


# ── Agent Prompt Editing ─────────────────────────────────────────────

@tool
def agent_edit_prompt(agent_name: str, new_prompt: str) -> str:
    """Edit the system prompt of a worker agent. Restart to apply.

    Args:
        agent_name: Worker name (e.g. "quill", "pulse", "canvas")
        new_prompt: New system prompt content
    """
    name = agent_name.lower().strip()
    # Check workers/ first, then agents/
    worker_prompt = PROJECT_ROOT / "workers" / name / "prompt_override.md"
    agent_prompt = PROJECT_ROOT / "agents" / name / "prompt_override.md"
    prompt_path = worker_prompt if worker_prompt.parent.exists() else agent_prompt
    try:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(new_prompt.strip())
        return f"✅ Prompt override written for {name}. Restart to apply."
    except Exception as e:
        return f"❌ Failed: {e}"


@tool
def agent_read_prompt(agent_name: str) -> str:
    """Read the current system prompt of a worker or agent."""
    name = agent_name.lower().strip()
    # Check workers/ first
    for base in ["workers", "agents"]:
        override = PROJECT_ROOT / base / name / "prompt_override.md"
        if override.exists():
            return f"📄 {name} prompt_override.md (ACTIVE):\n\n{override.read_text()[:4000]}"
        prompt = PROJECT_ROOT / base / name / "system_prompt.md"
        if prompt.exists():
            return f"📄 {name} system_prompt.md:\n\n{prompt.read_text()[:4000]}"
    return f"❌ Agent '{name}' not found."


MAVE_TOOLS = [
    file_read, file_write, file_list,
    worker_create, worker_launch, worker_kill,
    worker_edit_prompt, worker_read_prompt, worker_list,
    credential_create,
    agent_edit_prompt, agent_read_prompt,
]
