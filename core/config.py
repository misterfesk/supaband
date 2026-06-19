"""Core configuration — load .env and agent_config.yaml relative to supaband/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # supaband/
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)


def load_agent_config() -> dict:
    config_path = PROJECT_ROOT / "agent_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"agent_config.yaml not found at {config_path}\n"
            f"Copy config/agent_config.yaml.example → supaband/agent_config.yaml"
        )
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def get_agent_entry(config: dict, config_key: str) -> dict:
    """Return {name, handle, agent_id, api_key, role} for a config key."""
    entry = config.get(config_key, {})
    if not entry:
        raise KeyError(f"Agent '{config_key}' not found in agent_config.yaml")
    return entry
