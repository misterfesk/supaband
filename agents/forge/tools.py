"""Forge-specific tools: file management, cross-department coordination.

Forge is the Operations Manager. He oversees business operations, resource
allocation, process optimization, and cross-department coordination.
He has file tools and blackboard access but cannot spawn workers directly
(he requests workers from Supa via Band messaging).
"""

from __future__ import annotations

from pathlib import Path
from langchain_core.tools import tool
from core.config import PROJECT_ROOT


@tool
def file_read(path: str) -> str:
    """Read a file within supaband/. Use to review operational documents, reports, or configs.

    Args:
        path: Relative path from supaband/
    """
    full = (PROJECT_ROOT / path).resolve()
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
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
    """Write a file within supaband/. Use to create operational reports, process docs, or tracking sheets.

    Args:
        path: Relative path from supaband/
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


@tool
def file_list(dir_path: str = "") -> str:
    """List files in a directory within supaband/."""
    full = (PROJECT_ROOT / dir_path).resolve() if dir_path else PROJECT_ROOT
    try:
        full.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return f"❌ Access denied — path outside supaband/."
    if not full.is_dir():
        return f"❌ Not a directory: {dir_path}"
    entries = sorted(full.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    lines = [f"📂 {dir_path or 'supaband/'}"]
    for e in entries[:50]:
        kind = "📁" if e.is_dir() else "📄"
        lines.append(f"  {kind} {e.name}")
    if len(entries) > 50:
        lines.append(f"  ... ({len(entries) - 50} more)")
    return "\n".join(lines)


FORGE_TOOLS = [
    file_read, file_write, file_list,
]
