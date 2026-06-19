# Supaband Skills Directory

## Skills in this directory
These skills are loaded by Supaband agents (Supa, Koe, Mave, Forge, workers) via their system prompts.

- **agent-code-modification.md** — Protocol for modifying another agent's code
- **market-research.md** — Market research methodology for Koe
- **fleet-management.md** — Fleet start/stop/debug/health patterns
- **agent-development-patterns.md** — Standard patterns for adding/modifying agents

## Project-Level Skills (band-of-agents/skills/)
- **../skills/hermes-skills/** — Full copy of Agent Q's Hermes skill library (114 skills)
- **../skills/agent-coding-skills/** — Coding agent skills (find-skills, git-commit, langgraph-*, python-*, vector-index-tuning)
- **../skills/band-skills/** — Band platform SDK skills (from Band documentation)

Load order: supaband/skills/ → skills/agent-coding-skills/ → skills/hermes-skills/ → skills/band-skills/
