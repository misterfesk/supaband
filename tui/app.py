"""Supaband TUI — Terminal chat interface for interacting with Supa.

Architecture:
  - Direct HTTP chat: TUI → POST localhost:9100/chat → Supa's LLM → response
  - No Band dependency for user↔Supa communication (fixes SSL/network issues)
  - Band is still used by Supa for agent-to-agent delegation (Supa → Koe)
  - SQLite session management with per-session context
  - Auto-starts Supa on launch if not running
  - Slash commands for fleet management (/kill, /awake, /status, etc.)
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.rule import Rule
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.align import Align

# ── Path setup ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.session_db import SessionDB
from tui.commands import COMMANDS
from core import fleet

# ── Constants ───────────────────────────────────────────────────
COLOR_USER = "cyan"
COLOR_SUPA = "green"
COLOR_SYS = "dim"
COLOR_CMD = "yellow"
COLOR_ERR = "red"
COLOR_HEAD = "bold blue"

SUPA_PORT = 9100
CHAT_URL = f"http://127.0.0.1:{SUPA_PORT}/chat"
HEALTH_URL = f"http://127.0.0.1:{SUPA_PORT}/health"
CHAT_TIMEOUT = 120  # seconds for LLM response
CONTEXT_MSGS = 8    # prior messages to inject as context


# ── HTTP helpers ────────────────────────────────────────────────

def _http_get(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _http_post(url: str, data: dict, timeout: float = 120.0) -> dict | None:
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode())
            return {"error": err_body.get("error", str(e)), "status": "error"}
        except Exception:
            return {"error": str(e), "status": "error"}
    except Exception as e:
        return {"error": str(e), "status": "error"}


def supa_is_running() -> bool:
    """Check if Supa's health endpoint responds."""
    return _http_get(HEALTH_URL) is not None


def wait_for_supa(timeout: float = 15.0) -> bool:
    """Wait for Supa to be ready (health endpoint responds)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if supa_is_running():
            return True
        time.sleep(0.5)
    return False


def send_to_supa(message: str, context: str, session_id: str) -> dict:
    """Send a message to Supa via direct HTTP and get response."""
    result = _http_post(CHAT_URL, {
        "message": message,
        "context": context,
        "session_id": session_id,
    }, timeout=CHAT_TIMEOUT)
    return result or {"error": "no response", "status": "error"}


# ── TUI App ─────────────────────────────────────────────────────

class TUIApp:
    """Main TUI application."""

    def __init__(self):
        self.console = Console()
        self.db = SessionDB()
        self.current_session: str | None = None
        self._running = True
        self._clear_screen = False
        self.session_name = "none"

    # ── Initialization ───────────────────────────────────────────

    def init_supa(self) -> bool:
        """Ensure Supa is running. Auto-start if needed.

        Returns True if Supa is ready for direct chat.
        """
        # Check if already running
        if supa_is_running():
            return True

        # Auto-start Supa
        self.print_system("Starting Supa...")
        result = fleet.launch_agent("supa")
        if not result["ok"]:
            self.print_error(f"Failed to start Supa: {result.get('error', 'unknown')}")
            return False

        # Wait for health endpoint
        self.print_system(f"Supa launched (PID {result.get('pid')}). Waiting for readiness...")
        if not wait_for_supa(timeout=20.0):
            self.print_error("Supa started but health endpoint not responding. Check logs.")
            return False

        self.print_system("✅ Supa is online.")
        return True

    def init_default_session(self):
        """Create or resume a default session."""
        sessions = self.db.list_sessions()
        if sessions:
            s = sessions[0]
            self.current_session = s["id"]
            self.session_name = s["name"]
        else:
            self.create_new_session("default")

    def create_new_session(self, name: str) -> str:
        """Create a new chat session (no Band chatroom needed)."""
        session_id = f"s-{datetime.now():%Y%m%d-%H%M%S}"
        self.db.create_session(session_id, name, "")
        self.current_session = session_id
        self.session_name = name
        return session_id

    # ── Display ──────────────────────────────────────────────────

    def print_header(self):
        self.console.print()
        self.console.print(Align.center(
            Text("🚀 Supaband TUI — Supa Chat Interface", style=COLOR_HEAD)
        ))
        self.console.print(Rule(style="dim"))
        self.print_status_line()
        self.console.print()

    def print_status_line(self):
        msg_count = 0
        if self.current_session:
            msg_count = self.db.get_message_count(self.current_session)

        parts = [
            f"[bold]Session:[/bold] {self.session_name}",
            f"[bold]Messages:[/bold] {msg_count}",
        ]

        # Quick fleet status
        status = fleet.list_agent_status()
        online = [n for n, i in status.items() if i["running"]]
        parts.append(f"[bold]Online:[/bold] {', '.join(online) if online else 'none'}")

        self.console.print("  " + "  |  ".join(parts), style=COLOR_SYS)

    def print_user_message(self, content: str):
        ts = datetime.now().strftime("%H:%M:%S")
        panel = Panel(
            Text(content, style=COLOR_USER),
            title=f"[{COLOR_USER}]You[/{COLOR_USER}] {ts}",
            title_align="left",
            border_style=COLOR_USER,
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_supa_message(self, content: str):
        ts = datetime.now().strftime("%H:%M:%S")
        clean = re.sub(r'^@\[\[[0-9a-f-]+\]\]\s*', '', content)
        try:
            body = Markdown(clean)
        except Exception:
            body = Text(clean, style=COLOR_SUPA)

        panel = Panel(
            body,
            title=f"[{COLOR_SUPA}]Supa[/{COLOR_SUPA}] {ts}",
            title_align="left",
            border_style=COLOR_SUPA,
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_system(self, text: str, style: str = COLOR_SYS):
        self.console.print(text, style=style)

    def print_command_output(self, text: str):
        if text:
            self.console.print(Panel(
                Text(text, style=COLOR_CMD),
                border_style="dim",
                padding=(0, 1),
                title="[dim]output[/dim]",
                title_align="left",
            ))

    def print_error(self, text: str):
        self.console.print(f"[{COLOR_ERR}]✗ {text}[/{COLOR_ERR}]")

    # ── Command Handling ─────────────────────────────────────────

    def handle_command(self, raw: str) -> bool:
        parts = raw[1:].split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler = COMMANDS.get(cmd)
        if not handler:
            self.print_error(f"Unknown command: /{cmd}. Type /help for commands.")
            return True

        try:
            result = handler(self, args)
            if self._clear_screen:
                self._clear_screen = False
                os.system("clear" if os.name == "posix" else "cls")
                self.print_header()
            elif result:
                self.print_command_output(result)
        except Exception as e:
            self.print_error(f"Command failed: {e}")

        return True

    # ── Message Sending ──────────────────────────────────────────

    def send_message(self, content: str):
        """Send a user message to Supa via direct HTTP and display response."""
        if not self.current_session:
            self.print_error("No active session. Use /new to create one.")
            return

        # Check Supa is running
        if not supa_is_running():
            self.print_error("Supa is not running. Use /awake supa to start it.")
            return

        # Store user message in DB
        self.db.add_message(self.current_session, "user", content)
        self.print_user_message(content)

        # Get context from previous messages
        context = self.db.get_context(self.current_session, max_messages=CONTEXT_MSGS)

        # Send directly to Supa's HTTP endpoint
        self.console.print(f"[{COLOR_SYS}]⏳ Waiting for Supa...[/{COLOR_SYS}]", end="")

        result = send_to_supa(
            message=content,
            context=context,
            session_id=self.current_session or "direct",
        )

        # Clear waiting indicator
        self.console.file.write("\r\033[K")
        self.console.file.flush()

        if result is None:
            self.print_error("No response from Supa (network error). Is Supa running?")
            return

        if result.get("status") == "error":
            self.print_error(f"Supa error: {result.get('error', 'unknown')}")
            return

        response = result.get("response", "")
        if not response:
            response = "(empty response)"

        # Store in DB and display
        self.db.add_message(self.current_session, "supa", response)
        self.print_supa_message(response)

    # ── Main Loop ────────────────────────────────────────────────

    def run(self):
        """Main TUI loop."""
        # Auto-start Supa
        if not self.init_supa():
            self.print_error("Cannot start without Supa. Check agent_config.yaml and .env.")
            return

        # Init default session (skip if already done via CLI args)
        if not self.current_session:
            self.init_default_session()

        # Print header
        self.print_header()
        self.print_system("Type /help for commands, or just start chatting with Supa.")
        self.console.print()

        while self._running:
            try:
                user_input = Prompt.ask(
                    f"[{COLOR_USER}]>[/{COLOR_USER}]",
                    console=self.console,
                    show_default=False,
                )

                if not user_input.strip():
                    continue

                if self._clear_screen:
                    self._clear_screen = False
                    os.system("clear" if os.name == "posix" else "cls")
                    self.print_header()
                    continue

                # Handle slash commands
                if user_input.startswith("/"):
                    self.handle_command(user_input)
                    self.console.print()
                    continue

                # Regular message
                self.send_message(user_input)
                self.console.print()

            except KeyboardInterrupt:
                self.console.print()
                self.print_system("Press /quit to exit, or Ctrl+C again to force quit.")
                try:
                    time.sleep(1)
                except KeyboardInterrupt:
                    break
            except EOFError:
                break
            except Exception as e:
                self.print_error(f"Unexpected error: {e}")

        self.print_system("Supaband TUI closed.")
