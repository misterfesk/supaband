# Agent Development Patterns — Supaband

## Directory Structure
```
agents/<name>/
├── agent.py          # Main agent class (inherits BaseAgent)
├── tools.py          # @tool-decorated functions
├── system_prompt.md  # Optional: rich system prompt (workers use this)
└── data/             # Runtime data (created automatically)
    ├── agent.pid     # Process PID (managed by fleet)
    └── logs/         # Agent-specific logs
```

## Creating a New Agent

### 1. Agent class (agent.py)
```python
from core.agent_base import BaseAgent
from agents.<name>.tools import TOOLS

class <Name>Agent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="<name>",
            system_prompt="""You are <Name>, the <role>.
            Your responsibility: <describe role>
            Available tools: <list tools>
            Communication protocol: <describe Band usage>""",
            model_tier="standard"  # or "premium" for deeper context
        )
    
    def get_tools(self):
        return TOOLS

if __name__ == "__main__":
    agent = <Name>Agent()
    agent.run()
```

### 2. Tools (tools.py)
```python
from langchain_core.tools import tool
from core.shared_tools import create_file_tools, create_web_tools

# Standard tool factories (shared across agents)
file_read, file_write, file_list = create_file_tools("agents/<name>/data/")

# Custom tools
@tool
def my_custom_tool(param: str) -> str:
    """Description of what this tool does. Used by agent for reasoning."""
    # Implementation
    return result

TOOLS = [file_read, file_write, file_list, my_custom_tool]
```

### 3. Config (agent_config.yaml)
```yaml
agents:
  - name: "<name>"
    handle: "<handle>"       # Display name in Band
    band_id: "<uuid>"        # From Band platform
    model: "deepseek-v4-flash"
    room_id: "<room_uuid>"   # Optional: specific room
```

### 4. Port Registration
In `core/fleet.py`:
```python
AGENT_PORTS = {
    ...
    "<name>": 91XX,
}
FLEET_AGENTS = [..., "<name>"]
```

In `core/agent_base.py`, add port to the AGENT_PORTS dict (mirrors fleet.py).

## BaseAgent Features

### Lifecycle hooks (override as needed)
- `setup()` — Called before polling starts
- `teardown()` — Called during graceful shutdown
- `handle_message(msg)` — Override for custom message processing
- `should_respond(msg)` — Filter which messages to respond to

### Built-in behaviors
- PID file management (write on start, remove on stop)
- Health HTTP endpoint (GET /health returns JSON)
- Band polling loop (configurable interval)
- @mention detection in Band messages
- Sink agent routing (loop breaker — auto after 3 self-replies)
- ThreadPoolExecutor for message handling

### Model tiers
- "standard" — deepseek-v4-flash (default, 32k context)
- "premium" — deeper context model for complex agents

## Shared Tools (core/shared_tools.py)
```python
from core.shared_tools import create_file_tools, create_web_tools, create_blackboard_tools

# File tools (scoped to agent's data directory)
file_read, file_write, file_list = create_file_tools("agents/<name>/data/")

# Web tools (web_scrape via httpx)
web_scrape = create_web_tools()

# Blackboard tools (shared knowledge base)
bb_read, bb_write, bb_search = create_blackboard_tools()
```

## Communication Patterns

### Agent → Agent via Band
Agents communicate through Band chat rooms:
1. Agent A posts a message mentioning @AgentB
2. Agent B's polling loop detects the @mention
3. Agent B processes the message and responds

### Direct agent interaction (Supa tools)
Supa has tools to interact with other agents directly:
- `agent_status(name)` — Check agent health
- `agent_restart(name)` — Restart an agent
- `agent_delegate(name, task)` — Delegate a task
- `blackboard` tools — Write/read shared knowledge

### Worker Factory (Mave tools)
Mave creates workers on-demand:
- `worker_launch(name)` — Start a worker agent
- `worker_kill(name)` — Stop a worker agent
- `worker_status()` — List all workers

## Code Modification Protocol
Follow agent-code-modification.md:
1. Read target agent's agent.py AND tools.py
2. Understand tool structure (@tool-decorated functions)
3. Make targeted changes, preserve patterns
4. Syntax auto-validates on restart
5. Restart agent with kill+restart pattern
6. Verify with health endpoint
7. Log changes to agents/<name>/data/logs/

## Critical Code (modify with extreme caution)
- `core/agent_base.py` — Affects ALL agents. Changes here break everything if wrong.
- `core/config.py` — Agent config loader. Breaking change = no agents can start.
- `core/fleet.py` — Fleet process manager. Breaking change = cannot manage agents.

## Testing Patterns
- Start agent, check health endpoint responds
- Send test message via Band, verify agent responds
- Monitor logs: `tail -f agents/<name>/data/logs/*.log`
- For workers: test Mave's worker_launch/worker_kill round-trip

## Pitfalls
- Forgetting to add port to BOTH fleet.py AND agent_base.py
- Stale PID files after crash — delete manually if process is dead
- Tools that make blocking calls — use ThreadPoolExecutor
- Band API rate limits — agents poll at configured intervals
- .env must be in supaband/ root for all agents
- PYTHONPATH=. required when running agents directly
