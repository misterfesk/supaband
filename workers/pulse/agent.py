#!/usr/bin/env python3
"""Pulse — SEO & Digital Marketing Analyst

Marketing team specialist. Keyword research, SEO optimization, digital ad
campaign management, analytics reporting. Reports to Mave (Marketing Manager).
"""

from __future__ import annotations

import sys
import signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_base import BaseAgent, AGENT_HANDLES, load_skill_files
from core.shared_tools import make_blackboard_tools, make_file_tools, make_web_tools
from core.webui_tools import make_webui_tools


class PulseAgent(BaseAgent):
    CONFIG_KEY = "seo_analyst"
    MODEL = "deepseek-v4-flash"
    TEMPERATURE = 0.3

    def get_system_prompt(self) -> str:
        override = PROJECT_ROOT / "workers" / "pulse" / "prompt_override.md"
        if override.exists():
            return override.read_text().strip()
        prompt_path = PROJECT_ROOT / "workers" / "pulse" / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are Pulse. Complete assigned tasks efficiently."

    def get_extra_tools(self) -> list:
        bb_tools = make_blackboard_tools("pulse")
        file_tools = make_file_tools()
        web_tools = make_web_tools()
        webui_tools = make_webui_tools("pulse")
        return [*bb_tools, *file_tools, *web_tools, *webui_tools]


if __name__ == "__main__":
    agent = PulseAgent()

    def _shutdown(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
