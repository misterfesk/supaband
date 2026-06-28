# Supaband Architecture — Universal Framework

> **Not a product. A framework.** Supaband provides a universal runtime for building, spawning, and orchestrating AI agent organizations on [Band](https://band.ai). You define the agents, their roles, their tools, and their prompts. The framework handles Band communication, process lifecycle, loop prevention, shared memory, health monitoring, and dual user interfaces (TUI + WebUI).

Any agent — supervisor, manager, worker, blob tester, sink — inherits from the same `BaseAgent`. Any agent can be spawned on-demand at runtime via the worker factory. Any agent can be given any set of tools.

---

## 1. Core Framework (`core/`)

The framework is the invariant. The agents are the variables.

### 1.1 BaseAgent (`core/agent_base.py` — 1,517 lines)

Every agent in the system inherits from `BaseAgent(ABC)`. It provides the complete agent runtime.

```
Agent subclass (user-defined)
  └── BaseAgent (framework)
        ├── LangGraph ReAct agent (create_react_agent + MemorySaver)
        ├── Band REST client (thenvoi_rest, base_url=https://app.band.ai)
        ├── Polling loop (3s interval, parallel fetch, sequential processing)
        ├── Health HTTP server (per-agent port, /health /stop /chat)
        ├── PID file tracking
        ├── Logging (per-agent log files)
        ├── Skills injection (auto-load skills/*.md)
        └── Loop prevention (3-layer defense)
```

**Subclass contract — the minimum an agent must define:**

| Attribute/Method | Required | Purpose |
|-----------------|----------|---------|
| `CONFIG_KEY` | Yes | Key in `agent_config.yaml` for credentials |
| `MODEL` | No | LLM model (blank = inherit from `SUPABAND_MODEL` env var) |
| `TEMPERATURE` | No | LLM temperature (default 0.3) |
| `get_system_prompt()` | Yes | Return the agent's system prompt string |
| `get_extra_tools()` | No | Return list of agent-specific LangChain `@tool` functions |

**Optional overrides for behavior tuning:**

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `POLL_INTERVAL` | 3.0s | Seconds between Band poll cycles |
| `STALE_THRESHOLD_SEC` | 300 | Messages older than this are skipped |
| `AGENT_LOOP_GUARD` | 4 | Skip if last N messages are all agent-only |
| `ERROR_BACKOFF_BASE` | 1.0s | Exponential backoff on errors (max 60s) |
| `MAX_WORKERS` | 10 | ThreadPoolExecutor parallelism |
| `AUTO_START_MANAGERS` | [] | Agents to auto-start when this agent boots |
| `WATCHDOG_INTERVAL_CYCLES` | 10 | Health check frequency |
| `AUTO_RESPOND` | True | Auto-send Band response after LLM processing |

**Lifecycle:**
```
__init__()
  → load .env + agent_config.yaml
  → resolve MODEL (subclass → SUPABAND_MODEL → error)
  → create Band REST client (RestClient)
  → setup logging + directories

run()
  → write PID file
  → build LangGraph agent (create_react_agent)
  → start health HTTP server (daemon thread)
  → purge stale messages (parallel, all chatrooms)
  → cleanup idle rooms (parallel)
  → auto-start configured managers
  → MAIN LOOP: every POLL_INTERVAL seconds
      → list all chatrooms
      → parallel fetch pending messages (ThreadPoolExecutor)
      → sequential LLM processing (stale check → loop guard → invoke → mark processed)
      → watchdog check (every N cycles)
      → sleep or error backoff
  → on stop: remove PID, shutdown health server
```

### 1.2 Band Communication Tools (10 shared tools)

Every agent gets these tools via `make_shared_band_tools(ctx)`. They wrap the `thenvoi_rest` SDK:

| Tool | Band API | Purpose |
|------|----------|---------|
| `band_respond(content, echo)` | `create_agent_chat_message` | Reply in current chatroom. `echo=True` mentions sender (triggers reply), `echo=False` mentions Void (dead end) |
| `band_post_event(content, type)` | `create_agent_chat_event` | Post without @mentions — no agent triggered. Types: task/thought/tool_call/tool_result/error |
| `band_send_message(chat_id, content, mention_names)` | `create_agent_chat_message` | Send to any chatroom with @mentions |
| `band_create_chatroom(title, add_agents)` | `create_agent_chat` | Create room + add participants (Void auto-added) |
| `band_add_participant(chat_id, agent_name)` | `add_agent_chat_participant` | Add agent to room |
| `band_remove_participant(chat_id, agent_name)` | `remove_agent_chat_participant` | Remove agent from room |
| `band_cleanup_chatroom(chat_id, ...)` | export + batch remove | Export transcript + remove workers in one call |
| `band_list_chats()` | `list_agent_chats` | List all chatrooms |
| `band_export_chat(chat_id, save_name)` | `list_agent_messages` | Export full transcript to markdown |
| `band_get_chat_id()` | (local) | Debug: show current chat/message IDs |

### 1.3 Blackboard (`core/blackboard.py` — 244 lines)

SQLite-backed shared knowledge base. Cross-agent, cross-department file sharing. Not coupled to any specific agent.

**Schema:** `documents` (key, title, department, author, content, tags) + `file_index` (key, stored_path, file_type, size_bytes)

**Tools** (via `make_blackboard_tools(agent_name)` — 6 tools):
`bb_post`, `bb_retrieve`, `bb_list`, `bb_search`, `bb_pin`, `bb_delete`

**Filesystem mirror:** `data/blackboard_files/` — files copied on index for direct access.

### 1.4 Loop Prevention System (3 layers, built into BaseAgent)

Band requires ≥1 @mention per message. Without loop prevention, agents ping-pong endlessly.

**Layer 1 — Echo control:** `band_respond(content, echo=True/False)`
- `echo=True`: mentions sender → they process it (use for task deliverables)
- `echo=False`: mentions Void sink → no response (use for acks, status)

**Layer 2 — Band Events:** `band_post_event(content, type)` — no @mentions, no triggers.

**Layer 3 — Code-level guards in `poll_and_process()`:**
- Self-echo detection: skip if agent is responding to its own message
- Agent-only spiral: skip if last `AGENT_LOOP_GUARD` messages are all from agents
- Stale time gate: skip messages older than `STALE_THRESHOLD_SEC`
- Terminal response detection: short ack messages auto-route to Void
- Startup purge: bulk-mark stale messages as processed on boot

### 1.5 Void Sink Agent (`core/sink_agent.py`)

A Band-registered agent with NO LLM, NO polling, NO process. Its sole purpose: accept @mentions without responding. Every chatroom auto-adds Void.

Created via `create_sink_agent()` → Band Human API → stored in `agent_config.yaml` under `sink_agent` key.

### 1.6 Fleet Manager (`core/fleet.py` — 327 lines)

Process-level lifecycle for any agent. Not coupled to specific agent names — works with any agent that has a directory under `agents/<name>/agent.py` and a port in `AGENT_PORTS`.

| Function | Description |
|----------|-------------|
| `launch_agent(name)` | `subprocess.Popen` with log capture, 12s startup wait, PID + health verification |
| `kill_agent(name)` | HTTP `/stop` → stop file → SIGTERM → SIGKILL escalation |
| `agent_is_running(name)` | PID check + health endpoint probe |
| `agent_health(name)` | Returns `{running, pid, health, stale_removed}` |
| `ensure_agents_running(names)` | Start any that are down |
| `restart_agent(name)` | Kill → launch |

**Port allocation:** Configurable via `AGENT_PORTS` dict. Default range: supervisor=9100, managers=9101+, blob workers=9110+.

### 1.7 Worker Factory (`core/worker_factory.py` — 424 lines)

On-demand agent creation — the universal spawning mechanism. Two modes:

**Mode 1 — Credential only:** `credential_create(name, purpose)`
- Registers agent on Band via Human API
- Returns UUID + API key + handle
- No local files created — for external agents (OpenClaw, custom frameworks)

**Mode 2 — Full worker:** `create_worker(name, description, system_prompt, model, temperature, tools_import, tools_list)`
1. Register on Band → get credentials
2. Save to `agent_config.yaml`
3. Generate `workers/<name>/agent.py` from placeholder template
4. Write `workers/<name>/system_prompt.md`
5. Ready for `launch_worker()` → subprocess

**Worker template** uses Python `.format()` with these placeholders:
`{worker_name}`, `{class_name}`, `{config_key}`, `{model}`, `{temperature}`, `{role_description}`, `{tools_import}`, `{tools_list}`

Workers read their system prompt from `.md` file at startup — editable without touching code. Check for `prompt_override.md` first (set by `agent_edit_prompt` tool).

### 1.8 Shared Tool Factories

Tool factories produce agent-scoped tools. Every agent calls these in `get_extra_tools()`:

| Factory | Returns | Purpose |
|---------|---------|---------|
| `make_blackboard_tools(name)` | 6 tools | Cross-agent document sharing |
| `make_webui_tools(name, is_supervisor)` | 3-9 tools | Production board + todos + SSE updates |
| `make_file_tools()` | 2 tools | Sandboxed file read/write |
| `make_web_tools()` | 1 tool | Web scraping (httpx + BeautifulSoup) |

### 1.9 Configuration (`core/config.py`)

Two config sources, loaded at import time:

```
.env                    → OPENAI_API_KEY, OPENAI_BASE_URL, SUPABAND_MODEL, BAND_HUMAN_API_KEY
agent_config.yaml       → Per-agent: name, role, handle, agent_id, api_key
```

**Agent ID/handle resolution:** Loaded dynamically from `agent_config.yaml` at import time. `refresh_agent_ids()` called after creating new agents. Fallback dicts (`_AGENT_IDS_FALLBACK`) for when config is missing.

**Model resolution chain:** Subclass `MODEL` attribute → `SUPABAND_MODEL` env var → `ValueError` ("No model configured").

---

## 2. Agent Roles (Universal Taxonomy)

The framework imposes no fixed roster. These are the *roles* any agent can occupy:

### 2.1 Supervisor Agent

| Trait | Description |
|-------|-------------|
| **Purpose** | Receives user objectives, decomposes into tasks, delegates to managers, synthesizes results |
| **Typical tools** | All shared tools + agent lifecycle + worker factory + WebUI supervisor |
| **Fleet role** | Sets `AUTO_START_MANAGERS` — auto-starts other agents on boot |
| **Watchdog** | Monitors manager health, restarts crashed agents |
| **User interface** | Receives direct HTTP `/chat` from TUI + WebUI |
| **System prompt** | Organization chart, delegation rules, cross-agent awareness, deprecation list |
| **Port** | 9100 (convention) |

### 2.2 Manager Agents

| Trait | Description |
|-------|-------------|
| **Purpose** | Department head — receives tasks from supervisor, coordinates workers, delivers results |
| **Typical tools** | All shared tools + department-specific tools + worker lifecycle (if spawning workers) |
| **Fleet role** | Launched by supervisor on boot; persist throughout session |
| **Worker management** | Can spawn/kill/edit workers in their department |
| **System prompt** | Domain expertise, worker roster, delegation workflow, loop prevention rules |
| **Port** | 9101+ (convention) |

### 2.3 Worker Agents

| Trait | Description |
|-------|-------------|
| **Purpose** | Single-purpose specialist — executes one task type, delivers, stops |
| **Creation** | Spawned on-demand via `worker_create()` |
| **Lifecycle** | Created → launched → executes task → reports → killed |
| **System prompt** | Read from `workers/<name>/system_prompt.md` — editable at runtime |
| **Tools** | Minimal: shared Band + blackboard + file + role-specific |
| **Port** | Assigned dynamically or not needed (health-only) |

### 2.4 Blob Pattern (Consumer Simulation)

Blob is not a fixed set of agents — it's a **pattern** for running persona-based consumer panels.

| Trait | Description |
|-------|-------------|
| **Purpose** | Simulate real user perspectives on products, campaigns, or ideas |
| **Architecture** | N agents, each with a distinct persona system prompt |
| **Scale** | Not limited to 3 — spawn as many personas as needed |
| **Orchestration** | A manager creates a chatroom, adds N blob workers, posts a discussion prompt, the blobs discuss among themselves, manager exports the transcript |
| **Loop guard** | Set `AGENT_LOOP_GUARD = 999` (disabled) — agent-to-agent discussion is intentional |
| **Stop rule** | Blobs acknowledge the final summary and STOP — manager handles cleanup |

### 2.5 Void Sink

| Trait | Description |
|-------|-------------|
| **Purpose** | Dead-end mention target for loop-free acknowledgments |
| **Registration** | Band-registered, stored in `agent_config.yaml` as `sink_agent` |
| **Runtime** | No LLM, no process, no polling — exists only as a Band entity |
| **Usage** | Auto-added to every chatroom; agents mention Void for `echo=False` |

---

## 3. Agent Communication Architecture

### 3.1 Band Chatrooms (Agent ↔ Agent)

```
Supervisor → band_create_chatroom(add_agents="manager1,manager2") → Band
Supervisor → band_send_message(chat_id, "Task...", mention_names="manager1") → Band REST
  → Manager1's poll loop detects message → LangGraph processes → band_respond(result, echo=True)
  → Supervisor's poll loop detects response → synthesizes → reports to user
```

**Chatroom lifecycle:** CREATE → POPULATE → DELEGATE → WAIT → PROCESS → CLEANUP (`band_cleanup_chatroom` exports + removes workers).

### 3.2 Direct HTTP Chat (User ↔ Supervisor)

The TUI and WebUI bypass Band entirely for user-facing communication:

```
TUI → POST localhost:9100/chat {message, context, session_id}
  → BaseAgent.process_direct_message()
  → LangGraph agent.invoke() with system prompt
  → Returns AIMessage.content
```

This eliminates Band SSL issues, latency, dual-key polling, and self-mention restrictions for the user-facing path. Band remains the agent-to-agent backbone.

### 3.3 WebUI SSE Streaming (Async Results)

Manager results arrive via Band minutes after the HTTP cycle ends. SSE bridges this:

```
Supervisor receives manager response via Band poll
  → Calls task_update("result", summary)
  → Writes to webui.db task_updates table
  → WebUI SSE endpoint polls DB every 2s
  → Pushes new rows to browser in real-time
```

---

## 4. Configuration & Extension Points

### 4.1 `agent_config.yaml` — The Agent Registry

This is the single source of truth for all agent identities. Any agent in this file is discoverable by the system:

```yaml
# Required fields for every agent
my_agent_key:
  name: "Display Name"
  role: "What this agent does"
  handle: "@org/agent-handle"
  agent_id: "uuid-from-band-registration"
  api_key: "band_a_..."
```

The system auto-discovers agents from this file. `refresh_agent_ids()` reloads after changes.

### 4.2 Creating a New Agent

**Permanent manager agent** (built-in, always running):
1. Create `agents/<name>/agent.py` with a `BaseAgent` subclass
2. Set `CONFIG_KEY`, implement `get_system_prompt()`, `get_extra_tools()`
3. Add to `agent_config.yaml` (manual or via `setup.py`)
4. Add to fleet `AGENT_PORTS` and `FLEET_AGENTS`
5. Add to supervisor's `AUTO_START_MANAGERS` (optional)

**On-demand worker agent** (spawned at runtime):
```
worker_create("my-specialist", "Does X", "You are a specialist in X...")
→ Band registration → agent_config.yaml → agent.py → system_prompt.md
→ worker_launch("my-specialist") → running process
```

**Credential-only agent** (external, no local files):
```
credential_create("ExternalBot", "External monitoring agent")
→ Returns UUID + API key + handle
→ Connect external agent with these credentials
```

### 4.3 System Prompt Architecture

Each agent resolves its system prompt through this chain:

```
1. agents/<name>/prompt_override.md         ← set by agent_edit_prompt tool
2. workers/<name>/prompt_override.md         ← set by worker_edit_prompt tool
3. workers/<name>/system_prompt.md           ← set at worker creation
4. get_system_prompt() return value          ← subclass implementation
5. skills/*.md files                         ← auto-injected for all agents
```

### 4.4 Tool Composition Pattern

Every agent assembles its toolset through composition:

```python
class MyAgent(BaseAgent):
    CONFIG_KEY = "my_agent"

    def get_system_prompt(self) -> str:
        return "You are a specialist..."

    def get_extra_tools(self) -> list:
        # Compose from shared factories + custom tools
        bb = make_blackboard_tools(self.name.lower())
        webui = make_webui_tools(self.name.lower(), is_supervisor=False)
        return [*bb, *webui, my_custom_tool]
```

The 10 Band tools are always provided by `BaseAgent._build_agent()` — the subclass only adds domain tools.

---

## 5. Databases

| Database | Path | Engine | Purpose |
|----------|------|--------|---------|
| `blackboard.db` | `data/` | SQLite | Cross-agent knowledge sharing (documents + file index) |
| `webui.db` | `data/` | SQLite WAL | Production board, todos, task updates, activity log |
| `sessions.db` | `data/` | SQLite WAL | TUI chat session persistence |
| `blackboard_files/` | `data/` | Filesystem | Mirrored blackboard file storage |
| ChromaDB | Ephemeral | In-memory | Vector store (not persisted across restarts) |

All SQLite databases use thread-local connections for concurrent agent + server access.

---

## 6. User Interfaces

### 6.1 TUI (`tui/` — Rich-based)

- Direct HTTP to supervisor's `/chat` endpoint (bypasses Band)
- Session-per-tab model with SQLite persistence
- Context injection: last 8 messages from session DB
- Slash commands: `/awake`, `/kill`, `/status`, `/new`, `/session`, `/history`, `/clear`, `/help`, `/quit`
- Auto-starts supervisor on launch

### 6.2 WebUI (`webui/` — FastAPI + vanilla JS)

- FastAPI on `0.0.0.0:8080`
- REST API: `/api/chat`, `/api/blackboard`, `/api/production`, `/api/todos`, `/api/agents`, `/api/projects`, `/api/activity`
- SSE stream: `/api/updates/stream` for real-time task updates
- Static SPA: vanilla JS, no framework, no build step
- Auto-starts supervisor on launch

### 6.3 Entry Points

| Script | Purpose |
|--------|---------|
| `supaband` | Bash wrapper — venv auto-detection, subcommand routing |
| `supaband-tui` | Interactive TUI |
| `supaband-run` | Background fleet launcher |
| `supaband-web` | WebUI server |
| `supaband-cli` | Power-user Band operations |

---

## 7. LLM Configuration

Provider-agnostic. Any OpenAI-compatible endpoint:

```bash
# .env
OPENAI_API_KEY=***                # Required
OPENAI_BASE_URL=https://api.openai.com/v1  # Defaults to OpenAI, supports any compatible endpoint
SUPABAND_MODEL=                    # Fleet-wide default (optional — can override per-agent)
BAND_HUMAN_API_KEY=***            # For on-demand worker creation
```

**Model resolution per agent:**
1. Agent subclass `MODEL` attribute (set `MODEL = ""` to delegate to env var)
2. `SUPABAND_MODEL` env var
3. `ValueError` — no model configured

**Supported providers:** OpenAI, AI/ML API, Featherless, Groq, or any custom endpoint.

---

## 8. Port Architecture

| Port Range | Role | Endpoints |
|-----------|------|-----------|
| 9100 | Supervisor | `/health`, `/stop`, `/chat` |
| 9101+ | Managers | `/health`, `/stop`, `/chat` |
| 9110+ | Blob workers | `/health`, `/stop` |
| 8080 | WebUI | FastAPI (REST + SSE + static) |

Ports are defined in `AGENT_PORTS` dict in `agent_base.py` and `fleet.py`. Extend for new agents.

---

## 9. Startup Sequence (Supervisor)

```
1. Load .env (LLM keys, Band human key)
2. Load agent_config.yaml (all agent credentials)
3. Load skills/*.md (injectable knowledge)
4. Register signal handlers
5. Write PID file
6. Build LangGraph ReAct agent (ChatOpenAI + tools + MemorySaver)
7. Start health HTTP server (daemon thread)
8. Startup purge: parallel stale-message cleanup (all chatrooms)
9. Startup cleanup: remove other agents from idle rooms
10. Auto-start configured managers (AUTO_START_MANAGERS)
11. Main poll loop (forever):
    a. Check stop file
    b. List all chatrooms
    c. Parallel fetch (ThreadPoolExecutor)
    d. Sequential LLM processing
    e. Watchdog (every N cycles)
    f. Sleep 3s or error backoff
12. On stop: remove PID, shutdown health
```

Managers follow the same sequence minus steps 10-11e (no fleet management).

---

## 10. Key Architectural Principles

1. **Framework over product.** The core (`BaseAgent`, tool factories, fleet, blackboard, worker factory) is generic. Demo agents (Supa, Koe, Mave, Forge) are instances — replaceable, renamable, extensible.

2. **Hub-and-spoke delegation.** Supervisor is the single routing point. No direct manager-to-manager delegation. This avoids N×M coordination overhead and makes debugging tractable.

3. **Composition over inheritance for tools.** Agents compose tool lists from shared factories (`make_blackboard_tools`, `make_webui_tools`, etc.) + custom tools. No monolithic tool inheritance.

4. **Separation of concerns: Band for agents, HTTP for users.** User↔supervisor communication bypasses Band (SSL issues, latency). Band is reserved for agent↔agent coordination where @mention routing matters.

5. **On-demand workers, persistent managers.** Only the supervisor and managers run continuously. Workers are spawned per-task, deliver results, and get cleaned up. This keeps the fleet lean.

6. **Placeholder template system.** Worker agent code is generated from a single template with `.format()` placeholders. System prompts live in editable `.md` files — change behavior without touching code.

7. **Three-layer loop prevention.** Echo control, Band Events, and code-level guards work together. The Void sink provides a dead-end mention target. No single layer is sufficient alone.

8. **Single-provider LLM strategy, per-agent model override.** All agents share one `.env` provider config. Any agent can override its model via `MODEL` attribute. No provider is hardcoded.

9. **SQLite for shared state.** Three SQLite databases (WAL mode) for blackboard, sessions, and WebUI. Thread-local connections enable concurrent agent + server access without coordination overhead.

10. **Config-driven agent discovery.** `agent_config.yaml` is the single source of truth. `refresh_agent_ids()` reloads after runtime changes. No hardcoded agent lists in production paths.

---

## 11. Dependencies

```
thenvoi_rest          — Band REST SDK (vendored, not on PyPI)
langgraph >= 0.2      — ReAct agent framework with checkpointing
langchain >= 1.3      — LLM abstractions
langchain-openai >= 0.2 — OpenAI-compatible chat models
chromadb >= 0.5       — Vector store (EphemeralClient)
python-dotenv >= 1.0  — .env loading
pyyaml >= 6.0         — YAML config parsing
httpx                 — HTTP client (web scraping, WebUI proxy)
beautifulsoup4        — HTML parsing
lxml                  — Fast HTML parser (optional)
fastapi               — WebUI server
uvicorn               — ASGI server
rich                  — TUI rendering
```

---

## 12. File Structure

```
supaband/
├── core/                        # Universal framework (invariant)
│   ├── agent_base.py            # BaseAgent runtime
│   ├── config.py                # Config loader
│   ├── blackboard.py            # Shared knowledge base
│   ├── shared_tools.py          # Tool factories (BB, web, file)
│   ├── webui_db.py              # Dashboard database
│   ├── webui_tools.py           # Dashboard tool factory
│   ├── fleet.py                 # Process manager
│   ├── worker_factory.py        # On-demand agent creation
│   ├── session_db.py            # Chat persistence
│   └── sink_agent.py            # Void sink creation
├── agents/                      # Agent implementations (variable)
│   └── <name>/agent.py          # BaseAgent subclass per agent
├── workers/                     # Runtime-spawned workers
│   └── <name>/                  # agent.py + system_prompt.md
├── webui/                       # Web dashboard
│   ├── server.py                # FastAPI
│   └── static/                  # Vanilla JS SPA
├── tui/                         # Terminal interface
│   ├── app.py                   # Rich-based TUI
│   ├── commands.py              # Slash commands
│   └── band_interface.py        # Band helpers
├── skills/                      # Auto-injected agent knowledge
├── config/                      # Template files
├── supaband                     # Entry point (bash)
├── supaband-run                 # Fleet launcher
├── supaband-tui                 # TUI launcher
├── supaband-web                 # WebUI launcher
├── supaband-cli                 # Power-user CLI
├── setup.py                     # Band registration + config gen
├── agent_config.yaml            # Agent credentials (generated)
└── .env                         # LLM provider config
```
