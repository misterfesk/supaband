#!/usr/bin/env python3
"""Stop all worker agents.

Usage:
    python3 scripts/stop_workers.py
    python3 scripts/stop_workers.py quill  # stop specific worker
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.worker_factory import kill_worker, list_workers

ALL_WORKERS = ["quill", "pulse", "canvas"]

def main():
    workers = sys.argv[1:] if len(sys.argv) > 1 else ALL_WORKERS
    print(f"🔧 Stopping workers: {', '.join(workers)}")
    for name in workers:
        result = kill_worker(name)
        if result["ok"]:
            print(f"  ✅ {name}: {result['message']}")
        else:
            print(f"  ❌ {name}: {result.get('error', 'failed')}")

if __name__ == "__main__":
    main()
