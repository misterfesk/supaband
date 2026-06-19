"""WebUI tools — LangChain tools for agents to interact with the WebUI.

These tools let agents:
  - Post final deliverables to the Production section (production_post)
  - Create approval tasks for the user (todo_create)
  - Push real-time updates to the user via SSE (task_update — Supa only)
  - Log significant actions for the dashboard (log_activity)

All write to the shared webui.db (SQLite WAL — safe for concurrent access).
"""

from __future__ import annotations

from langchain_core.tools import tool
from core.config import PROJECT_ROOT
from core.webui_db import get_webui_db
from pathlib import Path


def make_webui_tools(agent_name: str, is_supervisor: bool = False) -> list:
    """Create WebUI tools for an agent.

    Args:
        agent_name: Name of the calling agent (e.g. "supa", "koe", "quill")
        is_supervisor: If True, includes task_update (SSE push to user).
                       Only Supa should have this.
    """

    @tool
    def production_post(item_type: str, title: str, content: str,
                        metadata: str = "{}") -> str:
        """Post a FINAL deliverable to the Production section of the WebUI.

        This is for user-visible finished work — NOT drafts or inter-agent sharing.
        Use bb_post for sharing with other agents; use production_post for
        deliverables the user should see in the Production dashboard.

        The content will be rendered as markdown in the WebUI postcard view.

        Args:
            item_type: Type of deliverable. One of:
                "post" (social media post), "report" (research report),
                "brief" (creative brief), "image" (visual description/demo),
                "analysis" (data analysis), "campaign" (campaign plan),
                "email" (email campaign), "article" (blog post/article)
            title: Short title for the deliverable
            content: Full content in markdown (will be displayed to user)
            metadata: JSON string with extra info, e.g.
                '{"channel": "LinkedIn", "word_count": 450, "format": "carousel"}'
        """
        db = get_webui_db()
        result = db.add_production(
            agent_name=agent_name,
            item_type=item_type,
            title=title,
            content=content,
            metadata=metadata,
        )
        if result["ok"]:
            return (f"✅ Production item posted: '{title}' (type={item_type}, "
                    f"id={result['id']}). User can view it in the Production section.")
        return f"❌ Failed to post production item: {result}"

    @tool
    def todo_create(task: str, priority: str = "normal") -> str:
        """Create a task that needs USER APPROVAL before proceeding.

        The task appears in the WebUI Todo section where the user can approve
        or reject it. Use this when you need the user's decision to continue.

        Args:
            task: Clear description of what needs approval and why.
                  Example: "Approve Q3 campaign budget: $5,000 across 3 channels"
            priority: One of "low", "normal", "high", "urgent". Default "normal".
        """
        db = get_webui_db()
        result = db.add_todo(
            agent_name=agent_name,
            task=task,
            priority=priority,
        )
        if result["ok"]:
            return (f"✅ Todo created (id={result['id']}, priority={priority}). "
                    f"User will see it in the Todo section for approval.")
        return f"❌ Failed to create todo: {result}"

    @tool
    def log_activity(action: str, detail: str = "") -> str:
        """Log a significant action to the agent activity feed.

        This appears in the WebUI dashboard and agent profile pages.
        Use for important milestones, task completions, or notable events.

        Args:
            action: Short action label. Examples: "delegated", "researched",
                    "blob_test", "campaign_started", "report_delivered"
            detail: Optional longer description
        """
        db = get_webui_db()
        db.log_activity(agent_name=agent_name, action=action, detail=detail)
        return f"✅ Activity logged: {action}"

    tools = [production_post, todo_create, log_activity]

    # ── Supervisor-only: task_update (SSE push to user) ──────
    if is_supervisor:
        @tool
        def task_update(update_type: str, content: str) -> str:
            """Push a real-time update to the user's WebUI.

            This is how you deliver results to the user AFTER the initial chat
            response. When managers deliver work via Band, use this to push
            their results to the user's browser in real-time.

            The update appears as a new message in the user's chat stream.

            Args:
                update_type: One of:
                    "info" — progress update ("Koe is running blob test...")
                    "result" — manager delivered results ("Marketing campaign ready...")
                    "warning" — issue or delay ("Research taking longer than expected...")
                    "complete" — task fully done ("Campaign launched. All deliverables posted.")
                content: The update message (markdown supported)
            """
            db = get_webui_db()
            result = db.add_update(
                update_type=update_type,
                content=content,
                agent_name=agent_name,
            )
            if result["ok"]:
                return f"✅ Update pushed to user ({update_type})."
            return f"❌ Failed to push update: {result}"

        tools.append(task_update)

        # ── Production find + delete ────────────────────────────

        @tool
        def production_find(title_query: str = "", agent_name: str = "",
                            item_type: str = "") -> str:
            """Search for production items in the WebUI by title, agent, or type.

            Use this when the user asks to find a specific production item,
            or before deleting one (to get the ID).

            Args:
                title_query: Partial title to search for (case-insensitive)
                agent_name: Filter by agent (e.g. "quill", "koe", "canvas")
                item_type: Filter by type ("post", "report", "brief", "analysis", "campaign")
            """
            db = get_webui_db()
            items = db.find_production(
                title_query=title_query, agent_name=agent_name,
                item_type=item_type, limit=20,
            )
            if not items:
                return "No production items found matching your search."
            lines = [f"Found {len(items)} production item(s):"]
            for it in items:
                lines.append(f"  ID={it['id']} | {it['agent_name']} | {it['item_type']} | {it['title']}")
            return "\n".join(lines)

        @tool
        def production_delete(item_id: int) -> str:
            """Delete a production item from the WebUI by its ID.

            Use production_find() first to locate the item ID if unknown.
            This permanently removes the item from the Production section.

            Args:
                item_id: The numeric ID of the production item to delete
            """
            db = get_webui_db()
            result = db.delete_production(item_id)
            if result.get("ok"):
                return f"✅ Deleted production item: '{result['title']}' (id={item_id})"
            return f"❌ {result.get('error', 'Delete failed')}"

        tools.append(production_find)
        tools.append(production_delete)

        # ── Todo delete ─────────────────────────────────────────

        @tool
        def todo_delete(todo_id: int) -> str:
            """Delete a todo item from the WebUI by its ID.

            This permanently removes the todo regardless of its status
            (pending, approved, or rejected). Use todo_create to make new ones.

            Args:
                todo_id: The numeric ID of the todo to delete
            """
            db = get_webui_db()
            result = db.delete_todo(todo_id)
            if result.get("ok"):
                return f"✅ Deleted todo: '{result['task'][:80]}' (id={todo_id})"
            return f"❌ {result.get('error', 'Delete failed')}"

        tools.append(todo_delete)

        # ── WebUI server control ────────────────────────────────

        @tool
        def webserver_start() -> str:
            """Start the Supaband WebUI server and return the access link.

            Launches the web server on port 8080 (if not already running)
            and returns the LAN URL that other devices on the same network
            can use to access the dashboard.

            No arguments needed — the server auto-starts and returns the link.
            """
            import subprocess as _sp
            import socket as _sock

            # Check if server is already running on 8080
            try:
                s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(("127.0.0.1", 8080))
                s.close()
                if result == 0:
                    # Already running — just return the link
                    try:
                        lan_ip = _sock.gethostbyname(_sock.gethostname())
                    except Exception:
                        lan_ip = "127.0.0.1"
                    return f"✅ WebUI server is already running.\nAccess: http://{lan_ip}:8080"
            except Exception:
                pass

            # Launch the server
            server_path = str(PROJECT_ROOT / "webui" / "server.py")
            venv_py = str(PROJECT_ROOT.parent / ".venv" / "bin" / "python3")
            if not Path(venv_py).exists():
                venv_py = "python3"

            try:
                _sp.Popen(
                    [venv_py, server_path, "--port", "8080"],
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    start_new_session=True,
                )
            except Exception as e:
                return f"❌ Failed to start server: {e}"

            # Wait briefly for startup
            import time as _time
            _time.sleep(3)

            # Get LAN IP
            try:
                s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                s.close()
            except Exception:
                try:
                    lan_ip = _sock.gethostbyname(_sock.gethostname())
                except Exception:
                    lan_ip = "127.0.0.1"

            return (f"✅ Supaband WebUI server started.\n"
                    f"Access from this device: http://127.0.0.1:8080\n"
                    f"Access from other devices on your network: http://{lan_ip}:8080")

        tools.append(webserver_start)

    return tools
