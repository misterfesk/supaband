#!/usr/bin/env python3
"""Blackboard administration — list, search, and manage shared documents.

Usage:
    python3 scripts/bb_admin.py                    # list all
    python3 scripts/bb_admin.py list marketing      # list by department
    python3 scripts/bb_admin.py search "coffee"     # search
    python3 scripts/bb_admin.py get "doc-key"       # retrieve
    python3 scripts/bb_admin.py pin "doc-key"       # pin
    python3 scripts/bb_admin.py delete "doc-key"    # delete
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.blackboard import get_blackboard

def main():
    bb = get_blackboard()
    args = sys.argv[1:]

    if not args:
        cmd = "list"
        cmd_args = []
    else:
        cmd = args[0]
        cmd_args = args[1:]

    if cmd == "list":
        dept = cmd_args[0] if cmd_args else ""
        docs = bb.list_all(department=dept)
        if not docs:
            print(f"No documents{f' in {dept}' if dept else ''}")
            return
        print(f"📋 {len(docs)} documents{f' in {dept}' if dept else ''}:")
        for d in docs:
            pin = "📌 " if d.get("is_pinned") else "  "
            tags = f" [{d['tags']}]" if d.get("tags") else ""
            print(f"  {pin}{d['key']:30s} — {d['title']} ({d['department']}){tags}")

    elif cmd == "search":
        if not cmd_args:
            print("Usage: bb_admin.py search <query>")
            return
        results = bb.search(" ".join(cmd_args))
        if not results:
            print("No results")
            return
        print(f"🔍 {len(results)} results:")
        for r in results:
            print(f"  {r['key']:30s} — {r['title']} ({r['department']})")
            if r.get("excerpt"):
                print(f"    {r['excerpt'][:100]}")

    elif cmd == "get":
        if not cmd_args:
            print("Usage: bb_admin.py get <key>")
            return
        result = bb.retrieve(cmd_args[0])
        if not result["ok"]:
            print(f"❌ {result['error']}")
            return
        doc = result["doc"]
        print(f"📄 {doc['title']}")
        print(f"   Key: {doc['key']}")
        print(f"   Department: {doc['department']}")
        print(f"   Author: {doc['author']}")
        print(f"   Updated: {doc.get('updated_at', '?')[:19]}")
        print(f"\n{doc.get('content', '')}")

    elif cmd == "pin":
        if not cmd_args:
            print("Usage: bb_admin.py pin <key>")
            return
        result = bb.pin(cmd_args[0])
        print(f"✅ Pinned: {cmd_args[0]}" if result["ok"] else f"❌ {result.get('error')}")

    elif cmd == "delete":
        if not cmd_args:
            print("Usage: bb_admin.py delete <key>")
            return
        result = bb.delete(cmd_args[0])
        print(f"✅ Deleted: {cmd_args[0]}" if result["ok"] else f"❌ {result.get('error')}")

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: list, search, get, pin, delete")

if __name__ == "__main__":
    main()
