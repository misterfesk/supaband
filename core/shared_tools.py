"""Shared tools — blackboard file sharing + common utilities for all agents.

These tools are available to every agent (Supa, Koe, managers, workers).
They provide cross-department file sharing via the blackboard system.
"""

from __future__ import annotations

from langchain_core.tools import tool
from core.blackboard import get_blackboard
from core.config import PROJECT_ROOT


def make_blackboard_tools(agent_name: str) -> list:
    """Create blackboard tools scoped to the calling agent's name."""

    @tool
    def bb_post(key: str, title: str, department: str, content: str, tags: str = "") -> str:
        """Post a document to the shared blackboard for other agents to read.

        Use this to share reports, briefs, analysis, or any document that other
        departments need. Other agents can retrieve it by key.

        Args:
            key: Unique document key (slug format, e.g. "q3-campaign-brief")
            title: Human-readable title
            department: Your department (e.g. "marketing", "research", "operations")
            content: Full document content (markdown supported)
            tags: Optional comma-separated tags for searchability
        """
        bb = get_blackboard()
        result = bb.post(key=key, title=title, department=department,
                         author=agent_name, content=content, tags=tags)
        if result["ok"]:
            return f"✅ Posted to blackboard: '{title}' (key={key}, dept={department})"
        return f"❌ Post failed: {result.get('error')}"

    @tool
    def bb_retrieve(key: str) -> str:
        """Retrieve a document from the shared blackboard by key.

        Args:
            key: Document key (e.g. "q3-campaign-brief")
        """
        bb = get_blackboard()
        result = bb.retrieve(key=key)
        if not result["ok"]:
            return f"❌ {result.get('error')}"
        doc = result["doc"]
        content = doc.get("content", "")
        if len(content) > 6000:
            content = content[:6000] + f"\n... ({len(content) - 6000} more chars)"
        return (f"📄 {doc['title']} (key={doc['key']}, dept={doc['department']}, "
                f"author={doc['author']}, updated={doc.get('updated_at', '?')[:19]})\n\n{content}")

    @tool
    def bb_list(department: str = "") -> str:
        """List documents on the blackboard, optionally filtered by department.

        Args:
            department: Optional department filter (e.g. "marketing", "research")
        """
        bb = get_blackboard()
        docs = bb.list_all(department=department)
        if not docs:
            return "No documents on the blackboard" + (f" for '{department}'" if department else "")
        lines = [f"📋 Blackboard ({len(docs)} docs" + (f", dept={department}" if department else "") + "):"]
        for d in docs:
            pin = "📌 " if d.get("is_pinned") else "  "
            tags = f" [{d['tags']}]" if d.get("tags") else ""
            lines.append(f"{pin}{d['key']:30s} — {d['title']} ({d['department']}){tags}")
        return "\n".join(lines)

    @tool
    def bb_search(query: str) -> str:
        """Search the blackboard for documents matching a query.

        Args:
            query: Search terms (e.g. "coffee market", "campaign Q3")
        """
        bb = get_blackboard()
        results = bb.search(query=query)
        if not results:
            return f"No documents found matching '{query}'"
        lines = [f"🔍 Search results for '{query}' ({len(results)}):"]
        for r in results:
            excerpt = r.get("excerpt", "")[:100]
            lines.append(f"  {r['key']:30s} — {r['title']} ({r['department']})")
            if excerpt:
                lines.append(f"    {excerpt}")
        return "\n".join(lines)

    @tool
    def bb_pin(key: str) -> str:
        """Pin a blackboard document so it appears at the top of lists.

        Args:
            key: Document key to pin
        """
        bb = get_blackboard()
        result = bb.pin(key=key)
        return f"✅ Pinned: {key}" if result["ok"] else f"❌ {result.get('error')}"

    @tool
    def bb_delete(key: str) -> str:
        """Delete a document from the blackboard.

        Args:
            key: Document key to delete
        """
        bb = get_blackboard()
        result = bb.delete(key=key)
        return f"✅ Deleted: {key}" if result["ok"] else f"❌ {result.get('error')}"

    return [bb_post, bb_retrieve, bb_list, bb_search, bb_pin, bb_delete]


# ── Web Scraping Tool (shared) ───────────────────────────────────────

def make_web_tools() -> list:
    """Create web scraping tool available to any agent that needs it."""

    @tool
    def web_scrape(url: str) -> str:
        """Scrape a web page and return its content as clean text.
        Use for research, keyword analysis, or reading online articles.

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
            }
            import re
            with httpx.Client(follow_redirects=True, timeout=20.0, headers=headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text

            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()

            for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                level = int(h.name[1])
                h.replace_with(f"\n\n{'#' * level} {h.get_text(strip=True)}\n")

            for p in soup.find_all("p"):
                p.insert_after("\n\n")
            for li in soup.find_all("li"):
                li.insert_before("• ")

            text = soup.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r"[ \t]{2,}", " ", text).strip()

            if not text or len(text) < 50:
                return f"❌ Page appears empty or requires JavaScript. URL: {url}"
            if len(text) > 8000:
                text = text[:8000] + f"\n\n... (truncated, {len(text)} total chars)"
            return f"📄 Scraped {url}:\n\n{text}"
        except Exception as e:
            return f"❌ Scrape failed: {e}"

    return [web_scrape]


# ── File Tools (shared) ──────────────────────────────────────────────

def make_file_tools() -> list:
    """Create file read/write tools available to any agent."""

    @tool
    def file_read(path: str) -> str:
        """Read a file within supaband/. Use to review documents, research, or configs.

        Args:
            path: Relative path from supaband/
        """
        full = (PROJECT_ROOT / path).resolve()
        try:
            full.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return "❌ Access denied — path outside supaband/."
        if not full.exists():
            return f"❌ File not found: {path}"
        try:
            content = full.read_text()
            preview = content[:4000]
            suffix = f"\n... ({len(content) - 4000} more chars)" if len(content) > 4000 else ""
            return f"📄 {path} ({len(content)} chars):\n\n{preview}{suffix}"
        except Exception as e:
            return f"❌ Read failed: {e}"

    @tool
    def file_write(path: str, content: str) -> str:
        """Write a file within supaband/. Use to save drafts, reports, or data.

        Args:
            path: Relative path from supaband/
            content: Full file content
        """
        full = (PROJECT_ROOT / path).resolve()
        try:
            full.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return "❌ Access denied — path outside supaband/."
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
            return f"✅ Written {len(content)} chars → {path}"
        except Exception as e:
            return f"❌ Write failed: {e}"

    return [file_read, file_write]
