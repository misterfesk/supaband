#!/usr/bin/env python3
"""
Supaband Automated Setup — registers all agents on Band, generates configs.

Usage:
    python3 setup.py              Interactive mode (asks for keys)
    python3 setup.py --help       Show options
    python3 setup.py --non-interactive --openai-key KEY --openai-base URL --band-human-key KEY

This script:
    1. Sets up Python venv and installs dependencies
    2. Registers ALL 12 agents on Band via Human API
    3. Generates agent_config.yaml with all credentials
    4. Generates .env with LLM provider settings
    5. Creates data directories
"""

from __future__ import annotations

import os
import sys
import time
import subprocess
import re
import secrets
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Agent definitions ────────────────────────────────────────────────

AGENTS = [
    {
        "config_key": "supervisor_agent",
        "name": "Supa",
        "role": "CEO & Supervisor — delegates tasks, manages fleet, interacts with users",
        "handle": "@zoha/supa-bz",
    },
    {
        "config_key": "research_manager",
        "name": "Koe",
        "role": "Research Department Manager — market research, competitor analysis, data synthesis",
        "handle": "@zoha/koe-bz",
    },
    {
        "config_key": "marketing_manager",
        "name": "Mave",
        "role": "Marketing & Digital Production Manager — coordinates content, SEO, and visual production",
        "handle": "@zoha/mave-bz",
    },
    {
        "config_key": "operations_manager",
        "name": "Forge",
        "role": "Operations Department Manager — resource allocation, process optimization, cross-department coordination",
        "handle": "@zoha/forge-bz",
    },
    {
        "config_key": "sink_agent",
        "name": "Void",
        "role": "Message sink — never responds (loop prevention dead-end target)",
        "handle": "",
    },
    {
        "config_key": "blob_worker_1",
        "name": "Blobw1",
        "role": "Blob Consumer Worker — Early Adopter persona for shadow testing",
        "handle": "@zoha/blob-worker-1",
    },
    {
        "config_key": "blob_worker_2",
        "name": "Blobw2",
        "role": "Blob Consumer Worker — Skeptical Buyer persona for shadow testing",
        "handle": "@zoha/blob-worker-2",
    },
    {
        "config_key": "blob_worker_3",
        "name": "Blobw3",
        "role": "Blob Consumer Worker — Price-Sensitive persona for shadow testing",
        "handle": "@zoha/blob-worker-3",
    },
    {
        "config_key": "content_strategist",
        "name": "Quill",
        "role": "Content Strategist & Copywriter — writes marketing copy, blog posts, social media content, email campaigns",
        "handle": "@zoha/quill-bz",
    },
    {
        "config_key": "seo_analyst",
        "name": "Pulse",
        "role": "SEO & Digital Marketing Analyst — keyword research, SEO optimization, digital ad campaign management, analytics",
        "handle": "@zoha/pulse-bz",
    },
    {
        "config_key": "visual_coordinator",
        "name": "Canvas",
        "role": "Visual Production Coordinator — creates creative briefs for graphics and video content",
        "handle": "@zoha/canvas-bz",
    },
    {
        "config_key": "credential_dataminer",
        "name": "DataMiner",
        "role": "Data analysis and mining specialist",
        "handle": "@zoha/dataminer-bz",
    },
]

# ── Helpers ──────────────────────────────────────────────────────────

C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_RESET = "\033[0m"

def ok(msg: str) -> str:
    return f"{C_GREEN}✓{C_RESET} {msg}"

def info(msg: str) -> str:
    return f"{C_CYAN}→{C_RESET} {msg}"

def warn(msg: str) -> str:
    return f"{C_YELLOW}⚠{C_RESET} {msg}"

def err(msg: str) -> str:
    return f"{C_RED}✗{C_RESET} {msg}"

def section(title: str):
    print(f"\n{C_BOLD}{'─'*60}{C_RESET}")
    print(f"{C_BOLD}  {title}{C_RESET}")
    print(f"{C_BOLD}{'─'*60}{C_RESET}\n")

def prompt_required(label: str, default: str = "") -> str:
    """Prompt until non-empty input."""
    while True:
        default_hint = f" [{default}]" if default else ""
        val = input(f"  {label}{default_hint}: ").strip()
        if not val and default:
            return default
        if val:
            return val
        print(f"  {err('Required')}")

def prompt_optional(label: str, default: str = "") -> str:
    """Prompt with optional default."""
    default_hint = f" [{default}]" if default else " [optional]"
    val = input(f"  {label}{default_hint}: ").strip()
    return val or default

# ── Venv Setup ───────────────────────────────────────────────────────

def setup_venv() -> int:
    """Create .venv and install dependencies. Returns exit code."""
    venv = PROJECT_ROOT / ".venv"
    if not venv.exists():
        print(info("Creating virtual environment..."))
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)

    pip = str(venv / "bin" / "pip")
    python = str(venv / "bin" / "python3")

    print(info("Installing dependencies..."))
    deps = [
        "langchain", "langchain-openai", "langgraph",
        "chromadb", "pyyaml", "python-dotenv",
        "thenvoi_rest",
        "fastapi", "uvicorn", "httpx",
        "rich",
    ]
    result = subprocess.run(
        [pip, "install", "--quiet", "--upgrade", *deps],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(err(f"pip install failed:\n{result.stderr[-500:]}"))
        return result.returncode
    print(ok("Dependencies installed"))
    return 0

def get_venv_python() -> str:
    venv = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv.exists():
        return str(venv)
    return sys.executable

# ── Band Agent Registration ──────────────────────────────────────────

def register_agent(band_client, agent_def: dict) -> dict | None:
    """Register one agent on Band. Returns {agent_id, api_key} or None on failure."""
    from thenvoi_rest import AgentRegisterRequest
    try:
        resp = band_client.human_api_agents.register_my_agent(
            agent=AgentRegisterRequest(
                name=agent_def["name"],
                description=agent_def["role"],
            )
        )
        data = resp.data
        if not data or not data.agent or not data.credentials or not data.credentials.api_key:
            raise ValueError(f"No credentials returned for {agent_def['name']}")
        return {
            "agent_id": str(data.agent.id),
            "api_key": str(data.credentials.api_key),
        }
    except Exception as e:
        print(f"  {err(agent_def['name'])} — {e}")
        return None

def register_all_agents(human_api_key: str) -> dict[str, dict]:
    """Register all 12 agents on Band. Returns {config_key: {agent_id, api_key}}."""
    from thenvoi_rest import RestClient

    client = RestClient(
        api_key=human_api_key,
        base_url="https://app.band.ai",
        timeout=30.0,
    )

    results = {}
    # Post a connecting notice so Band validates the Human API key
    try:
        client.human_api_agents.register_my_agent(
            agent={"name": "_connecting_", "description": "Validating Human API key"}
        )
    except Exception as e:
        err_str = str(e)
        # Expected — "_connecting_" is just a probe
        if "401" in err_str or "Unauthorized" in err_str or "invalid" in err_str.lower() or "Forbidden" in err_str or "403" in err_str:
            print(f"\n{err('Band Human API key is invalid.')}")
            print(f"  Error: {err_str}")
            print(f"  → Get your key at https://app.band.ai → Settings → API Keys")
            return {}
        # Other errors are OK — Band might reject _connecting_ name but the key is valid

    for i, agent in enumerate(AGENTS):
        name = agent["name"]
        print(f"  [{i+1}/{len(AGENTS)}] Registering {name:>10s}...", end=" ", flush=True)
        creds = register_agent(client, agent)
        if creds:
            results[agent["config_key"]] = creds
            print(ok(f"ID={creds['agent_id'][:12]}..."))
        else:
            print(err("Failed"))
        time.sleep(0.8)  # Rate limit courtesy

    return results

# ── Config Generation ────────────────────────────────────────────────

import yaml  # noqa: E402

def generate_agent_config(credentials: dict[str, dict]) -> str:
    """Generate agent_config.yaml from registered credentials."""
    config = {}
    for agent in AGENTS:
        key = agent["config_key"]
        creds = credentials.get(key, {})
        entry = {
            "name": agent["name"],
            "role": agent["role"],
            "handle": agent["handle"],
            "agent_id": creds.get("agent_id", f"your-{agent['name'].lower()}-uuid"),
            "api_key": creds.get("api_key", f"band_a_your_{agent['name'].lower()}_key"),
        }
        if agent.get("description"):
            entry["description"] = agent["description"]
        config[key] = entry

    # Header comment
    header = (
        "# Agent Configuration — Supaband\n"
        "# Auto-generated by setup.py — DO NOT commit to git\n"
        f"# {len(AGENTS)} agents registered\n"
        "#\n"
        "# Each agent was registered on Band via Human API.\n"
        "# If you need to re-register, delete this file and run setup.py again.\n"
        "#\n"
        "# See API_CONFIG.md for details on what each field means.\n"
    )
    yaml_str = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return header + "\n" + yaml_str

def generate_env(openai_key: str, openai_base_url: str, band_human_key: str = "") -> str:
    """Generate .env file."""
    band_line = f"BAND_HUMAN_API_KEY={band_human_key}\n" if band_human_key else ""
    return (
        "# Supaband Environment Variables\n"
        "# Auto-generated by setup.py — DO NOT commit to git\n\n"
        "# ── LLM Provider (OpenAI-compatible) ─────────────────────────────\n"
        f"OPENAI_API_KEY={openai_key}\n"
        f"OPENAI_BASE_URL={openai_base_url}\n\n"
        "# ── Band Human API (for on-demand worker creation) ────────────────\n"
        f"{band_line}"
        "# Keep this key — agents use it to spawn new workers at runtime.\n"
    )

def create_directories():
    """Create all necessary data directories."""
    dirs = [
        "agents/supa/data/logs",
        "agents/koe/data/logs",
        "agents/koe/data/research",
        "agents/koe/data/exports",
        "agents/mave/data/logs",
        "agents/mave/data/campaigns",
        "agents/mave/data/exports",
        "agents/forge/data/logs",
        "workers/quill/data/logs",
        "workers/pulse/data/logs",
        "workers/canvas/data/logs",
        "blob/blobw2/data/logs",
        "data/blackboard_files",
    ]
    for d in dirs:
        (PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)
    # Touch .gitkeep files
    for keep in [
        "agents/forge/data/.gitkeep",
        "agents/mave/data/.gitkeep",
        "workers/quill/data/.gitkeep",
        "workers/pulse/data/.gitkeep",
        "workers/canvas/data/.gitkeep",
        "data/.gitkeep",
        "data/blackboard_files/.gitkeep",
    ]:
        p = PROJECT_ROOT / keep
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()

# ── Interactive Prompt ───────────────────────────────────────────────

def interactive_prompt() -> tuple[str, str, str]:
    """Prompt user for all required keys interactively."""
    print(f"\n{C_BOLD}🦐 Supaband Setup — Interactive Configuration{C_RESET}\n")
    print("  This script will:")
    print("  1. Set up Python virtual environment")
    print("  2. Register all 12 agents on Band automatically")
    print("  3. Generate agent_config.yaml and .env")
    print("")
    print(f"  {C_BOLD}What you'll need:{C_RESET}")
    print("  • An OpenAI-compatible API key (OpenAI, AI/ML API, Featherless, Groq, etc.)")
    print("  • A Band Pro account with Human API key")
    print("")

    section("1. LLM Provider (OpenAI-compatible)")

    print("  Any OpenAI-compatible API works. Common options:")
    print("    • AI/ML API:     https://api.aimlapi.com/v1")
    print("    • OpenAI:        https://api.openai.com/v1")
    print("    • Featherless:   https://api.featherless.ai/v1")
    print("    • Groq:          https://api.groq.com/openai/v1")
    print("    • Custom:        your own endpoint")
    print("")

    openai_key = prompt_required("API Key")
    openai_base = prompt_required("Base URL", "https://api.openai.com/v1")

    section("2. Band Human API Key")

    print("  Get your Band Human API key at:")
    print("    → https://app.band.ai → Settings → API Keys")
    print("  You need a Band Pro account for multi-agent features.")
    print("")

    band_key = prompt_required("Band Human API Key")

    section("Review")
    print(f"  LLM Provider: {C_CYAN}{openai_base}{C_RESET}")
    print(f"  LLM API Key:  {C_CYAN}{openai_key[:12]}...{openai_key[-4:]}{C_RESET}")
    print(f"  Band Key:     {C_CYAN}{band_key[:12]}...{band_key[-4:]}{C_RESET}")
    print(f"  Agents to register: {C_CYAN}{len(AGENTS)}{C_RESET}")
    print("")

    confirm = input(f"  Proceed? [Y/n]: ").strip().lower()
    if confirm and confirm != "y" and confirm != "yes":
        print(f"\n{info('Setup cancelled.')}")
        sys.exit(0)

    return openai_key, openai_base, band_key

# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Supaband Automated Setup — register agents + generate configs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 setup.py                           # Interactive mode
  python3 setup.py --skip-registration       # Only set up venv + config templates
  python3 setup.py --non-interactive \\
    --openai-key sk-... --openai-base https://api.aimlapi.com/v1 \\
    --band-human-key band_h_...
""",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Skip prompts, use CLI args")
    parser.add_argument("--openai-key", help="OpenAI-compatible API key")
    parser.add_argument("--openai-base", default="https://api.openai.com/v1", help="OpenAI-compatible base URL")
    parser.add_argument("--band-human-key", help="Band Human API key")
    parser.add_argument("--skip-registration", action="store_true", help="Skip Band agent registration (use templates only)")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dependency installation")
    args = parser.parse_args()

    # ── Banner ───────────────────────────────────────────────────
    print(f"\n{C_BOLD}🦐 Supaband Setup{C_RESET}")
    print(f"{'─'*50}\n")

    # ── Step 0: Get keys ─────────────────────────────────────────
    if args.non_interactive:
        if not args.openai_key or not args.band_human_key:
            print(err("--non-interactive requires --openai-key and --band-human-key"))
            sys.exit(1)
        openai_key = args.openai_key
        openai_base = args.openai_base
        band_key = args.band_human_key
    else:
        openai_key, openai_base, band_key = interactive_prompt()

    # ── Step 1: Venv + deps ──────────────────────────────────────
    section("Step 1/3: Environment Setup")
    print(info("Python: " + sys.executable))
    print(info("Project: " + str(PROJECT_ROOT)))

    if not args.skip_deps:
        exit_code = setup_venv()
        if exit_code != 0:
            print(err("Dependency installation failed. Fix and retry."))
            sys.exit(exit_code)
    else:
        print(info("Skipping dependencies (--skip-deps)"))

    # ── Step 2: Register agents on Band ──────────────────────────
    section("Step 2/3: Band Agent Registration")

    registered = {}
    if args.skip_registration:
        print(warn("Skipping Band registration (--skip-registration)"))
        print("  Using template placeholders in agent_config.yaml")
    else:
        print(f"  Registering {C_BOLD}{len(AGENTS)} agents{C_RESET} on Band...\n")
        registered = register_all_agents(band_key)
        if not registered:
            print(f"\n{warn('No agents were registered.')}")
            print("  agent_config.yaml will be generated with placeholders.")
            print("  Register agents manually on https://app.band.ai and fill in the file.")
        else:
            print(f"\n{ok(f'{len(registered)}/{len(AGENTS)} agents registered successfully')}")

    # ── Step 3: Generate configs ─────────────────────────────────
    section("Step 3/3: Configuration Files")

    # agent_config.yaml
    config_path = PROJECT_ROOT / "agent_config.yaml"
    if config_path.exists():
        backup = PROJECT_ROOT / f"agent_config.yaml.backup-{int(time.time())}"
        config_path.rename(backup)
        print(info(f"Backed up existing config → {backup.name}"))

    config_content = generate_agent_config(registered)
    config_path.write_text(config_content)
    print(ok("Generated agent_config.yaml"))

    # .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        backup = PROJECT_ROOT / f".env.backup-{int(time.time())}"
        env_path.rename(backup)
        print(info(f"Backed up existing .env → {backup.name}"))

    env_content = generate_env(openai_key, openai_base, band_key)
    env_path.write_text(env_content)
    print(ok("Generated .env"))

    # Data directories
    print(info("Creating data directories..."))
    create_directories()
    print(ok("Data directories ready"))

    # ── Done ─────────────────────────────────────────────────────
    registered_note = (
        f"\n  {ok(f'{len(registered)}/{len(AGENTS)} agents registered on Band')}"
        if registered
        else f"\n  {warn(f'0 agents registered — fill in agent_config.yaml manually')}"
    )

    print(f"""
{C_BOLD}{'═'*60}{C_RESET}
{C_BOLD}  ✅ Supaband is ready!{C_RESET}
{C_BOLD}{'═'*60}{C_RESET}
{registered_note}

{C_BOLD}  Configuration files:{C_RESET}
    • .env              → LLM provider settings
    • agent_config.yaml → Agent credentials (keep secret)
    • config/            → Templates for reference

{C_BOLD}  Next steps:{C_RESET}
    1. Run:  {C_CYAN}./supaband{C_RESET}          (TUI chat with Supa)
    2. Run:  {C_CYAN}./supaband run{C_RESET}      (start agent fleet)
    3. Run:  {C_CYAN}./supaband web{C_RESET}      (dashboard at localhost:8080)

{C_BOLD}  Docs:{C_RESET}  README.md  |  API_CONFIG.md  |  FEATURES.md  |  CLI-CHEATSHEET.md
{C_BOLD}{'═'*60}{C_RESET}
""")


if __name__ == "__main__":
    main()
