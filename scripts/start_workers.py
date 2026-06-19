#!/usr/bin/env python3
"""Start all marketing worker agents (Quill, Pulse, Canvas).

Usage:
    python3 scripts/start_workers.py
    python3 scripts/start_workers.py quill pulse  # start specific workers
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.worker_factory import launch_worker, list_workers

ALL_WORKERS = ["quill", "pulse", "canvas"]

def main():
    workers = sys.argv[1:] if len(sys.argv) > 1 else ALL_WORKERS
    print(f"🔧 Starting workers: {', '.join(workers)}")
    for name in workers:
        result = launch_worker(name)
        if result["ok"]:
            print(f"  ✅ {name}: PID {result['pid']}")
        else:
            print(f"  ❌ {name}: {result.get('error', 'failed')}")

    # Show status
    print("\n📋 Worker status:")
    for w in list_workers():
        status = f"✅ PID {w['pid']}" if w["running"] else "⚫ offline"
        print(f"  {w['name']:20s} — {status}")

if __name__ == "__main__":
    main()
