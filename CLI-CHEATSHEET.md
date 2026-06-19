# Supaband CLI — Cheatsheet

All commands run from `supaband/` directory.

## Quick Start

```bash
# One-command entry point
./supaband              # Launch TUI (interactive Supa chat)
./supaband --new        # TUI with fresh session
./supaband run          # Start all manager agents
./supaband status       # Show fleet PIDs + health
./supaband stop         # Stop all agents
./supaband web          # Start WebUI dashboard

# Legacy scripts (also work)
./supaband-run supa koe mave forge  # Start specific agents
./supaband-run --fg supa            # Foreground (for debugging)
```

---

## Fleet Commands

```
./supaband-cli fleet-status           Show all agents, PIDs, uptime
./supaband-cli stop                   Graceful stop (HTTP → SIGTERM fallback)
./supaband-cli start [supa] [koe]    Launch agents as background processes
./supaband-cli start supa koe mave forge  # Launch full fleet
```

---

## Band Commands (-a <agent> required)

```
./supaband-cli -a supa chats                          List all Band chatrooms
./supaband-cli -a supa room -t "Title"                 Create chatroom
./supaband-cli -a supa room -t "Title" -m koe -M "msg" Create + add Koe + send
./supaband-cli -a supa mention koe -c <id> "msg"       @mention Koe in existing room
./supaband-cli -a koe export <id>                       Save chat history to .md
./supaband-cli -a supa poll -c <id> -m koe -t 120      Watch for replies
./supaband-cli -a supa agent-info                       Show agent identity
```

---

## Agents

| Agent  | Handle             | Port  | Model              | Role |
|--------|--------------------|-------|--------------------|------|
| Supa   | @zoha/supa-bz      | 9100  | configurable  | CEO & Supervisor |
| Koe    | @zoha/koe-bz       | 9101  | configurable  | Research Manager |
| Mave   | @zoha/mave-bz      | 9105  | configurable  | Marketing Manager |
| Forge  | @zoha/forge-bz     | 9106  | configurable  | Operations Manager |

### Specialist Workers (on-demand)

| Worker | Handle             | Role |
|--------|--------------------|------|
| Quill  | @zoha/quill-bz     | Content Strategist |
| Pulse  | @zoha/pulse-bz     | SEO Analyst |
| Canvas | @zoha/canvas-bz    | Visual Production |
---

## Architecture

```
supaband/
├── agents/          # Manager agents (supa, koe, mave, forge)
├── workers/         # Specialist workers (quill, pulse, canvas)
├── blob/            # Shadow testing consumer panel
├── core/            # Shared infrastructure (agent_base, config, blackboard, etc.)
├── webui/           # Web dashboard (FastAPI)
├── tui/             # Terminal UI (Rich)
├── scripts/         # Utility scripts
├── skills/          # Agent skill files
├── config/          # Templates (.env, agent_config.yaml)
├── supaband         # Single entry point
├── supaband-cli     # Fleet & Band management CLI
├── supaband-tui     # Terminal UI
├── supaband-web     # WebUI launcher
└── setup.sh         # One-command setup
```

Each agent:
- Writes a `.pid` file on startup
- Runs an HTTP health server on its port
- Polls Band every 3s for new messages
- Processes messages through LangGraph ReAct agent
- Responds via Band automatically

---

## Health Endpoints

```bash
curl http://127.0.0.1:9100/health  # Supa
curl http://127.0.0.1:9101/health  # Koe
curl http://127.0.0.1:9105/health  # Mave
curl http://127.0.0.1:9106/health  # Forge
```

Returns: `{"status":"ok","cycles":42,"messages_processed":15,"uptime_seconds":3600,"model":"...configurable via SUPABAND_MODEL..."}`
