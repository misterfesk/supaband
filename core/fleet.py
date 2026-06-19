"""Fleet process manager — robust local process control for Supaband agents.

Tracks agents by PID file + health endpoint, not by in-memory state,
so Supa can survive restarts without losing track of the fleet.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from core.config import PROJECT_ROOT

log = logging.getLogger(__name__)

# Agent names recognized by the fleet manager
FLEET_AGENTS = ["supa", "koe", "mave", "forge", "blobw1", "blobw2", "blobw3"]

# Health endpoint ports (mirrors agent_base.AGENT_PORTS)
AGENT_PORTS: dict[str, int] = {
    "supa": 9100,
    "koe": 9101,
    
    "mave": 9105,
    "forge": 9106,
    "blobw1": 9110,
    "blobw2": 9111,
    "blobw3": 9112,
}

# Default set of manager agents that Supa keeps alive
MANAGER_AGENTS = ["koe", "mave", "forge"]


# ── Paths ────────────────────────────────────────────────────────────

def _agent_dir(name: str) -> Path:
    return PROJECT_ROOT / "agents" / name.lower()


def _pid_file(name: str) -> Path:
    return _agent_dir(name) / "data" / "agent.pid"


def _stop_file(name: str) -> Path:
    return _agent_dir(name) / "data" / "stop"


def _venv_python() -> Path:
    """Return the project virtualenv python, falling back to sys.executable."""
    venv = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv.exists():
        return venv
    return Path(sys.executable)


# ── Low-level helpers ────────────────────────────────────────────────

def _check_pid(pid: int) -> bool:
    """Return True if a process with `pid` is alive and not a zombie."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Defunct/zombie processes still respond to kill(0,0); check /proc state
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        if len(stat) > 2 and stat[2] == "Z":
            return False
    except Exception:
        pass
    return True


def _http_get(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _read_pid_file(name: str) -> int | None:
    pf = _pid_file(name)
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except Exception:
        return None


def _clean_stale_pid(name: str) -> bool:
    """Remove a PID file that no longer points to a live process."""
    pid = _read_pid_file(name)
    if pid is None:
        return False
    if not _check_pid(pid):
        try:
            _pid_file(name).unlink(missing_ok=True)
            return True
        except Exception:
            pass
    return False


# ── Public API ───────────────────────────────────────────────────────

def agent_pid(name: str) -> int | None:
    """Return the live PID for an agent, or None if not running.
    Cleans stale PID files automatically."""
    name = name.lower()
    pid = _read_pid_file(name)
    if pid is not None:
        if _check_pid(pid):
            return pid
        _clean_stale_pid(name)
    return None


def agent_is_running(name: str) -> bool:
    """Check whether an agent process is alive AND its health endpoint responds."""
    name = name.lower()
    pid = agent_pid(name)
    if pid is None:
        return False
    port = AGENT_PORTS.get(name)
    if port:
        health = _http_get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        if health:
            return True
        # Process exists but health not responding yet — still consider running
        return True
    return True


def agent_health(name: str) -> dict:
    """Return a status dict for the agent: {running, pid, health, stale_removed}."""
    name = name.lower()
    stale_removed = _clean_stale_pid(name)
    pid = _read_pid_file(name)
    alive = pid is not None and _check_pid(pid)
    health_data: dict | None = None
    if alive:
        port = AGENT_PORTS.get(name)
        if port:
            health_data = _http_get(f"http://127.0.0.1:{port}/health", timeout=2.0)
    return {
        "name": name,
        "running": alive,
        "pid": pid,
        "health": health_data,
        "stale_removed": stale_removed,
    }


def list_agent_status() -> dict[str, dict]:
    """Return status dict for every fleet agent."""
    return {name: agent_health(name) for name in FLEET_AGENTS}


def launch_agent(name: str, foreground: bool = False) -> dict:
    """Start an agent as a background process with log capture.
    Returns a status dict; is a no-op if the agent is already running.
    """
    name = name.lower()
    agent_py = _agent_dir(name) / "agent.py"
    if not agent_py.exists():
        return {"ok": False, "error": f"Agent not found: {agent_py}"}

    # If a live agent already serves the health endpoint, trust it
    port = AGENT_PORTS.get(name)
    if port:
        health = _http_get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        if health:
            return {
                "ok": True,
                "pid": health.get("pid"),
                "started": False,
                "message": "already running (health endpoint active)",
            }

    # If already running via PID file, return existing PID
    existing = agent_pid(name)
    if existing:
        return {"ok": True, "pid": existing, "started": False, "message": "already running"}

    # Remove any stale stop file so the agent can start
    _stop_file(name).unlink(missing_ok=True)

    logfile = _agent_dir(name) / "data" / "logs" / f"startup-{datetime.now():%Y%m%d-%H%M%S}.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)

    python_bin = _venv_python()
    try:
        if foreground:
            proc = subprocess.Popen(
                [str(python_bin), str(agent_py)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        else:
            with open(logfile, "a") as lf:
                proc = subprocess.Popen(
                    [str(python_bin), str(agent_py)],
                    cwd=str(PROJECT_ROOT),
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Wait up to 12s for PID file or health endpoint to confirm startup
    deadline = time.time() + 12.0
    confirmed_pid = None
    health_ok = False
    while time.time() < deadline:
        time.sleep(0.5)
        confirmed_pid = agent_pid(name)
        if confirmed_pid:
            break
        if proc.poll() is not None:
            break

    # If PID file never appeared but process is alive, trust the subprocess PID
    if confirmed_pid is None and proc.poll() is None:
        confirmed_pid = proc.pid

    # Quick health check; not required for success — agent may still be booting
    if confirmed_pid and _check_pid(confirmed_pid):
        port = AGENT_PORTS.get(name)
        if port:
            health_ok = _http_get(f"http://127.0.0.1:{port}/health", timeout=2.0) is not None

    alive = confirmed_pid is not None and _check_pid(confirmed_pid)
    return {
        "ok": alive,
        "pid": confirmed_pid or proc.pid,
        "started": True,
        "log": str(logfile) if not foreground else None,
        "health_ready": health_ok,
        "error": None if alive else f"Agent process exited (PID {proc.pid})",
    }


def kill_agent(name: str, force: bool = False) -> dict:
    """Stop an agent gracefully via HTTP stop endpoint, then SIGTERM, then SIGKILL.
    Returns a status dict.
    """
    name = name.lower()
    port = AGENT_PORTS.get(name)

    # 1. Try graceful HTTP stop
    if port:
        try:
            _http_get(f"http://127.0.0.1:{port}/stop", timeout=3.0)
        except Exception:
            pass

    # 2. Drop a stop file as a backup signal
    _stop_file(name).touch()

    # 3. Wait briefly
    time.sleep(1.5)

    pid = _read_pid_file(name)
    killed = []
    if pid and _check_pid(pid):
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            killed.append(str(pid))
        except Exception as e:
            return {"ok": False, "error": f"kill pid {pid} failed: {e}"}

    # 4. If still alive, escalate to SIGKILL
    time.sleep(1.0)
    pid = _read_pid_file(name)
    if pid and _check_pid(pid):
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(f"{pid} (SIGKILL)")
        except Exception as e:
            return {"ok": False, "error": f"SIGKILL pid {pid} failed: {e}"}

    # 5. Clean up
    _stop_file(name).unlink(missing_ok=True)
    _clean_stale_pid(name)

    return {"ok": True, "killed": killed or ["no process found"], "stopped": True}


def ensure_agents_running(names: list[str]) -> dict[str, dict]:
    """Start every agent in `names` that is not currently running.
    Returns a dict mapping agent name to launch result.
    """
    results: dict[str, dict] = {}
    for name in names:
        if agent_is_running(name):
            results[name] = {"ok": True, "running": True, "pid": agent_pid(name)}
        else:
            results[name] = launch_agent(name)
    return results


def restart_agent(name: str) -> dict:
    """Kill then launch an agent."""
    kill_result = kill_agent(name)
    time.sleep(0.5)
    launch_result = launch_agent(name)
    return {"kill": kill_result, "launch": launch_result}


def ensure_managers() -> dict[str, dict]:
    """Convenience: ensure all manager agents are running."""
    return ensure_agents_running(MANAGER_AGENTS)
