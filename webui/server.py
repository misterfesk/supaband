#!/usr/bin/env python3
"""Supaband WebUI Server — FastAPI backend.

Serves the Supaband web dashboard with:
  - REST API for chat, blackboard, production, todos, agents, projects
  - SSE stream for real-time task updates
  - Static file serving for the frontend
  - Auto-starts Supa if not running

Usage:
    python3 webui/server.py [--port 8080] [--host 0.0.0.0]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Path setup ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.webui_db import WebUIDB, get_webui_db
from core.blackboard import get_blackboard
from core.session_db import SessionDB
from core.config import PROJECT_ROOT, load_agent_config
from core import fleet

# ── Agent roster (from agent_config.yaml) ───────────────────────
AGENT_ROSTER = {
    "supa": {"role": "CEO & Supervisor", "department": "Executive", "port": 9100},
    "koe": {"role": "Research Manager", "department": "Research", "port": 9101},
    "mave": {"role": "Marketing & Digital Production Manager", "department": "Marketing", "port": 9105},
    "forge": {"role": "Operations Manager", "department": "Operations", "port": 9106},
    "quill": {"role": "Content Strategist & Copywriter", "department": "Marketing", "port": 0},
    "pulse": {"role": "SEO & Digital Marketing Analyst", "department": "Marketing", "port": 0},
    "canvas": {"role": "Visual Production Coordinator", "department": "Marketing", "port": 0},
    "blobw1": {"role": "Consumer Panel — Early Adopter", "department": "Research", "port": 9110},
    "blobw2": {"role": "Consumer Panel — Skeptical Buyer", "department": "Research", "port": 9111},
    "blobw3": {"role": "Consumer Panel — Price-Sensitive", "department": "Research", "port": 9112},
    "void": {"role": "Message Sink (loop breaker)", "department": "System", "port": 0},
}

# ── App ──────────────────────────────────────────────────────────
app = FastAPI(title="Supaband", docs_url=None, redoc_url=None)
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Helpers ──────────────────────────────────────────────────────

def _http_get(url: str, timeout: float = 3.0) -> dict | None:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def ensure_supa_running() -> bool:
    """Ensure Supa is running. Auto-start if needed."""
    if _http_get("http://127.0.0.1:9100/health"):
        return True
    print("  Starting Supa...")
    result = fleet.launch_agent("supa")
    if not result.get("ok"):
        print(f"  Failed to start Supa: {result.get('error', 'unknown')}")
        return False
    # Wait for health endpoint
    for _ in range(20):
        if _http_get("http://127.0.0.1:9100/health"):
            print("  Supa is online.")
            return True
        time.sleep(1)
    print("  Supa started but health endpoint not responding.")
    return False


def get_agent_health(name: str) -> dict:
    """Get agent health from its HTTP endpoint."""
    port = AGENT_ROSTER.get(name, {}).get("port", 0)
    if port == 0:
        return {"running": False, "reason": "no health port"}
    return _http_get(f"http://127.0.0.1:{port}/health") or {"running": False}


# ── Chat endpoints (proxy to Supa) ───────────────────────────────

@app.post("/api/chat")
async def chat(payload: dict):
    """Send a message to Supa and get a response."""
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    session_id = payload.get("session_id", "webui")
    context = payload.get("context", "")

    # Store in session DB (create session if it doesn't exist)
    db = SessionDB()
    if not db.get_session(session_id):
        db.create_session(session_id, "webui", "")
    db.add_message(session_id, "user", message)

    # Forward to Supa's existing /chat endpoint
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("http://127.0.0.1:9100/chat", json={
                "message": message,
                "context": context,
                "session_id": session_id,
            })
            data = resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "Supa is not running. Start it from the Agents tab.")
    except Exception as e:
        raise HTTPException(500, f"Chat error: {e}")

    if data.get("status") == "error":
        raise HTTPException(500, data.get("error", "unknown"))

    response = data.get("response", "")
    db.add_message(session_id, "supa", response)
    return {"response": response, "status": "ok"}


@app.get("/api/chat/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 100):
    """Get message history for a session."""
    db = SessionDB()
    msgs = db.get_messages(session_id, limit=limit)
    return {"messages": msgs}


@app.post("/api/chat/session")
async def create_session(payload: dict):
    """Create a new chat session."""
    name = payload.get("name", "session")
    db = SessionDB()
    session_id = f"web-{datetime.now():%Y%m%d-%H%M%S}"
    db.create_session(session_id, name, "")
    return {"session_id": session_id, "name": name}


@app.get("/api/chat/sessions")
async def list_sessions():
    """List all chat sessions."""
    db = SessionDB()
    sessions = db.list_sessions()
    return {"sessions": sessions}


# ── SSE: Real-time task updates ──────────────────────────────────

@app.get("/api/stream/{session_id}")
async def stream_updates(session_id: str):
    """SSE stream — pushes task_updates in real-time."""
    async def event_generator():
        last_id = 0
        wdb = get_webui_db()
        while True:
            try:
                updates = wdb.get_updates_since(session_id, last_id)
                for u in updates:
                    data = {
                        "id": u["id"],
                        "type": u["update_type"],
                        "content": u["content"],
                        "agent": u["agent_name"],
                        "timestamp": u["created_at"],
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    last_id = u["id"]
            except Exception:
                pass
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/updates")
async def get_updates(session_id: str = "", limit: int = 50):
    """Get recent task updates (history)."""
    wdb = get_webui_db()
    updates = wdb.get_updates(session_id=session_id, limit=limit)
    return {"updates": updates}


# ── Blackboard ───────────────────────────────────────────────────

@app.get("/api/blackboard")
async def list_blackboard(department: str = "", limit: int = 50):
    """List blackboard documents."""
    bb = get_blackboard()
    docs = bb.list_all(department=department, limit=limit)
    return {"documents": docs}


@app.get("/api/blackboard/{key}")
async def get_blackboard_doc(key: str):
    """Retrieve a specific blackboard document."""
    bb = get_blackboard()
    result = bb.retrieve(key=key)
    if not result["ok"]:
        raise HTTPException(404, result.get("error", "not found"))
    return {"doc": result["doc"]}


# ── Production ───────────────────────────────────────────────────

@app.get("/api/production")
async def list_production(agent_name: str = "", item_type: str = "",
                          project_id: str = "", limit: int = 50):
    """List production items (postcards)."""
    wdb = get_webui_db()
    items = wdb.list_production(
        project_id=project_id, agent_name=agent_name,
        item_type=item_type, limit=limit
    )
    return {"items": items}


@app.get("/api/production/{item_id}")
async def get_production_item(item_id: int):
    """Get a specific production item."""
    wdb = get_webui_db()
    item = wdb.get_production(item_id)
    if not item:
        raise HTTPException(404, "not found")
    return {"item": item}


# ── Todos ────────────────────────────────────────────────────────

@app.get("/api/todos")
async def list_todos(status: str = "", project_id: str = "", limit: int = 50):
    """List todos."""
    wdb = get_webui_db()
    todos = wdb.list_todos(status=status, project_id=project_id, limit=limit)
    return {"todos": todos}


@app.post("/api/todos/{todo_id}/approve")
async def approve_todo(todo_id: int, payload: Optional[dict] = None):
    """Approve a todo."""
    note = (payload or {}).get("note", "")
    wdb = get_webui_db()
    result = wdb.resolve_todo(todo_id, "approved", note)
    return result


@app.post("/api/todos/{todo_id}/reject")
async def reject_todo(todo_id: int, payload: Optional[dict] = None):
    """Reject a todo."""
    note = (payload or {}).get("note", "")
    wdb = get_webui_db()
    result = wdb.resolve_todo(todo_id, "rejected", note)
    return result


# ── Agents ───────────────────────────────────────────────────────

@app.get("/api/agents")
async def list_agents():
    """List all agents with their current status."""
    agents = []
    for name, info in AGENT_ROSTER.items():
        status = fleet.list_agent_status().get(name, {"running": False})
        health = get_agent_health(name) if status.get("running") else {}
        # Get recent activity
        wdb = get_webui_db()
        activity = wdb.get_agent_activity(name, limit=5)
        agents.append({
            "name": name,
            "role": info["role"],
            "department": info["department"],
            "running": status.get("running", False),
            "pid": status.get("pid"),
            "health": health,
            "activity": activity,
        })
    return {"agents": agents}


@app.get("/api/agents/{name}/profile")
async def agent_profile(name: str):
    """Get detailed agent profile."""
    name = name.lower()
    if name not in AGENT_ROSTER:
        raise HTTPException(404, "unknown agent")

    info = AGENT_ROSTER[name]
    status = fleet.list_agent_status().get(name, {"running": False})
    health = get_agent_health(name) if status.get("running") else {}

    # Get config entry
    try:
        config = load_agent_config()
        # Find the agent in config by name
        agent_config = {}
        for key, entry in config.items():
            if (entry.get("name") or key).lower() == name:
                agent_config = {
                    "handle": entry.get("handle", ""),
                    "role": entry.get("role", ""),
                    "description": entry.get("description", ""),
                }
                break
    except Exception:
        agent_config = {}

    wdb = get_webui_db()
    activity = wdb.get_agent_activity(name, limit=20)

    return {
        "name": name,
        "role": info["role"],
        "department": info["department"],
        "running": status.get("running", False),
        "pid": status.get("pid"),
        "health": health,
        "config": agent_config,
        "activity": activity,
    }


@app.post("/api/agents/{name}/launch")
async def launch_agent(name: str):
    """Start an agent."""
    name = name.lower()
    result = fleet.launch_agent(name)
    return result


@app.post("/api/agents/{name}/kill")
async def kill_agent(name: str):
    """Stop an agent."""
    name = name.lower()
    result = fleet.kill_agent(name)
    return result


@app.post("/api/agents/{name}/restart")
async def restart_agent(name: str):
    """Restart an agent."""
    name = name.lower()
    fleet.kill_agent(name)
    time.sleep(1)
    result = fleet.launch_agent(name)
    return result


# ── Projects ─────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    wdb = get_webui_db()
    projects = wdb.list_projects()
    # Add stats for each project
    result = []
    for p in projects:
        stats = wdb.get_project_stats(p["id"])
        result.append({**p, "stats": stats})
    return {"projects": result}


@app.post("/api/projects")
async def create_project(payload: dict):
    """Create a new project."""
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name required")
    description = payload.get("description", "")
    wdb = get_webui_db()
    result = wdb.create_project(name=name, description=description)
    return result


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project dashboard data."""
    wdb = get_webui_db()
    project = wdb.get_project(project_id)
    if not project:
        raise HTTPException(404, "project not found")
    stats = wdb.get_project_stats(project_id)
    return {**project, "stats": stats}


# ── Dashboard ────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def dashboard(project_id: str = ""):
    """Get aggregated dashboard data."""
    wdb = get_webui_db()
    pid = project_id or WebUIDB.DEMO_PROJECT_ID

    # Agent status summary
    agents = []
    online_count = 0
    for name, info in AGENT_ROSTER.items():
        if name == "void":
            continue
        status = fleet.list_agent_status().get(name, {"running": False})
        is_running = status.get("running", False)
        if is_running:
            online_count += 1
        agents.append({
            "name": name,
            "role": info["role"],
            "department": info["department"],
            "running": is_running,
        })

    # Recent activity
    activity = wdb.get_all_activity(limit=15)

    # Counts
    stats = wdb.get_project_stats(pid)

    return {
        "agents_online": online_count,
        "agents_total": len(agents),
        "agents": agents,
        "activity": activity,
        "stats": stats,
    }


# ── Static serving ───────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main SPA page."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Supaband</h1><p>Frontend not built yet.</p>")
    return HTMLResponse(index_path.read_text())


# ── Startup ──────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Initialize on server start."""
    wdb = WebUIDB()
    wdb.init_demo_data()
    print("  WebUI DB initialized (demo project seeded)")


# ── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Supaband WebUI Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8080, help="Port")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  SUPABAND — WebUI Server")
    print("=" * 60)

    # Ensure Supa is running
    if ensure_supa_running():
        print("  Supa: ONLINE")
    else:
        print("  Supa: OFFLINE (chat will not work until started)")

    # Init DB
    WebUIDB().init_demo_data()
    print("  Database: initialized")

    # Get IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    print(f"\n  Supaband running at:")
    print(f"    http://{ip}:{args.port}")
    print(f"    http://127.0.0.1:{args.port}")
    print(f"\n  Press Ctrl+C to stop.")
    print("=" * 60 + "\n")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
