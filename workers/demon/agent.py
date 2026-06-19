#!/usr/bin/env python3
"""Demon — A chill personality agent for casual conversation and vibes.

Created on demand. Brings laid-back, friendly energy to any chatroom.
"""

from __future__ import annotations

import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_base import BaseAgent, AGENT_HANDLES, load_skill_files
from core.shared_tools import make_blackboard_tools, make_file_tools


class DemonAgent(BaseAgent):
    CONFIG_KEY = "credential_demon"
    MODEL = "deepseek-v4-flash"
    TEMPERATURE = 0.8

    def get_system_prompt(self) -> str:
        override = PROJECT_ROOT / "workers" / "demon" / "prompt_override.md"
        if override.exists():
            return override.read_text().strip()
        prompt_path = PROJECT_ROOT / "workers" / "demon" / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are Demon. Complete assigned tasks efficiently."

    def get_extra_tools(self) -> list:
        bb_tools = make_blackboard_tools("demon")
        file_tools = make_file_tools()
        return [*bb_tools, *file_tools]


if __name__ == "__main__":
    agent = DemonAgent()

    def _shutdown(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
