# Fleet Management — Supaband Multi-Agent System

## Architecture
All agents run as independent OS processes, each with:
- A PID file at `agents/<name>/data/agent.pid`
- A health HTTP endpoint at `http://127.0.0.1:<port>/health`
- Their own LangGraph ReAct agent loop polling Band

Health ports: supa=9100, koe=9101, mave=9105, forge=9106, blobw1=9110, blobw2=9111, blobw3=9112

## Starting Agents

### All at once (recommended)
```
./supaband-run          # launches supa + koe + mave + forge
./supaband              # single entry: TUI + fleet + web
```

### Individual agents
```
cd supaband
PYTHONPATH=. python3 agents/<name>/agent.py &
```

### Workers (Quill, Pulse, Canvas)
```
PYTHONPATH=. python3 scripts/start_workers.py
```
Workers are managed by Mave via worker_launch/worker_kill tools.

## Health Checks

### Quick health
```
./supaband-cli status
```

### Detailed health
```
PYTHONPATH=. python3 scripts/fleet_health.py
```

### Manual health endpoint check
```
curl http://127.0.0.1:9100/health   # Supa
curl http://127.0.0.1:9101/health   # Koe
curl http://127.0.0.1:9105/health   # Mave
curl http://127.0.0.1:9106/health   # Forge
```

Health response: `{"pid": 12345, "cycles": 42, "messages_processed": 15, "uptime_seconds": 3600, "model": "deepseek-v4-flash", ...}`

## Stopping Agents

### All at once
```
./supaband-cli stop
```

### Individual
```
kill $(cat agents/<name>/data/agent.pid)
```

### Force kill (if PID file stale)
```
pkill -f "agents/<name>/agent.py"
```

## Common Issues

### Agent won't start
1. Check .env has OPENAI_API_KEY set
2. Check agent_config.yaml has correct agent entries
3. Verify venv is active: `. .venv/bin/activate`
4. Check no stale PID file: `rm agents/<name>/data/agent.pid` if process dead
5. Check port not in use: `lsof -i :<port>`

### Agent starts but doesn't poll
1. Check Band credentials: agent_config.yaml has valid band_api_key
2. Check Band room exists and agent is participant
3. Check agent is registered with Band
4. Look at agent logs: `tail -f agents/<name>/data/logs/*.log`

### Agent loops / floods Band
1. Stop the agent immediately: `kill $(cat agents/<name>/data/agent.pid)`
2. Check if Void sink agent is active (loop breaker)
3. Review last messages in Band room
4. Agent will auto-route to Void after 3 consecutive self-replies

### Port conflict
1. Find what's on the port: `lsof -i :<port>`
2. Kill stale process or change port in core/fleet.py and core/agent_base.py
3. Ports must match between fleet.py (AGENT_PORTS) and agent_base.py

## Log Locations
- Agent logs: `agents/<name>/data/logs/`
- Process stdout/stderr: terminal where agent was launched
- Fleet manager logs: inline with supaband-cli output
- Band message traces: search agent logs for "Band message"

## Restart After Code Change
1. Stop the agent: `kill $(cat agents/<name>/data/agent.pid)`
2. Verify PID file removed after 2-3 seconds
3. Restart: `PYTHONPATH=. python3 agents/<name>/agent.py &`
4. Health check: wait 5 seconds, then `curl http://127.0.0.1:<port>/health`

## Adding a New Agent
1. Create `agents/<name>/agent.py` (subclass BaseAgent)
2. Create `agents/<name>/tools.py` (define @tool functions)
3. Add entry to `agent_config.yaml` (name, handle, band_id, model)
4. Add port to `core/fleet.py` (AGENT_PORTS) and `core/agent_base.py`
5. Add to FLEET_AGENTS list in `core/fleet.py`
6. Register agent with Band (get band_id from Band platform)
7. Test: start agent, check health endpoint, verify Band polling

## Worker Management
Workers (Quill, Pulse, Canvas) are different from core agents:
- Created on-demand by Mave via worker_factory
- Use `core/worker_factory.py` to launch/kill
- Store state in `workers/<name>/data/`
- Not in FLEET_AGENTS — managed separately
