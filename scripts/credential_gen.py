#!/usr/bin/env python3
"""Standalone credential generator — create Band credentials without an agent.

Usage:
    python3 scripts/credential_gen.py "AgentName" "Purpose description"
    python3 scripts/credential_gen.py  # will ask for name and purpose
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.worker_factory import credential_create

def main():
    if len(sys.argv) >= 3:
        name = sys.argv[1]
        purpose = sys.argv[2]
    else:
        name = input("Agent name (or Enter for random): ").strip()
        purpose = input("Purpose: ").strip()

    print(f"\n🔑 Creating credentials for '{name or '(random)'}'...")
    result = credential_create(name=name, purpose=purpose)

    if not result["ok"]:
        print(f"❌ Failed: {result.get('error')}")
        sys.exit(1)

    print(f"\n✅ Credentials created!")
    print(f"   Name:      {result['name']}")
    print(f"   UUID:      {result['agent_id']}")
    print(f"   API Key:   {result['api_key']}")
    print(f"   Handle:    {result['handle']}")
    print(f"   Config:    {result['config_key']}")
    print(f"\n   Use these to connect an external agent to Band.")

if __name__ == "__main__":
    main()
