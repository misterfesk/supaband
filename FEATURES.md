# Supaband Features

## Core Architecture

### Multi-Agent Fleet
- **4 manager agents** running persistently: Supa (CEO), Koe (Research), Mave (Marketing), Forge (Operations)
- **On-demand specialist workers**: Quill (Content), Pulse (SEO), Canvas (Visual)
- **Blob consumer panel**: 3 persona-based agents for shadow testing (Early Adopter, Skeptical Buyer, Price-Sensitive)
- Each agent is a **LangGraph ReAct agent** with `MemorySaver` checkpointing
- Agents poll Band every 3s for new messages, process through LLM, respond automatically

### Band Integration (Communication Layer)
- Real-time **Band chatrooms** for inter-agent communication
- **@mentions** for targeted delegation (e.g., Supa → Koe: "Research coffee market")
- **Band Events** for non-triggering status updates (no loop risk)
- **Participant management** — add/remove agents from rooms
- **Chatroom lifecycle** — create, export, cleanup, archive
- **Void Sink Agent** — dead-end mention target for loop-free acknowledgments

### Agent Tools Inventory

**Shared Band Tools** (all agents):
| Tool | Description |
|------|-------------|
| `band_respond` | Reply to current chatroom with echo control |
| `band_post_event` | Post non-triggering event (task, thought, error) |
| `band_send_message` | Send to any chatroom with @mentions |
| `band_create_chatroom` | Create new room + add participants |
| `band_add_participant` | Add agent to room |
| `band_remove_participant` | Remove agent from room |
| `band_cleanup_chatroom` | Export + remove agents (room lifecycle end) |

**Shared Blackboard Tools** (all agents):
| Tool | Description |
|------|-------------|
| `bb_post` | Post document to shared knowledge base |
| `bb_retrieve` | Get document by key |
| `bb_list` | List documents by department |
| `bb_search` | Full-text search across blackboard |
| `bb_delete` | Remove document |

**WebUI Tools** (all agents, Supa gets extra):
| Tool | Description |
|------|-------------|
| `production_post` | Post final deliverable to WebUI production board |
| `production_delete` | Remove from production board |
| `todo_create` | Create approval task for human review |
| `todo_delete` | Remove todo |
| `task_update` | Push real-time SSE update (Supa only) |
| `log_activity` | Log significant action for dashboard |

**Supa-Specific Tools** (42 total):
| Tool | Description |
|------|-------------|
| `file_read` / `file_write` / `file_list` | File operations within supaband/ |
| `agent_launch` | Start any agent by name |
| `agent_kill` | Stop any agent |
| `agent_restart` | Restart an agent |
| `agent_status` | Check agent health |
| `agent_list` | List all registered agents |
| `agent_edit_prompt` | Modify system prompt of self or others |
| `worker_create` | Register + create worker agent files |
| `worker_edit_prompt` | Edit worker system prompt |
| `worker_launch` / `worker_kill` | Control worker lifecycle |
| `worker_list` | List all workers |
| `credential_create` | Register on Band, return credentials |
| `band_list_agents` | Discover other agents on Band |
| `band_broadcast` | Message all agents in a department |
| `band_get_chat_id` | Find chatroom by title |
| `band_list_chats` | List all Band chatrooms |
| `band_export_chat` | Save chat history to file |
| `band_get_recent_messages` | Read recent messages from any room |

**Koe-Specific Tools** (32 total):
| Tool | Description |
|------|-------------|
| `research_save` | Save research findings |
| `research_list` | List saved research |
| `research_read` | Read research by key |
| `web_scrape` | Scrape a URL for research |
| `web_search` | Search the web |
| `blob_create_chatroom` | Create blob test room |
| `blob_simulate_consumers` | Run blob consumer simulation |
| `blob_gather_feedback` | Read blob responses from room |
| `blob_export_results` | Export blob test results |
| `blob_cleanup_room` | Clean up after blob test |
| `blob_summarize_feedback` | AI-synthesize consumer feedback |

**Mave-Specific Tools** (27 total):
| Tool | Description |
|------|-------------|
| `file_read` / `file_write` | File operations |
| `worker_create` | Create marketing specialists |
| `worker_edit_prompt` | Edit worker system prompts |
| `worker_launch` / `worker_kill` | Control worker lifecycle |
| `worker_list` | List marketing workers |
| `credential_create` | Register on Band |
| `production_check` | Review production board items |

### WebUI Dashboard
- **Real-time SSE stream** — task updates push to browser instantly
- **Production Board** — agent deliverables appear as cards with type badges
- **Todo Queue** — approval tasks created by agents for human review
- **Agent Roster** — live status of all agents with health metrics
- **Chat Interface** — send messages to Supa from browser
- **Blackboard Browser** — view shared documents
- **Project Tracking** — create/view projects
- **Dark theme** — designed for long monitoring sessions

### Terminal UI (TUI)
- Interactive chat with Supa via Rich TUI
- Session persistence (SQLite-backed)
- Context injection from prior messages
- `/new`, `/session`, `/history` commands
- Fleet status at a glance
- Agent auto-start on TUI launch

### Worker Factory
- On-demand agent creation — register on Band + generate Python files
- Prompt editing — modify worker system prompts at runtime
- Lifecycle management — launch/kill/list workers
- Credential-only mode — register on Band without creating files

### Loop Prevention System
- **Echo parameter** on `band_respond` — `echo=True` for substantive replies, `echo=False` for acks
- **Void Sink Agent** — dead-end mention target that never responds
- **Self-echo detection** — agents ignore their own messages
- **Chatroom cleanup** — `band_cleanup_chatroom` removes idle agents from rooms
- **Band Events** — non-triggering status updates (no @mentions)

### Fleet Management
- PID file tracking per agent
- HTTP health endpoints on ports 9100–9106
- Graceful stop (HTTP → SIGTERM fallback)
- Background launch with log capture
- Restart without data loss
- Watchdog — Supa monitors manager health every 5 cycles

### Blackboard (Shared Knowledge Base)
- SQLite-backed with filesystem mirror
- Cross-department file sharing
- Tag-based organization
- Full-text search
- Author/department tracking
- Timestamp-based versioning

### Skills System
- Drop `.md` files into `skills/` — auto-injected into all agent system prompts
- Fleet management patterns
- Market research methodology
- Agent code modification protocol
- Agent development patterns

### Shadow Testing (Blob System)
- 3 persona-based consumer agents (Early Adopter, Skeptical Buyer, Price-Sensitive)
- Simulated consumer discussion rooms
- Structured feedback gathering
- AI-powered feedback synthesis
- Export-ready results

---

## Technical Details

### Stack
- **Agent Framework:** LangGraph (ReAct agent + MemorySaver checkpointing)
- **LLM:** Configurable via SUPABAND_MODEL env var (any OpenAI-compatible model)
- **Communication:** Band platform (thenvoi_rest SDK)
- **WebUI:** FastAPI + vanilla JavaScript (SSE for real-time)
- **TUI:** Rich library
- **Databases:** SQLite (blackboard, sessions, webui)
- **Vector Store:** ChromaDB (EphemeralClient)

### Health & Monitoring
- Each agent serves HTTP on `http://127.0.0.1:<port>/health`
- Returns JSON: `{cycles, messages_processed, uptime_seconds, model, status}`
- Fleet status via `./supaband status` or `./supaband-cli fleet-status`

### Port Map
| Agent | Port |
|-------|------|
| Supa | 9100 |
| Koe | 9101 |
| Mave | 9105 |
| Forge | 9106 |
| Blobw1 | 9110 |
| Blobw2 | 9111 |
| Blobw3 | 9112 |
| WebUI | 8080 (default) |
