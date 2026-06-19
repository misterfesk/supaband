# API Configuration Guide

This guide walks you through the API keys and services Supaband needs.

> **TL;DR:** Run `./setup.sh` — it asks for your keys interactively and does everything automatically.

---

## Required Services

### 1. OpenAI-Compatible LLM Provider

**What it's for:** All agents (Supa, Koe, Mave, Forge, workers) use this for LLM inference.

**Any OpenAI-compatible API works:**

| Provider | Base URL | How to Get |
|----------|----------|-----------|
| **OpenAI** | `https://api.openai.com/v1` | [platform.openai.com](https://platform.openai.com) |
| **AI/ML API** | `https://api.aimlapi.com/v1` | [aimlapi.com](https://aimlapi.com) |
| **Featherless** | `https://api.featherless.ai/v1` | [featherless.ai](https://featherless.ai) |
| **Groq** | `https://api.groq.com/openai/v1` | [console.groq.com](https://console.groq.com) |
| **Custom** | Your own URL | Self-hosted or third-party |

**Where to put it:** `.env` file
```bash
OPENAI_API_KEY=your-o...# Optional: defaults to https://api.openai.com/v1

# The setup script generates this automatically from your prompt answers.
```

**Model used:** `deepseek-v4-flash` (configurable per-agent in `agents/<name>/agent.py`)

---

### 2. Band Platform (Agent Communication)

**What it's for:** Multi-agent communication layer — agents send messages, create chatrooms, @mention each other, and discover other agents through Band.

**How to get it:**
1. Go to [app.band.ai](https://app.band.ai)
2. Sign up for a **Band Pro** account (required for multi-agent features)
3. Go to **Settings → API Keys**
4. Copy your **Human API Key** (starts with `band_h_`)

**Where to put it:** Automated setup uses it to register all agents, then discards it. It is NOT stored in any config file after setup.

**Agents automatically registered by setup:**
- Supa (CEO Supervisor)
- Koe (Research Manager)
- Mave (Marketing Manager)
- Forge (Operations Manager)
- Void (Loop prevention sink)
- Blobw1, Blobw2, Blobw3 (Shadow testing consumer panel)
- Quill (Content Strategist)
- Pulse (SEO Analyst)
- Canvas (Visual Production)
- DataMiner (Data analysis)

Each agent gets its own API key from Band (stored in `agent_config.yaml`).

---

## Configuration Files

### `.env` — LLM Provider Settings
```bash
# Generated automatically by ./setup.sh
OPENAI_API_KEY=your-o...L: https://api.openai.com/v1
```

### `agent_config.yaml` — Agent Credentials
```yaml
# Generated automatically by ./setup.sh
supervisor_agent:
  name: "Supa"
  role: "CEO & Supervisor"
  handle: "@zoha/supa-bz"
  agent_id: "uuid-from-band"
  api_key: "band_a_your_supa_key"

research_manager:
  name: "Koe"
  # ... etc for all 12 agents
```

---

## Setup Options

### Option A: Automated (Recommended)
```bash
./setup.sh
```
Prompts for:
1. OpenAI-compatible API key + base URL
2. Band Human API key

Then automatically:
- Creates venv + installs deps
- Registers all 12 agents on Band
- Generates `.env` and `agent_config.yaml`

### Option B: CI / Scripted
```bash
python3 setup.py --non-interactive \
  --openai-key sk-... \
  --openai-base https://api.aimlapi.com/v1 \
  --band-human-key band_h_...
```

### Option C: Manual (skip Band registration)
```bash
python3 setup.py --skip-registration
```
Generates `.env` + `agent_config.yaml` with placeholders. Fill in agent credentials manually from [app.band.ai](https://app.band.ai).

---

## Verification

After setup, verify connectivity:

```bash
# Test LLM (use whatever model you configured)
source .venv/bin/activate
python3 -c "
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
load_dotenv()
llm = ChatOpenAI(
    model='deepseek-v4-flash',
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
)
print(llm.invoke('Hello').content)
"

# Test Band
python3 -c "
from thenvoi_rest import RestClient
import yaml
with open('agent_config.yaml') as f:
    cfg = yaml.safe_load(f)
key = cfg['supervisor_agent']['api_key']
c = RestClient(api_key=key, base_url='https://app.band.ai')
print(c.agent_api_chats.list_agent_chats(page_size=1))
"
```

---

## Troubleshooting

| Problem | Likely Fix |
|---------|-----------|
| `FileNotFoundError: agent_config.yaml` | Run `./setup.sh` |
| `OPENAI_API_KEY not found in .env` | Check `.env` has `OPENAI_API_KEY=...` (not AIML_API_KEY) |
| Band registration fails | Verify your Human API key at app.band.ai → Settings → API Keys |
| `AuthenticationError` from Band | Each agent has its own key — verify in `agent_config.yaml` |
| LLM connection error | Check your `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env` |
| `ModuleNotFoundError: thenvoi_rest` | Run `source .venv/bin/activate && pip install thenvoi_rest` |
| Loop / echo issues | Make sure Void sink agent is registered and in `agent_config.yaml` |
