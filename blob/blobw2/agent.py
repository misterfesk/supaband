#!/usr/bin/env python3
"""Blobw2 — Blob Consumer Worker 2 (Skeptical Buyer persona).

Spawned by Koe's blob_launch_workers() tool for shadow testing sessions.
Reads personality from blob/blobw2/personality.md (written by Koe before each session).

Usage:
    python3 blob/blobw2/agent.py
"""

from __future__ import annotations

import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.blob_agent_base import BlobWorkerAgent


class Blobw2Agent(BlobWorkerAgent):
    CONFIG_KEY = "blob_worker_2"
    MODEL = "deepseek/deepseek-chat"
    BLOB_NAME = "blobw2"
    NEXT_AGENT = "blobw3"
    AUTO_RESPOND_TARGET = "blobw3"


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = Blobw2Agent()

    def _shutdown(sig, frame):
        print(f"\nBlobw2 shutting down...")
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
