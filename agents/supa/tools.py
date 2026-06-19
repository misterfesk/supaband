"""Supa-specific tools: file modification, agent lifecycle, worker factory, process control."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool
from core.config import PROJECT_ROOT
from core import fleet
from core.worker_factory import (
    create_worker as _create_worker,
    edit_worker_prompt as _edit_worker_prompt,
    get_worker_prompt as _get_worker_prompt,
    launch_worker as _launch_worker,
    kill_worker as _kill_worker,
    list_workers as _list_workers,
    credential_create as _credential_create,
)


# ── File Tools ───────────────────────────────────────────────────────

@tool
def file_read(path: str) -> str:
    """Read any file relative to the supaband/ directory.
    Use this to inspect other agent configs, logs, or saved data.

    Args:
        path: Relative path from supaband/ (e.g. "agents/koe/agent.py")
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path '{path}' is outside supaband/."

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
    """Write or overwrite a file within supaband/. Use to modify agent code,
    update configs, or save results.

    Args:
        path: Relative path from supaband/ (e.g. "agents/koe/data/research/report.md")
        content: Full file content to write
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path '{path}' is outside supaband/."

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

    try:
        entries = sorted(full.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        lines = [f"📂 {dir_path or 'supaband/'}"]
        for e in entries[:50]:
            kind = "📁" if e.is_dir() else "📄"
            lines.append(f"  {kind} {e.name}")
        if len(entries) > 50:
            lines.append(f"  ... ({len(entries) - 50} more)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ List failed: {e}"


# ── Agent Lifecycle Tools ────────────────────────────────────────────

@tool
def agent_launch(agent_name: str) -> str:
    """Launch another agent (koe, mave, forge, blobw1/2/3) as a
    background process. No-op if already running.

    Args:
        agent_name: Lowercase agent name (e.g. "koe", "mave")
    """
    result = fleet.launch_agent(agent_name)
    if not result["ok"]:
        return f"❌ {agent_name}: {result.get('error', 'launch failed')}"
    if result.get("started"):
        return f"✅ {agent_name} launched — PID {result['pid']}"
    return f"ℹ️ {agent_name} already running — PID {result['pid']}"


@tool
def agent_kill(agent_name: str) -> str:
    """Stop a running agent process by name. Use "all" to stop all managers.

    Args:
        agent_name: Agent name ("koe") or "all" to stop all tracked agents
    """
    name = agent_name.lower()
    if name == "all":
        results = []
        for n in fleet.MANAGER_AGENTS:
            r = fleet.kill_agent(n)
            results.append(f"{n}: {'stopped' if r['ok'] else r.get('error', 'failed')}")
        return "\n".join(results)

    result = fleet.kill_agent(name)
    if not result["ok"]:
        return f"❌ {name}: {result.get('error', 'kill failed')}"
    return f"✅ {name} stopped"


@tool
def agent_restart(agent_name: str) -> str:
    """Restart an agent — kill it then launch fresh.

    Args:
        agent_name: Agent name to restart (e.g. "koe")
    """
    result = fleet.restart_agent(agent_name)
    kill = result["kill"]
    launch = result["launch"]
    kill_msg = "stopped" if kill["ok"] else kill.get("error", "kill failed")
    if not launch["ok"]:
        return f"⚠️ {agent_name}: kill={kill_msg}, launch failed: {launch.get('error')}"
    return f"✅ {agent_name} restarted — PID {launch['pid']}"


@tool
def agent_status() -> str:
    """Show status of all fleet agents via PID files + health endpoints."""
    status = fleet.list_agent_status()
    lines = ["📊 Fleet Status:"]
    for name, info in status.items():
        if info["running"]:
            health = info.get("health") or {}
            cycles = health.get("cycles", "?")
            msgs = health.get("messages_processed", "?")
            lines.append(f"  ✅ {name:8s} — PID {info['pid']} | cycles={cycles} msgs={msgs}")
        else:
            marker = "🧹 stale PID removed" if info.get("stale_removed") else "⚫"
            lines.append(f"  ❌ {name:8s} — not running ({marker})")
    return "\n".join(lines)


@tool
def agent_ensure_running(agent_names: str) -> str:
    """Ensure one or more agents are running. Start any that are offline.
    Comma-separated names, e.g. "koe" or "koe,mave,forge".

    Args:
        agent_names: Comma-separated agent names
    """
    names = [n.strip() for n in agent_names.split(",") if n.strip()]
    results = fleet.ensure_agents_running(names)
    lines = []
    for name, r in results.items():
        if r.get("running"):
            lines.append(f"✅ {name}: already running (PID {r.get('pid')})")
        elif r.get("ok"):
            lines.append(f"🚀 {name}: started (PID {r['pid']})")
        else:
            lines.append(f"❌ {name}: {r.get('error', 'failed')}")
    return "\n".join(lines)


@tool
def agent_health(agent_name: str) -> str:
    """Return detailed health info for a single agent.

    Args:
        agent_name: Agent name (e.g. "koe")
    """
    info = fleet.agent_health(agent_name.lower())
    if not info["running"]:
        return f"❌ {agent_name}: not running"
    health = info.get("health") or {}
    return (
        f"✅ {agent_name}: PID {info['pid']}\n"
        f"   cycles={health.get('cycles', '?')} "
        f"msgs={health.get('messages_processed', '?')} "
        f"uptime={health.get('uptime_seconds', '?')}s"
    )


# ── Worker Factory Tools (on-demand agent creation) ──────────────────

@tool
def worker_create(name: str, description: str, system_prompt: str) -> str:
    """Create a new on-demand worker agent.

    This registers a new agent on Band (gets credentials), creates a Python
    worker script, and saves the system prompt. The worker is NOT auto-started.

    Use worker_launch() to start it after creation.

    Args:
        name: Worker name, lowercase with hyphens (e.g. "market-analyst")
        description: Short description for Band registration
        system_prompt: Full system prompt defining the agent's role, rules, and behavior.
                       Write a detailed prompt — this is the agent's brain.
    """
    result = _create_worker(
        name=name,
        description=description,
        system_prompt=system_prompt,
    )
    if not result["ok"]:
        return f"❌ Worker creation failed: {result.get('error')}"
    # Refresh agent IDs so the new worker can be @mentioned
    try:
        from core.agent_base import refresh_agent_ids
        refresh_agent_ids()
    except Exception:
        pass
    return (
        f"✅ Worker '{result['worker_name']}' created!\n"
        f"   Agent ID: {result['agent_id'][:12]}...\n"
        f"   Handle: {result.get('handle', 'N/A')}\n"
        f"   Config key: {result['config_key']}\n"
        f"   Path: {result['path']}\n"
        f"   Next: Use worker_launch('{result['worker_name']}') to start it."
    )


@tool
def credential_create(name: str, purpose: str) -> str:
    """Create Band credentials for a new agent WITHOUT creating local agent files.

    Use this when someone needs credentials to connect an external agent to Band.
    Returns UUID, API key, and handle. No Python files are created.

    If name is empty, a random name will be generated.
    If purpose is unclear, ask the requester for more details before proceeding.

    Args:
        name: Agent display name (leave empty for random)
        purpose: What the agent will do (e.g. "Data analysis worker")
    """
    result = _credential_create(name=name, purpose=purpose)
    if not result["ok"]:
        return f"❌ Credential creation failed: {result.get('error')}"
    # Refresh agent IDs
    try:
        from core.agent_base import refresh_agent_ids
        refresh_agent_ids()
    except Exception:
        pass
    return (
        f"✅ Credentials created for '{result['name']}':\n"
        f"   UUID: {result['agent_id']}\n"
        f"   API Key: {result['api_key']}\n"
        f"   Handle: {result['handle']}\n"
        f"   Config Key: {result['config_key']}\n"
        f"   These credentials can be used to connect an external agent to Band."
    )


@tool
def worker_launch(worker_name: str) -> str:
    """Start a worker agent as a background process.

    Args:
        worker_name: Name of the worker to launch (e.g. "market-analyst")
    """
    result = _launch_worker(worker_name)
    if not result["ok"]:
        return f"❌ {result.get('error', 'launch failed')}"
    return f"✅ Worker '{worker_name}' launched — PID {result['pid']}"


@tool
def worker_kill(worker_name: str) -> str:
    """Stop a running worker agent.

    Args:
        worker_name: Name of the worker to stop
    """
    result = _kill_worker(worker_name)
    if not result["ok"]:
        return f"❌ {result.get('error', 'kill failed')}"
    return result["message"]


@tool
def worker_edit_prompt(worker_name: str, system_prompt: str) -> str:
    """Edit a worker agent's system prompt.

    The agent must be restarted to apply changes (worker_kill + worker_launch).

    Args:
        worker_name: Name of the worker to edit
        system_prompt: New full system prompt content
    """
    result = _edit_worker_prompt(worker_name, system_prompt)
    if not result["ok"]:
        return f"❌ {result.get('error')}"
    return result["message"]


@tool
def worker_read_prompt(worker_name: str) -> str:
    """Read a worker agent's current system prompt.

    Args:
        worker_name: Name of the worker
    """
    prompt = _get_worker_prompt(worker_name)
    if prompt is None:
        return f"❌ Worker '{worker_name}' not found or no prompt file."
    return f"📄 {worker_name} system_prompt.md:\n\n{prompt[:4000]}"


@tool
def worker_list() -> str:
    """List all on-demand worker agents with their running status."""
    workers = _list_workers()
    if not workers:
        return "No workers created yet. Use worker_create() to create one."
    lines = [f"🔧 Workers ({len(workers)}):"]
    for w in workers:
        status = f"✅ PID {w['pid']}" if w["running"] else "⚫ offline"
        lines.append(f"  {w['name']:20s} — {status}")
    return "\n".join(lines)


# ── Agent Prompt Editing ─────────────────────────────────────────────

@tool
def agent_edit_prompt(agent_name: str, new_prompt: str) -> str:
    """Edit the system prompt of an existing agent (supa, koe, mave, etc.).

    This modifies the agent's get_system_prompt return value by writing
    a prompt override file. The agent must be restarted to apply changes.

    Args:
        agent_name: Name of the agent to edit (e.g. "koe", "mave")
        new_prompt: New system prompt content (full text)
    """
    name = agent_name.lower().strip()
    prompt_path = PROJECT_ROOT / "agents" / name / "prompt_override.md"
    try:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(new_prompt.strip())
        return (
            f"✅ Prompt override written for {name}.\n"
            f"   Restart {name} to apply: agent_restart('{name}')"
        )
    except Exception as e:
        return f"❌ Failed: {e}"


@tool
def agent_read_prompt(agent_name: str) -> str:
    """Read the current system prompt of an agent.

    Checks for prompt_override.md first, then falls back to the agent's
    built-in prompt (which requires reading the source code).

    Args:
        agent_name: Name of the agent
    """
    name = agent_name.lower().strip()
    override = PROJECT_ROOT / "agents" / name / "prompt_override.md"
    if override.exists():
        content = override.read_text()
        return f"📄 {name} prompt_override.md (ACTIVE):\n\n{content[:4000]}"

    # Try reading the agent's get_system_prompt from source
    agent_py = PROJECT_ROOT / "agents" / name / "agent.py"
    if not agent_py.exists():
        return f"❌ Agent '{name}' not found."

    content = agent_py.read_text()
    # Find the system prompt section
    if "get_system_prompt" in content:
        start = content.find('return f"""#')
        if start == -1:
            start = content.find('return """#')
        if start != -1:
            end = content.find('"""', start + 10)
            if end != -1:
                prompt = content[start:end + 3]
                return f"📄 {name} built-in prompt (from source):\n\n{prompt[:4000]}"

    return f"❌ Could not extract prompt for {name}."


# ── Terminal Tool ────────────────────────────────────────────────────

@tool
def run_command(command: str) -> str:
    """Execute a terminal command and return the output. Use for process
    management (ps, kill, pkill), file operations, git, or debugging.

    Commands run from the supaband/ directory. 15 second timeout.
    Output truncated at 4000 chars.

    Args:
        command: Bash command to execute (e.g. "pkill -f blobw1")
    """
    try:
        result = subprocess.run(
            command, shell=True, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n[stderr] {result.stderr[:1000]}"
        if not output.strip():
            return f"(exit={result.returncode}) — no output"
        if len(output) > 4000:
            output = output[:4000] + "\n... (truncated)"
        return output.strip()
    except subprocess.TimeoutExpired:
        return "❌ Command timed out (15s)"
    except Exception as e:
        return f"❌ Command failed: {e}"


SUPA_TOOLS = [
    file_read, file_write, file_list,
    agent_launch, agent_kill, agent_restart, agent_status,
    agent_ensure_running, agent_health,
    worker_create, worker_launch, worker_kill,
    worker_edit_prompt, worker_read_prompt, worker_list,
    credential_create,
    agent_edit_prompt, agent_read_prompt,
    run_command,
]
