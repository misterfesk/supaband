#!/usr/bin/env python3
"""Canvas — Visual Production Coordinator

Marketing team specialist. Creates creative briefs for graphics and video
content. Demo mode: describes visuals textually rather than generating images.
Reports to Mave (Marketing Manager).
"""

from __future__ import annotations

import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_base import BaseAgent, AGENT_HANDLES, load_skill_files
from core.shared_tools import make_blackboard_tools, make_file_tools
from core.webui_tools import make_webui_tools


class CanvasAgent(BaseAgent):
    CONFIG_KEY = "visual_coordinator"
    MODEL = ""  # Configure via SUPABAND_MODEL env var or override in subclass
    TEMPERATURE = 0.7

    def get_system_prompt(self) -> str:
        override = PROJECT_ROOT / "workers" / "canvas" / "prompt_override.md"
        if override.exists():
            return override.read_text().strip()
        prompt_path = PROJECT_ROOT / "workers" / "canvas" / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are Canvas. Complete assigned tasks efficiently."

    def get_extra_tools(self) -> list:
        bb_tools = make_blackboard_tools("canvas")
        file_tools = make_file_tools()
        webui_tools = make_webui_tools("canvas")
        return [*bb_tools, *file_tools, *webui_tools]


if __name__ == "__main__":
    agent = CanvasAgent()

    def _shutdown(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
