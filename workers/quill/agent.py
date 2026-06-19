#!/usr/bin/env python3
"""Quill — Content Strategist & Copywriter

Marketing team specialist. Writes marketing copy, blog posts, social media
content, email campaigns, and ad text. Reports to Mave (Marketing Manager).
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


class QuillAgent(BaseAgent):
    CONFIG_KEY = "content_strategist"
    MODEL = "deepseek-v4-flash"
    TEMPERATURE = 0.6

    def get_system_prompt(self) -> str:
        override = PROJECT_ROOT / "workers" / "quill" / "prompt_override.md"
        if override.exists():
            return override.read_text().strip()
        prompt_path = PROJECT_ROOT / "workers" / "quill" / "system_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text().strip()
        return "You are Quill. Complete assigned tasks efficiently."

    def get_extra_tools(self) -> list:
        bb_tools = make_blackboard_tools("quill")
        file_tools = make_file_tools()
        webui_tools = make_webui_tools("quill")
        return [*bb_tools, *file_tools, *webui_tools]


if __name__ == "__main__":
    agent = QuillAgent()

    def _shutdown(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    agent.run()
