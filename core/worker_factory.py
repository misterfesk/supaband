"""Worker agent factory — create, configure, and spawn on-demand agents.

Two modes:
  1. credential_create(name, purpose) — Register on Band, return credentials only.
     No local agent files created. Used when someone just needs Band credentials.
  2. create_worker(name, description, system_prompt, ...) — Full pipeline:
     Register on Band + create local agent files + save to config.

Supa and Koe use this module to:
1. Register a new agent on Band via Human API (returns agent_id + api_key)
2. Create a Python worker script from a placeholder template
3. Save credentials to agent_config.yaml
4. Launch the worker as a background process

Workers are lightweight agents that:
- Have a single-purpose system prompt (set at creation time)
- Can be given specific tools (band tools + file tools + blackboard by default)
- Poll Band for messages addressed to them
- Can be killed/edited/restarted by Supa or their manager

Worker files live in supaband/workers/<name>/ with:
  - agent.py (generated from template with placeholders filled)
  - system_prompt.md (editable — Supa/managers can change this)
  - data/ (logs, pid, exports)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from core.config import PROJECT_ROOT, load_agent_config

log = logging.getLogger(__name__)

WORKERS_DIR = PROJECT_ROOT / "workers"
WORKERS_DIR.mkdir(parents=True, exist_ok=True)


# ── Band Agent Registration ──────────────────────────────────────────

def register_band_agent(name: str, description: str) -> dict[str, str]:
    """Register a new external agent on Band via Human API.

    Returns: {"agent_id": str, "api_key": str, "name": str}
    Raises on failure.
    """
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    from thenvoi_rest import RestClient, AgentRegisterRequest

    human_key = os.getenv("BAND_HUMAN_API_KEY", "")
    if not human_key:
        raise ValueError("BAND_HUMAN_API_KEY not found in .env")

    client = RestClient(api_key=human_key, base_url="https://app.band.ai", timeout=30.0)
    resp = client.human_api_agents.register_my_agent(
        agent=AgentRegisterRequest(name=name, description=description)
    )
    data = resp.data
    agent = data.agent
    if agent is None:
        raise ValueError("Band returned None agent")
    creds = data.credentials
    if creds is None or not creds.api_key:
        raise ValueError("Band returned no API key")

    return {
        "agent_id": str(agent.id),
        "api_key": str(creds.api_key),
        "name": str(agent.name or name),
    }


def save_worker_config(config_key: str, name: str, agent_id: str, api_key: str,
                       description: str = "", handle: str = "") -> None:
    """Save a worker agent's credentials to agent_config.yaml."""
    config_path = PROJECT_ROOT / "agent_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    if not handle:
        handle = _make_handle(name)

    config[config_key] = {
        "name": name,
        "description": description,
        "handle": handle,
        "agent_id": agent_id,
        "api_key": api_key,
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    log.info(f"Saved worker config: {config_key} → {name} ({agent_id[:12]}...)")


def _make_handle(name: str) -> str:
    """Generate a Band handle from a name: @zoha/<slug>-bz."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return f"@zoha/{slug}-bz"


def credential_create(name: str, purpose: str) -> dict[str, Any]:
    """Create Band credentials for a new agent WITHOUT creating local agent files.

    This registers a new agent on Band and returns the credentials (UUID, API key, handle).
    No Python files are created — the caller gets credentials to use externally.

    Args:
        name: Agent display name (e.g. "Market Analyst")
        purpose: Short description of the agent's purpose

    Returns:
        {"ok": bool, "name": str, "agent_id": str, "api_key": str, "handle": str}
    """
    display_name = name.strip()
    if not display_name:
        import random, string
        display_name = "agent-" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

    try:
        creds = register_band_agent(
            name=display_name,
            description=purpose or "On-demand agent",
        )
    except Exception as e:
        return {"ok": False, "error": f"Band registration failed: {e}"}

    handle = _make_handle(display_name)
    config_key = f"credential_{re.sub(r'[^a-z0-9]+', '_', display_name.lower()).strip('_')}"

    # Save to config so credentials are persisted
    try:
        save_worker_config(
            config_key=config_key,
            name=creds["name"],
            agent_id=creds["agent_id"],
            api_key=creds["api_key"],
            description=purpose,
            handle=handle,
        )
    except Exception as e:
        log.warning(f"Config save failed (credentials still returned): {e}")

    return {
        "ok": True,
        "name": creds["name"],
        "agent_id": creds["agent_id"],
        "api_key": creds["api_key"],
        "handle": handle,
        "config_key": config_key,
    }


# ── Worker Template (placeholder-based) ──────────────────────────────

WORKER_TEMPLATE = '''#!/usr/bin/env python3
"""{worker_name} — {role_description}

Auto-generated by the worker factory. Reads its system prompt from
workers/{worker_name}/system_prompt.md at startup.

Supa or the department manager can edit the system prompt file to change
this agent's behavior, then restart it to apply changes.
"""

from __future__ import annotations

import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_base import BaseAgent, AGENT_HANDLES, load_skill_files
from core.shared_tools import make_blackboard_tools
{tools_import}


class {class_name}Agent(BaseAgent):
    CONFIG_KEY = "{config_key}"
    MODEL = "{model}"
    TEMPERATURE = {temperature}

    def get_system_prompt(self) -> str:
        # Check for prompt override (set by agent_edit_prompt tool)
        override = PROJECT_ROOT / "workers" / "{worker_name}" / "prompt_override.md"
        if override.exists():
            return override.read_text().strip()
        prompt_path = PROJECT_ROOT / "workers" / "{worker_name}" / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are {worker_name}. Complete assigned tasks efficiently."

    def get_extra_tools(self) -> list:
        bb_tools = make_blackboard_tools("{worker_name}")
        return [*bb_tools{tools_list}]


if __name__ == "__main__":
    agent = {class_name}Agent()

    def _shutdown(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
'''


def _to_class_name(name: str) -> str:
    """Convert 'market-analyst' → 'MarketAnalyst'."""
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


# ── Worker Lifecycle ─────────────────────────────────────────────────

def create_worker(name: str, description: str, system_prompt: str,
                  model: str = "deepseek-v4-flash",
                  temperature: float = 0.4,
                  tools_import: str = "",
                  tools_list: str = "",
                  department: str = "") -> dict[str, Any]:
    """Full worker creation pipeline.

    1. Register agent on Band → get credentials
    2. Save credentials to agent_config.yaml
    3. Create worker directory + agent.py + system_prompt.md
    4. Return summary

    Args:
        name: Worker name (lowercase, hyphens ok, e.g. "market-analyst")
        description: Short description for Band registration
        system_prompt: Full system prompt text for the agent
        model: LLM model to use (default: deepseek-v4-flash)
        temperature: LLM temperature
        tools_import: Optional Python import line for extra tools (e.g. "from agents.marketing.tools import MARKETING_WORKER_TOOLS")
        tools_list: Optional tools list extension (e.g. ", *MARKETING_WORKER_TOOLS")
        department: Department name for organization

    Returns:
        {"ok": bool, "worker_name": str, "agent_id": str, "config_key": str, "path": str}
    """
    worker_name = name.lower().strip()
    class_name = _to_class_name(worker_name)
    config_key = f"worker_{worker_name.replace('-', '_')}"

    # 1. Register on Band
    try:
        creds = register_band_agent(
            name=worker_name.replace("-", " ").title(),
            description=description,
        )
    except Exception as e:
        return {"ok": False, "error": f"Band registration failed: {e}"}

    handle = _make_handle(worker_name.replace("-", " ").title())

    # 2. Save to config
    try:
        save_worker_config(
            config_key=config_key,
            name=creds["name"],
            agent_id=creds["agent_id"],
            api_key=creds["api_key"],
            description=description,
            handle=handle,
        )
    except Exception as e:
        return {"ok": False, "error": f"Config save failed: {e}"}

    # 3. Create worker directory + files
    worker_dir = WORKERS_DIR / worker_name
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # agent.py — fill template placeholders
    agent_code = WORKER_TEMPLATE.format(
        worker_name=worker_name,
        class_name=class_name,
        config_key=config_key,
        model=model,
        temperature=temperature,
        role_description=description,
        tools_import=tools_import,
        tools_list=tools_list,
    )
    (worker_dir / "agent.py").write_text(agent_code)

    # system_prompt.md
    (worker_dir / "system_prompt.md").write_text(system_prompt.strip())

    log.info(f"Created worker: {worker_name} at {worker_dir}")
    return {
        "ok": True,
        "worker_name": worker_name,
        "agent_id": creds["agent_id"],
        "handle": handle,
        "config_key": config_key,
        "path": str(worker_dir.relative_to(PROJECT_ROOT)),
    }


def edit_worker_prompt(worker_name: str, system_prompt: str) -> dict:
    """Edit a worker agent's system prompt.

    The agent must be restarted to apply changes.
    """
    worker_name = worker_name.lower().strip()
    prompt_path = WORKERS_DIR / worker_name / "system_prompt.md"
    if not prompt_path.parent.exists():
        return {"ok": False, "error": f"Worker '{worker_name}' not found."}
    try:
        prompt_path.write_text(system_prompt.strip())
        return {"ok": True, "message": f"Prompt updated. Restart {worker_name} to apply."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_worker_prompt(worker_name: str) -> str | None:
    """Read a worker's current system prompt."""
    prompt_path = WORKERS_DIR / worker_name.lower().strip() / "system_prompt.md"
    if not prompt_path.exists():
        return None
    return prompt_path.read_text()


def launch_worker(worker_name: str) -> dict:
    """Launch a worker agent as a background process."""
    worker_name = worker_name.lower().strip()
    agent_py = WORKERS_DIR / worker_name / "agent.py"
    if not agent_py.exists():
        return {"ok": False, "error": f"Worker '{worker_name}' not found."}

    venv = PROJECT_ROOT.parent / ".venv" / "bin" / "python3"
    python_bin = str(venv) if venv.exists() else sys.executable

    logfile = WORKERS_DIR / worker_name / "data" / "logs" / f"startup-{datetime.now():%Y%m%d-%H%M%S}.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(logfile, "a") as lf:
            proc = subprocess.Popen(
                [python_bin, str(agent_py)],
                cwd=str(PROJECT_ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    time.sleep(2)
    alive = proc.poll() is None
    return {
        "ok": alive,
        "pid": proc.pid,
        "worker_name": worker_name,
        "log": str(logfile.relative_to(PROJECT_ROOT)),
    }


def kill_worker(worker_name: str) -> dict:
    """Kill a worker agent process."""
    worker_name = worker_name.lower().strip()
    try:
        result = subprocess.run(
            ["pkill", "-f", f"workers/{worker_name}/agent.py"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return {"ok": True, "message": f"Worker '{worker_name}' stopped."}
        return {"ok": False, "error": f"No process found for '{worker_name}'."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_workers() -> list[dict]:
    """List all created workers with status."""
    workers = []
    if not WORKERS_DIR.exists():
        return workers

    for d in sorted(WORKERS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        agent_py = d / "agent.py"
        prompt = d / "system_prompt.md"
        if not agent_py.exists():
            continue

        # Check if running
        try:
            check = subprocess.run(
                ["pgrep", "-f", f"workers/{d.name}/agent.py"],
                capture_output=True, text=True, timeout=3,
            )
            running = check.returncode == 0
            pid = int(check.stdout.strip().split("\n")[0]) if running and check.stdout.strip() else None
        except Exception:
            running = False
            pid = None

        workers.append({
            "name": d.name,
            "running": running,
            "pid": pid,
            "has_prompt": prompt.exists(),
            "path": str(d.relative_to(PROJECT_ROOT)),
        })
    return workers
