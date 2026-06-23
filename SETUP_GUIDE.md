# Supaband Manual Setup Guide

> **For when `./setup.sh` fails** — this guide walks through installing Supaband manually, step by step. Works even without an automated setup script.

---

## Prerequisites

- **Python 3.11+** (3.12, 3.13, 3.14 all work)
- **Band Pro account** — https://app.band.ai (needed for multi-agent communication)
- **OpenAI-compatible LLM API key** — OpenAI, AI/ML API, Featherless, Groq, or any custom provider
- **`git`, `curl`** (standard tools)

---

## Step 1: Clone and Enter Project

```bash
git clone https://github.com/misterfesk/supaband.git
cd supaband
```

---

## Step 2: Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Linux/Mac
# .venv\Scripts\activate    # On Windows
```

Verify it's working:
```bash
which python3     # Should point to .venv/bin/python3
python3 --version # Should be 3.11+
```

---

## Step 3: Install Dependencies

```bash
pip install --upgrade \
  langchain langchain-openai langgraph \
  chromadb pyyaml python-dotenv \
  thenvoi_rest \
  fastapi uvicorn httpx \
  rich
```

Verify the Band SDK installed:
```bash
python3 -c "from thenvoi_rest import RestClient; print('OK')"
```

---

## Step 4: Get Your Band Human API Key

1. Go to https://app.band.ai
2. Log in to your **Band Pro account**
3. Navigate to **Settings → API Keys**
4. Copy your **Human API key** (starts with `band_h_...`)

Keep this key secret — it can create and manage agents on your behalf.

---

## Step 5: Register Agents on Band

You must register all 12 agents ONCE. The Band REST API gives each agent a unique ID and API key.

### 5a. Create a Registration Script

Create a file called `register.py`:

```python
#!/usr/bin/env python3
"""Register all Supaband agents on Band. Run: python3 register.py"""
import sys, time
from thenvoi_rest import RestClient, AgentRegisterRequest

HUMAN_API_KEY = "band_h_YOUR_KEY_HERE"  # ← Replace with your key

AGENTS = [
    {"key": "supervisor_agent",   "name": "Supa",   "desc": "CEO & Supervisor"},
    {"key": "research_manager",   "name": "Koe",    "desc": "Research Department Manager"},
    {"key": "marketing_manager",  "name": "Mave",   "desc": "Marketing & Digital Production Manager"},
    {"key": "operations_manager", "name": "Forge",  "desc": "Operations Department Manager"},
    {"key": "sink_agent",         "name": "Void",   "desc": "Message sink — loop prevention"},
    {"key": "blob_worker_1",      "name": "Blobw1", "desc": "Early Adopter persona (shadow testing)"},
    {"key": "blob_worker_2",      "name": "Blobw2", "desc": "Skeptical Buyer persona (shadow testing)"},
    {"key": "blob_worker_3",      "name": "Blobw3", "desc": "Price-Sensitive persona (shadow testing)"},
    {"key": "content_strategist", "name": "Quill",  "desc": "Content Strategist & Copywriter"},
    {"key": "seo_analyst",        "name": "Pulse",  "desc": "SEO & Digital Marketing Analyst"},
    {"key": "visual_coordinator", "name": "Canvas", "desc": "Visual Production Coordinator"},
    {"key": "credential_dataminer","name": "DataMiner","desc":"Data analysis and mining specialist"},
]

client = RestClient(api_key=HUMAN_API_KEY, base_url="https://app.band.ai", timeout=30.0)
results = {}

for i, agent in enumerate(AGENTS):
    name = agent["name"]
    print(f"[{i+1}/{len(AGENTS)}] Registering {name}...", end=" ", flush=True)
    try:
        resp = client.human_api_agents.register_my_agent(
            agent=AgentRegisterRequest(name=name, description=agent["desc"])
        )
        # Response format depends on SDK version:
        if hasattr(resp, "data") and hasattr(resp.data, "agent"):
            data = resp.data
        elif hasattr(resp, "agent"):
            data = resp
        else:
            print(f"FAILED (unexpected response type: {type(resp)})")
            continue

        agent_id = data.agent.id
        api_key = data.credentials.api_key
        results[agent["key"]] = {"agent_id": agent_id, "api_key": api_key}
        print(f"OK — ID={agent_id[:12]}...")
    except Exception as e:
        print(f"FAILED — {e}")
    time.sleep(0.8)  # Respect rate limits

print(f"\nRegistered: {len(results)}/{len(AGENTS)} agents")
print("\nCopy these into agent_config.yaml:")
for key, creds in results.items():
    print(f"  {key}: agent_id={creds['agent_id']} api_key={creds['api_key']}")
```

### 5b. Run the Script

```bash
python3 register.py
```

**Expected output:**
```
[1/12] Registering Supa... OK — ID=aa1b2c3d4e5f...
[2/12] Registering Koe... OK — ID=bb2c3d4e5f6a...
...
Registered: 12/12 agents
```

> **If it fails:** Check that your `HUMAN_API_KEY` is correct. It must start with `band_h_`. If you see `401` or `Unauthorized`, your key is invalid.

---

## Step 6: Create agent_config.yaml

Create `agent_config.yaml` in the project root:

```yaml
# Agent Configuration — Supaband
# Manually configured — DO NOT commit to git
# 12 agents registered

supervisor_agent:
  name: "Supa"
  role: "CEO & Supervisor"
  handle: "@zoha/supa-bz"
  agent_id: "your-supa-uuid"          # ← Replace with actual UUID
  api_key: "band_a_your_supa_key"     # ← Replace with actual key

research_manager:
  name: "Koe"
  role: "Research Department Manager"
  handle: "@zoha/koe-bz"
  agent_id: "your-koe-uuid"
  api_key: "band_a_your_koe_key"

marketing_manager:
  name: "Mave"
  role: "Marketing & Digital Production Manager"
  handle: "@zoha/mave-bz"
  agent_id: "your-mave-uuid"
  api_key: "band_a_your_mave_key"

operations_manager:
  name: "Forge"
  role: "Operations Department Manager"
  handle: "@zoha/forge-bz"
  agent_id: "your-forge-uuid"
  api_key: "band_a_your_forge_key"

sink_agent:
  name: "Void"
  role: "Message sink — loop prevention"
  handle: ""
  agent_id: "your-void-uuid"
  api_key: "band_a_your_void_key"

blob_worker_1:
  name: "Blobw1"
  role: "Early Adopter persona (shadow testing)"
  handle: "@zoha/blob-worker-1"
  agent_id: "your-blobw1-uuid"
  api_key: "band_a_your_blobw1_key"

blob_worker_2:
  name: "Blobw2"
  role: "Skeptical Buyer persona (shadow testing)"
  handle: "@zoha/blob-worker-2"
  agent_id: "your-blobw2-uuid"
  api_key: "band_a_your_blobw2_key"

blob_worker_3:
  name: "Blobw3"
  role: "Price-Sensitive persona (shadow testing)"
  handle: "@zoha/blob-worker-3"
  agent_id: "your-blobw3-uuid"
  api_key: "band_a_your_blobw3_key"

content_strategist:
  name: "Quill"
  role: "Content Strategist & Copywriter"
  handle: "@zoha/quill-bz"
  agent_id: "your-quill-uuid"
  api_key: "band_a_your_quill_key"

seo_analyst:
  name: "Pulse"
  role: "SEO & Digital Marketing Analyst"
  handle: "@zoha/pulse-bz"
  agent_id: "your-pulse-uuid"
  api_key: "band_a_your_pulse_key"

visual_coordinator:
  name: "Canvas"
  role: "Visual Production Coordinator"
  handle: "@zoha/canvas-bz"
  agent_id: "your-canvas-uuid"
  api_key: "band_a_your_canvas_key"

credential_dataminer:
  name: "DataMiner"
  role: "Data analysis and mining specialist"
  handle: "@zoha/dataminer-bz"
  agent_id: "your-dataminer-uuid"
  api_key: "band_a_your_dataminer_key"
```

**Fill in real values** from Step 5's output — replace every `your-*-uuid` and `band_a_your_*_key`.

---

## Step 7: Create .env File

Create `.env` in the project root:

```bash
# Supaband Environment Variables
# Manually configured — DO NOT commit to git

# ── LLM Provider (OpenAI-compatible) ─────────────────────────────
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1

# ── Model ────────────────────────────────────────────────────────
SUPABAND_MODEL=deepseek-chat

# ── Band Human API (for on-demand worker creation) ────────────────
BAND_HUMAN_API_KEY=band_h_your_human_api_key_here
```

Replace:
- `sk-your-openai-api-key-here` with your actual LLM API key
- `https://api.openai.com/v1` with your provider's base URL (if different)
- `SUPABAND_MODEL` with the model name your provider supports
- `band_h_your_human_api_key_here` with your Band Human API key from Step 4

**Common LLM provider URLs:**
| Provider | Base URL |
|----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| AI/ML API | `https://api.aimlapi.com/v1` |
| Featherless | `https://api.featherless.ai/v1` |
| Groq | `https://api.groq.com/openai/v1` |

---

## Step 8: Create Data Directories

```bash
mkdir -p \
  agents/supa/data/logs \
  agents/koe/data/logs agents/koe/data/research agents/koe/data/exports \
  agents/mave/data/logs agents/mave/data/campaigns agents/mave/data/exports \
  agents/forge/data/logs \
  workers/quill/data/logs \
  workers/pulse/data/logs \
  workers/canvas/data/logs \
  blob/blobw2/data/logs \
  data/blackboard_files

# Touch .gitkeep so git tracks empty dirs
touch \
  agents/forge/data/.gitkeep \
  agents/mave/data/.gitkeep \
  workers/quill/data/.gitkeep \
  workers/pulse/data/.gitkeep \
  workers/canvas/data/.gitkeep \
  data/.gitkeep \
  data/blackboard_files/.gitkeep
```

---

## Step 9: Verify Everything

```bash
# Check Python environment
source .venv/bin/activate
python3 -c "from thenvoi_rest import RestClient; print('SDK OK')"
python3 -c "from langchain_openai import ChatOpenAI; print('LangChain OK')"

# Check config files
ls -la agent_config.yaml .env

# Quick connectivity check (won't register, just validates key)
python3 -c "
import os, sys
from dotenv import load_dotenv
load_dotenv()
from thenvoi_rest import RestClient
key = os.environ.get('BAND_HUMAN_API_KEY', '')
if not key:
    print('ERROR: BAND_HUMAN_API_KEY not in .env')
    sys.exit(1)
try:
    c = RestClient(api_key=key, base_url='https://app.band.ai', timeout=10.0)
    agents = c.human_api_agents.list_my_agents(page_size=5)
    print(f'Band connection OK — {len(getattr(agents, \"data\", agents)) if hasattr(agents, \"data\") else \"?\"} agents found')
except Exception as e:
    print(f'Band connection FAILED: {e}')
"
```

---

## Step 10: Launch Supaband

```bash
./supaband           # Interactive TUI chat with Supa
./supaband run       # Start all 4 manager agents in background
./supaband web       # WebUI dashboard at http://localhost:8080
```

---

## Troubleshooting

### "Module not found: thenvoi_rest"
```bash
.venv/bin/pip install --upgrade thenvoi_rest
```

### "401 Unauthorized" during registration
Your Band Human API key is invalid or expired. Get a new one at https://app.band.ai → Settings → API Keys.

### "AttributeError: ... object has no attribute 'data'"
The Band SDK response format differs from what the code expects. Use the `hasattr` check pattern shown in Step 5 above — it handles both old and new SDK versions.

### Agents start but don't communicate
Make sure `agent_config.yaml` has real agent IDs and API keys — not placeholder values. Each agent needs its own `band_a_...` key (different from your Human API key `band_h_...`).

### Re-registering agents
If you need to re-register (keys lost, agents broken):
1. Delete `agent_config.yaml`
2. Delete all agents on Band (Settings → Agents → Delete each)
3. Re-run `python3 register.py` from Step 5

---

## Files You Should NEVER Commit to Git

- `.env` — contains API keys
- `agent_config.yaml` — contains agent credentials
- `register.py` — contains your Human API key (if you pasted it in)
- `.venv/` — local virtual environment
- Any `*.backup-*` files

Add these to `.gitignore`:
```
.env
agent_config.yaml
register.py
*.backup-*
```
