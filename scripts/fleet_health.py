#!/usr/bin/env python3
"""Fleet health check — comprehensive status of all agents and workers.

Usage:
    python3 scripts/fleet_health.py
"""

import sys
import json
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import fleet
from core.worker_factory import list_workers

CORE_AGENTS = ["supa", "koe", "mave", "forge"]

def check_health(name, port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def main():
    print("═" * 60)
    print("  FLEET HEALTH CHECK")
    print("═" * 60)

    # Core agents
    print("\n📊 Core Agents:")
    for name in CORE_AGENTS:
        port = fleet.AGENT_PORTS.get(name, 0)
        health = check_health(name, port)
        if health:
            print(f"  ✅ {name:8s} — PID {health['pid']:6d} | cycles={health['cycles']:3d} | "
                  f"msgs={health['messages_processed']:3d} | uptime={health['uptime_seconds']}s | "
                  f"model={health['model']}")
        else:
            pid = fleet.agent_pid(name)
            if pid:
                print(f"  ⚠️  {name:8s} — PID {pid} (health endpoint not responding)")
            else:
                print(f"  ❌ {name:8s} — not running")

    # Workers
    print("\n🔧 Worker Agents:")
    workers = list_workers()
    if not workers:
        print("  (no workers created)")
    for w in workers:
        status = f"✅ PID {w['pid']}" if w["running"] else "⚫ offline"
        prompt = "📝" if w.get("has_prompt") else "❌ no prompt"
        print(f"  {w['name']:20s} — {status} {prompt}")

    # Blackboard
    print("\n📋 Blackboard:")
    try:
        from core.blackboard import get_blackboard
        bb = get_blackboard()
        docs = bb.list_all()
        files = bb.list_files()
        print(f"  Documents: {len(docs)}")
        print(f"  Files: {len(files)}")
        for d in docs[:5]:
            pin = "📌 " if d.get("is_pinned") else "  "
            print(f"  {pin}{d['key']:30s} — {d['title']} ({d['department']})")
    except Exception as e:
        print(f"  ❌ Error: {e}")

    print("\n" + "═" * 60)

if __name__ == "__main__":
    main()
