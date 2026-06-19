"""Koe-specific tools: research data management, web scraping, blob control, file analysis."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from core.config import PROJECT_ROOT, load_agent_config, get_agent_entry
from core import fleet

KOE_DATA = PROJECT_ROOT / "agents" / "koe" / "data"
KOE_RESEARCH = KOE_DATA / "research"
KOE_EXPORTS = KOE_DATA / "exports"
KOE_RESEARCH.mkdir(parents=True, exist_ok=True)
KOE_EXPORTS.mkdir(parents=True, exist_ok=True)


# ── File Tools ───────────────────────────────────────────────────────

@tool
def file_read(path: str) -> str:
    """Read a file within supaband/. Use to review research data or agent configs.

    Args:
        path: Relative path from supaband/ (e.g. "agents/koe/data/research/report.md")
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    if not full.exists():
        return f"❌ Not found: {path}"
    try:
        content = full.read_text()
        preview = content[:4000]
        suffix = f"\n... ({len(content) - 4000} more chars)" if len(content) > 4000 else ""
        return f"📄 {path} ({len(content)} chars):\n\n{preview}{suffix}"
    except Exception as e:
        return f"❌ Read failed: {e}"


@tool
def file_write(path: str, content: str) -> str:
    """Write a file within supaband/. Use to save research reports, data, findings.

    Args:
        path: Relative path (e.g. "agents/koe/data/research/coffee_market.md")
        content: Full file content
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return f"✅ Written {len(content)} chars → {path}"
    except Exception as e:
        return f"❌ Write failed: {e}"


# ── Research Data Management ─────────────────────────────────────────

@tool
def research_save(subject: str, content: str) -> str:
    """Save research data to Koe's data folder with auto-naming.

    Args:
        subject: Short subject slug (e.g. "coffee-market-portland")
        content: Full research content (markdown format preferred)
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{subject}.md"
    filepath = KOE_RESEARCH / filename
    try:
        header = f"# {subject}\nSaved: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
        filepath.write_text(header + content)
        return f"✅ Research saved → agents/koe/data/research/{filename}"
    except Exception as e:
        return f"❌ Save failed: {e}"


@tool
def research_list() -> str:
    """List all saved research files in Koe's data folder."""
    try:
        entries = sorted(KOE_RESEARCH.iterdir(),
                        key=lambda x: x.stat().st_mtime, reverse=True)
        if not entries:
            return "No research files saved yet."
        lines = [f"📚 Koe's Research ({len(entries)} files):"]
        for e in entries[:20]:
            size = e.stat().st_size
            ts = datetime.fromtimestamp(e.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  📄 {e.name} — {size}B — {ts}")
        if len(entries) > 20:
            lines.append(f"  ... ({len(entries) - 20} more)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ List failed: {e}"


# ── Web Scraping ─────────────────────────────────────────────────────

@tool
def web_scrape(url: str) -> str:
    """Scrape a web page and return its content as clean text.

    Use this when a user provides a URL for research, or when you need to
    read the content of a web page for analysis.

    Uses BeautifulSoup for robust HTML parsing — removes scripts, styles,
    navigation, and boilerplate. Returns up to 8000 chars of clean text.

    Args:
        url: Full URL to scrape (e.g. "https://example.com/article")
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError:
        return "❌ httpx/bs4 not available — cannot scrape."

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        # Parse with BeautifulSoup for robust extraction
        # Try lxml first (faster), fall back to built-in html.parser
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        # Convert headings to markdown-style (replace element with text)
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            level = int(h.name[1])
            h.replace_with(f"\n\n{'#' * level} {h.get_text(strip=True)}\n")

        # Convert paragraphs and list items to lines
        for p in soup.find_all("p"):
            p.insert_after("\n\n")
        for li in soup.find_all("li"):
            li.insert_before("• ")

        # Extract links
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = str(a["href"])
            if text and href.startswith("http"):
                a.replace_with(f"{text} ({href})")

        # Get clean text
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()

        if not text or len(text) < 50:
            return f"❌ Page appears empty or requires JavaScript rendering. URL: {url}"

        if len(text) > 8000:
            text = text[:8000] + f"\n\n... (truncated, {len(text)} total chars)"
        return f"📄 Scraped {url}:\n\n{text}"
    except Exception as e:
        return f"❌ Scrape failed: {e}"


# ── Blob Agent Lifecycle Tools ───────────────────────────────────────

BLOB_AGENTS = ["blobw1", "blobw2", "blobw3"]
_BLOB_PIDS: dict[str, int] = {}


@tool
def blob_awake(agent_name: str) -> str:
    """Start a single blob worker agent.

    Use this to start specific blob workers individually rather than all at once.

    Args:
        agent_name: One of "blobw1", "blobw2", "blobw3"
    """
    name = agent_name.lower().strip()
    if name not in BLOB_AGENTS:
        return f"❌ Unknown blob agent. Valid: {', '.join(BLOB_AGENTS)}"

    result = fleet.launch_agent(name)
    if not result["ok"]:
        return f"❌ {name}: {result.get('error', 'launch failed')}"
    if result.get("started"):
        _BLOB_PIDS[name] = result.get("pid", 0)
        return f"✅ {name} started — PID {result['pid']}"
    return f"ℹ️ {name} already running — PID {result['pid']}"


@tool
def blob_kill(agent_name: str) -> str:
    """Stop a single blob worker agent.

    Args:
        agent_name: One of "blobw1", "blobw2", "blobw3", or "all" to stop all
    """
    name = agent_name.lower().strip()
    if name == "all":
        results = []
        for bname in BLOB_AGENTS:
            r = fleet.kill_agent(bname)
            results.append(f"{bname}: {'stopped' if r['ok'] else r.get('error', 'failed')}")
            _BLOB_PIDS.pop(bname, None)
        return "\n".join(results)
    if name not in BLOB_AGENTS:
        return f"❌ Unknown blob agent. Valid: {', '.join(BLOB_AGENTS)}"

    result = fleet.kill_agent(name)
    _BLOB_PIDS.pop(name, None)
    if not result["ok"]:
        return f"❌ {name}: {result.get('error', 'kill failed')}"
    return f"✅ {name} stopped"


@tool
def worker_kill(process_name: str) -> str:
    """Kill a worker process by name pattern. Use for stuck or unresponsive workers.
    Does NOT kill core agents (supa, koe, mave, forge).

    Args:
        process_name: Process name to kill (matches partial, e.g. "dev_manager")
    """
    protected = {"supa", "koe", "mave", "forge"}
    if process_name.lower().strip() in protected:
        return f"❌ Cannot kill core agent '{process_name}' — protected."

    try:
        result = subprocess.run(
            ["pkill", "-f", process_name],
            capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return f"✅ Killed processes matching '{process_name}'."
        return f"⚠️ No process matching '{process_name}' found."
    except Exception as e:
        return f"❌ Kill failed: {e}"


# ── Export & Analysis Tools ──────────────────────────────────────────

@tool
def export_to_topic(topic: str, chat_id: str) -> str:
    """Export a Band chatroom conversation to a file named after the topic.

    The file is saved to agents/koe/data/exports/<topic-slug>.md
    Use this after blob discussions to save the transcript for analysis.

    Args:
        topic: Topic name for the file (e.g. "coffee-market-test")
        chat_id: Band chatroom UUID to export
    """
    try:
        config = load_agent_config()
        entry = get_agent_entry(config, "research_manager")
        from thenvoi_rest import RestClient
        client = RestClient(api_key=entry["api_key"], base_url="https://app.band.ai", timeout=30.0)

        resp = client.agent_api_messages.list_agent_messages(
            chat_id=chat_id, status="all", page_size=200)
        msgs = resp.data if hasattr(resp, "data") else []
        if not msgs:
            return f"❌ No messages found in chat {chat_id[:12]}..."

        # Create topic slug
        slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
        filepath = KOE_EXPORTS / f"{slug}.md"

        lines = [
            f"# Export: {topic}",
            f"Chat ID: {chat_id}",
            f"Exported: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"Messages: {len(msgs)}\n",
        ]
        for m in msgs:
            sender = m.sender_name or "unknown"
            content = m.content or "(empty)"
            # Strip mention prefixes for readability
            content = re.sub(r'^@\[\[[0-9a-f-]+\]\]\s*', '', content)
            ts = str(getattr(m, "inserted_at", "") or "")
            lines.append(f"**[{sender}]** ({ts[:19]})\n{content}\n")

        filepath.write_text("\n".join(lines))
        return f"✅ Exported {len(msgs)} messages → agents/koe/data/exports/{slug}.md"
    except Exception as e:
        return f"❌ Export failed: {e}"


@tool
def analyze_export(topic: str) -> str:
    """Read an exported conversation file and return its content for analysis.

    Use this after export_to_topic() to read the transcript and formulate
    your research verdict.

    Args:
        topic: Topic name used in export_to_topic (e.g. "coffee-market-test")
    """
    slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
    filepath = KOE_EXPORTS / f"{slug}.md"
    if not filepath.exists():
        # Try to find matching files
        matches = list(KOE_EXPORTS.glob(f"*{slug}*")) + list(KOE_EXPORTS.glob(f"*{topic.lower()}*"))
        if matches:
            filepath = matches[0]
        else:
            return f"❌ No export found for '{topic}'. Use export_to_topic() first."

    content = filepath.read_text()
    preview = content[:6000]
    suffix = f"\n\n... ({len(content) - 6000} more chars)" if len(content) > 6000 else ""
    return f"📄 {filepath.name} ({len(content)} chars):\n\n{preview}{suffix}"


@tool
def verdict_save(topic: str, verdict: str, export_filename: str = "") -> str:
    """Save your research verdict for a topic alongside the export.

    Creates a verdict file in agents/koe/data/research/ with your analysis
    and conclusions. This is your final deliverable for a research task.

    Args:
        topic: Topic name (e.g. "coffee-market-portland")
        verdict: Your full analysis and conclusions (markdown format)
        export_filename: Optional export filename this verdict is based on
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
    filename = f"{ts}-verdict-{slug}.md"
    filepath = KOE_RESEARCH / filename
    try:
        header = (
            f"# Verdict: {topic}\n"
            f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        )
        if export_filename:
            header += f"Based on: {export_filename}\n"
        header += "\n"
        filepath.write_text(header + verdict)
        return f"✅ Verdict saved → agents/koe/data/research/{filename}"
    except Exception as e:
        return f"❌ Save failed: {e}"


# ── Blob Shadow Testing Tools ─────────────────────────────────────────

from agents.koe.blob_tools import BLOB_TOOLS  # noqa: E402


# ── Export ───────────────────────────────────────────────────────────

KOE_TOOLS = [
    file_read, file_write,
    research_save, research_list,
    web_scrape,
    blob_awake, blob_kill, worker_kill,
    export_to_topic, analyze_export, verdict_save,
    *BLOB_TOOLS,
]
