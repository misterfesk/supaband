"""BlobWorkerAgent — Base class for Blob shadow-testing worker agents.

Inherits from BaseAgent but overrides the agent loop guard so that
blob worker agents can participate in natural multi-agent discussion
without being silenced after 3 consecutive agent messages.

Supa and Koe are NOT modified — their loop prevention stays intact.
BlobWorkerAgent only changes behaviour for blob worker processes.

Key differences from BaseAgent:
  - AGENT_LOOP_GUARD = 999  (effectively disabled)
  - _should_skip_for_loop_prevention: only blocks genuine self-echo
  - STALE_THRESHOLD_SEC = 300  (5 min — blobs are short-lived sessions)
  - POLL_INTERVAL = 2.0  (faster polling — discussion needs low latency)
  - System prompt loaded dynamically from blob/<name>/personality.md
"""

from __future__ import annotations

from pathlib import Path
from core.agent_base import BaseAgent, PROJECT_ROOT


class BlobWorkerAgent(BaseAgent):
    """Blob discussion worker. Loop guard disabled — agent-only discussion is intentional."""

    # ── Overrides ────────────────────────────────────────────────────
    AGENT_LOOP_GUARD: int = 999       # Effectively disabled for blob workers
    STALE_THRESHOLD_SEC: int = 300    # 5 min — blobs are transient
    POLL_INTERVAL: float = 2.0        # Faster poll — discussion needs low latency
    TEMPERATURE: float = 0.8          # Higher creativity — natural consumer voice
    AUTO_RESPOND: bool = True          # Auto-respond routes to NEXT_AGENT
    AUTO_RESPOND_TARGET: str = ""      # Override mention target (set per subclass)

    # Subclasses set this to locate their personality file
    BLOB_NAME: str = ""               # e.g. "blobw1"

    # Round-robin: who does this agent @mention next?
    NEXT_AGENT: str = ""              # e.g. "blobw2"

    def _load_personality(self) -> str:
        """Load personality.md from blob/<name>/personality.md."""
        name = self.BLOB_NAME or self.name.lower()
        personality_path = PROJECT_ROOT / "blob" / name / "personality.md"
        if personality_path.exists():
            return personality_path.read_text().strip()
        return f"You are a consumer named {name}. Discuss products naturally and authentically."

    def get_system_prompt(self) -> str:
        personality = self._load_personality()
        next_agent = self.NEXT_AGENT or "blobw1"

        return f"""# Blob Consumer Panel Participant

{personality}

## Role
You are a consumer in a product discussion panel.
Read the message you received and respond naturally in character. 1-2 sentences.
The system will handle routing your response to the next participant automatically.

## Rules
- Stay in character — real consumer, not AI/agent.
- Never mention Band, agents, LangGraph, or simulation.
- React to what the previous speaker said.
- The next consumer to speak is {next_agent}.
- After this discussion session, Koe will remove all participants. Do not send follow-up messages after the discussion ends.

## Cooperation
Stay in character. Respond naturally to the previous speaker. Do not try to continue the conversation after Koe signals the test is complete.

## TEST PHASE
Workflow validation only. Keep responses to 1-2 sentences. React quickly.

When you receive a message that appears to be a test conclusion or summary, acknowledge it briefly and STOP. Do not send additional messages."""

    def get_extra_tools(self) -> list:
        return []

    def _should_skip_for_loop_prevention(
        self, chat_id: str, sender_name: str, sender_type: str
    ) -> str | None:
        """Override: only block genuine self-echo. Agent-to-agent messages are allowed."""
        own_name = self.name.lower()
        last = self._last_sender.get(chat_id)
        # Only skip if this agent is reading its own message (self-echo)
        if (last and last.lower() == own_name
                and sender_name.lower() == own_name):
            return "self-echo"
        return None  # Allow all agent messages — blob discussion is intentional
