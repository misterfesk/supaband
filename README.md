# Supaband 🦐

> A multi-agent management system for your business & projects — clone, configure, run.

**Supaband** is a multi-agent system that can manage your business or projects autonomously. A CEO agent (Supa) spawns new agents on-demand, coordinates a customized team of specialists, and executes tasks through a real-time collaboration layer built on [Band](https://band.ai). Agents brainstorm ideas, make marketing strategies, produce digital content (posts, images, videos), manage projects with approval workflows, integrate 3rd-party services, and even issue remote credentials so you can connect external agents (like OpenClaw managing a VPS) — all without touching the infrastructure yourself.

**Supaband** is a self-contained multi-agent AI system for business automation. You give Supa your strategic objectives — it brainstorms, creates plans, and the agent team executes. Agents coordinate market research, marketing campaigns, content production, visual briefs, and operational planning. Deliverables land on the production dashboard for your approval, and you can connect external services for extended workflows.

> ⚠️ **Setup Note (Hackathon Submission)**
> This project was built during a hackathon. The automated `setup.sh` may hit issues depending on your environment (Python version mismatch, missing Band SDK dependencies). The original code is preserved as-submitted.
>
> If the automated setup fails, follow the **[Manual Setup Guide](SETUP_GUIDE.md)** for step-by-step instructions.
> *This guide was added post-submission to help judges and users get the project running.*

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/misterfesk/supaband.git
cd supaband

# 2. One-command setup (interactive — asks for API keys)
./setup.sh

# 3. Launch
./supaband          # Interactive TUI chat with Supa (the CEO agent)
./supaband web      # WebUI dashboard on http://localhost:8080
./supaband run      # Start all 4 manager agents as background processes
```

**What `./setup.sh` does:**
- Creates a Python virtual environment + installs all dependencies
- Asks for your **OpenAI-compatible API key** + **Band Human API key**
- **Registers ALL 12 agents on Band automatically** (no manual steps)
- Generates `agent_config.yaml` and `.env` with all credentials

> **Prerequisites:** Python 3.11+ and a [Band Pro account](https://app.band.ai) (for agent communication layer). You need a **Human API key** from Band — Settings → API Keys.

---

## What You Need

| Service | Purpose | How to Get |
|---------|---------|-------------|
| **OpenAI-compatible API** | LLM inference for all agents | [OpenAI](https://platform.openai.com), [AI/ML API](https://aimlapi.com), [Featherless](https://featherless.ai), [Groq](https://groq.com), or any compatible provider |
| **Band Pro account** | Agent communication layer | [app.band.ai](https://app.band.ai) → Settings → API Keys → Human API key |

**Supported LLM providers** — anything implementing the OpenAI `/v1/chat/completions` endpoint:

| Provider | Base URL |
|----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| AI/ML API | `https://api.aimlapi.com/v1` |
| Featherless | `https://api.featherless.ai/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Custom | Your own endpoint |

---

## Architecture

```
supaband/
├── agents/              # Manager agents (Supa, Koe, Mave, Forge)
│   ├── supa/            # CEO & Supervisor — delegation, fleet, user interaction
│   ├── koe/             # Research Manager — market research, competitor analysis
│   ├── mave/            # Marketing Manager — campaigns, content, SEO, visuals
│   └── forge/           # Operations Manager — coordination, resource allocation
├── workers/             # On-demand specialist workers
│   ├── quill/           # Content Strategist & Copywriter
│   ├── pulse/           # SEO & Digital Marketing Analyst
│   └── canvas/          # Visual Production Coordinator
├── blob/                # Shadow testing consumer panel (3 persona agents)
├── core/                # Shared infrastructure
│   ├── agent_base.py    # BaseAgent — polling, Band, health, tools, lifecycle
│   ├── config.py        # .env + agent_config.yaml loader
│   ├── blackboard.py    # SQLite shared knowledge base for cross-agent file sharing
│   ├── worker_factory.py # On-demand agent creation + registration
│   ├── fleet.py         # Fleet process manager (PID, health, launch/kill)
│   ├── webui_db.py      # WebUI dashboard database
│   ├── webui_tools.py    # LangChain tools for production board + todos
│   ├── shared_tools.py  # Blackboard tools for all agents
│   ├── session_db.py    # Chat session persistence (TUI + WebUI)
│   └── sink_agent.py    # Void sink agent (loop prevention)
├── webui/               # Web dashboard (FastAPI + vanilla JS + SSE)
│   ├── server.py        # FastAPI server with REST API + SSE streaming
│   └── static/          # Frontend (index.html, app.js, styles.css)
├── tui/                 # Terminal UI (Rich-based)
│   ├── app.py           # Main TUI application
│   ├── commands.py      # Slash command handlers (/awake, /kill, /status, etc.)
│   └── band_interface.py # Band polling + proxy agent patterns
├── scripts/             # Admin utilities
├── skills/              # Agent skill files (injected into system prompts)
├── config/              # Templates (.env.example, agent_config.yaml.example)
├── supaband             # Single entry point (TUI + fleet + web subcommands)
├── supaband-cli         # Power-user CLI for fleet + Band management
├── supaband-run         # Agent launcher
├── supaband-tui         # Terminal UI entry point
├── supaband-web         # WebUI launcher
├── setup.py             # Automated setup (Band registration + config generation)
├── setup.sh             # Setup wrapper
└── README.md
```

### How It Works

1. Each agent inherits from `BaseAgent` — a persistent **LangGraph ReAct agent** with `MemorySaver` checkpointing
2. Agents poll Band every 3s for new messages addressed to them (via `thenvoi_rest` SDK)
3. On receiving a message: LangGraph processes through the LLM with all available tools
4. Agents respond via Band (with `@mentions` for targeting)
5. Supa auto-starts manager agents on launch via the fleet system
6. Workers are spawned on-demand by Supa or Mave via `worker_factory.py`
7. All agents share a SQLite blackboard for cross-department file exchange
8. WebUI receives real-time updates via SSE stream from the backend

---

## Agent Roster

### Core Managers (always running)

| Agent | Handle | Role | Port |
|-------|--------|------|------|
| **Supa** | `@<org>/supa-bz` | CEO & Supervisor — delegates tasks, manages fleet, interacts with users | 9100 |
| **Koe** | `@<org>/koe-bz` | Research Manager — market research, competitor analysis, data synthesis | 9101 |
| **Mave** | `@<org>/mave-bz` | Marketing & Digital Production Manager — campaigns, content, SEO, visuals | 9105 |
| **Forge** | `@<org>/forge-bz` | Operations Manager — resource allocation, process optimization, coordination | 9106 |

### Specialist Workers (spawned on-demand)

| Worker | Handle | Role |
|--------|--------|------|
| **Quill** | `@<org>/quill-bz` | Content Strategist & Copywriter |
| **Pulse** | `@<org>/pulse-bz` | SEO & Digital Marketing Analyst |
| **Canvas** | `@<org>/canvas-bz` | Visual Production Coordinator |
### Shadow Testing Panel

| Agent | Persona |
|-------|---------|
| **Blobw1** | Early Adopter — enthusiastic about new products |
| **Blobw2** | Skeptical Buyer — cautious, needs convincing |
| **Blobw3** | Price-Sensitive — budget-conscious consumer |

### System Agent

| Agent | Role |
|-------|------|
| **Void** | Message sink — never responds (loop prevention dead-end target) |

---

## Features

### 🎯 Multi-Agent Collaboration
- 4 persistent manager agents + on-demand specialist workers
- Supervisor-worker delegation pattern via Band `@mentions`
- Cross-department coordination through blackboard file sharing
- 42 tools on Supa, 32 on Koe, 27 on Mave

### 💬 Band Integration
- Real-time Band chatrooms for all inter-agent communication
- `@mentions` for targeted task delegation
- Band **Events** for non-triggering status updates (no loop risk)
- **Participant management** — add/remove agents from rooms
- **Chatroom lifecycle** — create, export, cleanup, archive
- **Void Sink Agent** — dead-end mention target for loop-free acknowledgments

### 🌐 WebUI Dashboard
- **Real-time SSE stream** — task updates push to browser instantly
- **Production Board** — agent deliverables appear as cards with type badges
- **Todo Queue** — approval tasks created by agents for human review
- **Agent Roster** — live status of all agents with health metrics
- **Chat Interface** — send messages to Supa directly from browser
- **Blackboard Browser** — view and search shared documents
- **Project Tracking** — create and monitor projects
- Dark theme designed for long monitoring sessions

### 🖥️ Terminal UI (TUI)
- Interactive chat with Supa via Rich library
- Session persistence (SQLite-backed)
- Context injection from prior messages
- Slash commands: `/new`, `/session`, `/history`, `/quit`, `/awake`, `/kill`, `/status`
- Fleet status at a glance
- Agent auto-start on TUI launch

### 📋 Blackboard (Shared Knowledge Base)
- SQLite-backed with filesystem mirror
- Cross-department file sharing
- Tag-based organization
- Full-text search
- Author/department tracking
- Timestamp-based versioning

### 🔧 Worker Factory
- On-demand agent creation — register on Band + generate Python files
- Prompt editing — modify worker system prompts at runtime
- Lifecycle management — launch/kill/list workers
- Credential-only mode — register on Band without creating files

### 🛡️ Loop Prevention System
- **Echo control** on `band_respond` — `echo=True` for replies, `echo=False` for acks
- **Void Sink Agent** — dead-end mention target that never responds
- **Self-echo detection** — agents ignore their own messages
- **Chatroom cleanup** — removes idle agents from completed rooms
- **Band Events** — non-triggering status updates (no @mentions)

### 💚 Fleet Management
- PID file tracking per agent
- HTTP health endpoints on ports 9100–9112
- Graceful stop (HTTP → SIGTERM → SIGKILL fallback)
- Background launch with log capture
- Restart without data loss
- Watchdog — Supa monitors manager health every 5 cycles

### 📊 Production Board & Todo Queue
- Agents post deliverable items to WebUI production board
- Todo items with human approval workflow
- Project-scoped organization
- Agent activity logging

### 🔍 Shadow Testing (Blob System)
- 3 persona-based consumer agents simulate real user perspectives
- Structured feedback gathering from simulated discussions
- AI-powered feedback synthesis
- Export-ready results

---

## Commands

```bash
# Main entry point
./supaband              # Interactive TUI (chat with Supa)
./supaband --new        # TUI with fresh session
./supaband --session s  # Resume a specific session
./supaband run          # Launch all manager agents
./supaband status       # Show fleet PIDs + health
./supaband stop         # Stop all agents
./supaband web          # Start WebUI dashboard

# Power-user CLI
./supaband-cli fleet-status         # Detailed agent health
./supaband-cli start supa koe       # Launch specific agents
./supaband-cli stop                 # Stop all agents
./supaband-cli -a supa chats       # List Band chatrooms
./supaband-cli -a supa room -t "Research" -m koe -M "task"  # Create room + delegate
./supaband-cli -a supa poll -c <id> -m koe -t 120           # Watch for responses
./supaband-cli -a koe export <id>                            # Export chat history
```

### TUI Slash Commands

| Command | Description |
|---------|-------------|
| `/awake <agent>` | Start an agent (supa, koe, mave, forge) |
| `/kill <agent>` | Stop an agent |
| `/status` | Show all agent PIDs and health |
| `/new` | Create a new chat session |
| `/session <id>` | Switch to a specific session |
| `/history` | Show recent messages |
| `/clear` | Clear the screen |
| `/help` | Show all commands |
| `/quit` | Exit the TUI |

---

## Health Endpoints

Each agent serves an HTTP health endpoint:

```bash
curl http://127.0.0.1:9100/health  # Supa
curl http://127.0.0.1:9101/health  # Koe
curl http://127.0.0.1:9105/health  # Mave
curl http://127.0.0.1:9106/health  # Forge
curl http://127.0.0.1:9110/health  # Blobw1
curl http://127.0.0.1:9111/health  # Blobw2
curl http://127.0.0.1:9112/health  # Blobw3
```

Returns:
```json
{"status": "ok", "cycles": 42, "messages_processed": 15, "uptime_seconds": 3600, "model": "*configurable via SUPABAND_MODEL*"}
```

---

## Setup Manual Walkthrough

If you prefer manual setup over the automated `./setup.sh`:

1. **Get an OpenAI-compatible API key** from your provider of choice
2. **Get a Band Human API key** from [app.band.ai](https://app.band.ai) → Settings → API Keys
3. Create venv: `python3 -m venv .venv && source .venv/bin/activate`
4. Install deps: `pip install -r requirements.txt`
5. Run setup: `python3 setup.py` (interactive mode)
6. Or skip registration: `python3 setup.py --skip-registration` (fill in `agent_config.yaml` manually)

---

## Use Cases

### 1. Market Research Automation
> "Research the competitive landscape for a new coffee shop in Austin"

Supa delegates to Koe → Koe scrapes web data, runs blob shadow tests with 3 consumer personas → synthesizes findings → posts to blackboard → Quill and Pulse get spawned for content + SEO strategy.

### 2. Marketing Campaign Production
> "Create a Q3 marketing campaign for our product launch"

Supa → Mave coordinates: spawns Quill (copy), Pulse (SEO/keywords), Canvas (creative briefs) → each produces assets → posted to production board → Supa presents final campaign summary.

### 3. Cross-Department Coordination
> "We need a go-to-market strategy for our new AI tool"

Supa decomposes task → delegates research to Koe, messaging to Mave, logistics to Forge → managers work in parallel → Supa synthesizes all findings into unified strategy.

### 4. Agent Fleet Management
> Run a self-healing agent organization that monitors itself

Supa's watchdog restarts crashed agents automatically. Health endpoints expose real-time metrics. Fleet commands enable manual control. Void sink prevents conversation spirals.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Agent Framework** | LangGraph (ReAct agent + MemorySaver checkpointing) |
| **LLM** | Configurable — set SUPABAND_MODEL in .env for any OpenAI-compatible model |
| **Communication** | Band platform (`thenvoi_rest` SDK) |
| **WebUI** | FastAPI + vanilla JavaScript (SSE for real-time) |
| **TUI** | Rich library |
| **Databases** | SQLite (blackboard, sessions, webui) |
| **Vector Store** | ChromaDB (EphemeralClient) |
| **Languages** | Python 3.11+ |

---

## Configuration

### `.env` — LLM Provider
```bash
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.aimlapi.com/v1  # Optional, defaults to OpenAI
BAND_HUMAN_API_KEY=your-band-human-key       # For on-demand worker creation
```

### `agent_config.yaml` — Agent Credentials
Generated automatically by `./setup.sh`. Contains 12 agent entries with Band API keys, UUIDs, handles, and roles.

### Skills System
Drop `.md` files into `skills/` — they're auto-injected into all agent system prompts. Built-in skills:
- `fleet-management.md` — How to manage the agent fleet
- `market-research.md` — Research methodology patterns
- `agent-code-modification.md` — Protocol for modifying agent source code
- `agent-development-patterns.md` — Patterns for extending agents

---

## Troubleshooting

| Problem | Likely Fix |
|---------|-----------|
| `FileNotFoundError: agent_config.yaml` | Run `./setup.sh` |
| `OPENAI_API_KEY not found in .env` | Check `.env` has `OPENAI_API_KEY=...` |
| Band registration fails | Verify your Human API key at app.band.ai → Settings → API Keys |
| `AuthenticationError` from Band | Each agent has its own key — verify in `agent_config.yaml` |
| LLM connection error | Check `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env` |
| `ModuleNotFoundError: thenvoi_rest` | Run `source .venv/bin/activate && pip install -r requirements.txt` |
| Loop / echo issues | Make sure Void sink agent is registered and in `agent_config.yaml` |
| Agents not responding | Check `./supaband status` — agents may need starting |

---

## License

MIT — see [LICENSE](LICENSE) file.
