"""Sink agent — dead agent used as a mention target to break conversation loops.

Band requires at least 1 @mention per message. When agents want to send a
terminal message (acknowledgment, status, final report) without triggering
another agent, they mention the Void sink agent instead. Void never polls
Band, has no LLM, and cannot respond.

The Void agent is created once via the Human API (register_my_agent) and
its ID is stored in agent_config.yaml under the 'sink_agent' key.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from core.config import load_agent_config, PROJECT_ROOT

log = logging.getLogger(__name__)

# Cached sink agent ID
_sink_id: Optional[str] = None


def get_sink_agent_id() -> str:
    """Return the Void sink agent UUID.

    Loads from agent_config.yaml. Raises if not configured.
    """
    global _sink_id
    if _sink_id:
        return _sink_id

    config = load_agent_config()
    entry = config.get("sink_agent", {})
    agent_id = str(entry.get("agent_id", ""))
    if not agent_id or agent_id == "your-void-uuid":
        raise ValueError(
            "Sink agent not configured. Run setup to create it:\n"
            "  python3 -c \"from core.sink_agent import create_sink_agent; create_sink_agent()\""
        )
    _sink_id = agent_id
    return _sink_id


def create_sink_agent() -> dict:
    """Create the Void sink agent via Human API.

    Stores the agent_id in agent_config.yaml. The API key is not needed
    since Void never polls — it only needs to exist as a participant.

    Returns:
        {"agent_id": str, "name": str}
    """
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    from thenvoi_rest import RestClient, AgentRegisterRequest
    import yaml

    human_key = os.getenv("BAND_HUMAN_API_KEY", "")
    if not human_key:
        raise ValueError("BAND_HUMAN_API_KEY not found in .env")

    client = RestClient(api_key=human_key, base_url="https://app.band.ai", timeout=30.0)

    resp = client.human_api_agents.register_my_agent(
        agent=AgentRegisterRequest(
            name="Void",
            description="Terminal message sink — accepts mentions but never responds. "
                        "Used to break agent conversation loops.",
        )
    )

    data = resp.data
    agent = data.agent
    if agent is None:
        raise ValueError("Agent creation returned None")
    agent_id = str(agent.id)
    log.info(f"Created Void sink agent: {agent_id}")

    # Save to config
    config_path = PROJECT_ROOT / "agent_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    config["sink_agent"] = {
        "name": "Void",
        "role": "Message sink — never responds",
        "handle": "",
        "agent_id": agent_id,
        "api_key": "none_needed",
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    global _sink_id
    _sink_id = agent_id

    return {"agent_id": agent_id, "name": "Void"}


def ensure_sink_agent() -> str:
    """Ensure sink agent exists, create if missing. Returns agent_id."""
    try:
        return get_sink_agent_id()
    except ValueError:
        log.info("Sink agent not found — creating...")
        result = create_sink_agent()
        return result["agent_id"]
