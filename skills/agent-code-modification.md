# Agent Code Modification Protocol

When modifying another agent's code, follow this protocol:

1. **Read first** — Use file_read() on the target agent's agent.py AND tools.py
2. **Understand the tool structure** — Each tool is a @tool-decorated function
3. **Make targeted changes** — Modify only what's necessary, preserve existing patterns
4. **Test the syntax** — The agent will auto-validate on restart
5. **Restart the agent** — Use agent_restart(name) to apply changes
6. **Verify** — Use agent_status() to confirm the agent came back up
7. **Log your changes** — Write a brief note to agents/<name>/data/logs/

Important paths:
- Agent code: agents/<name>/agent.py
- Agent tools: agents/<name>/tools.py
- Shared code: core/agent_base.py
- Config: core/config.py

Never modify core/agent_base.py without careful consideration — it affects all agents.
