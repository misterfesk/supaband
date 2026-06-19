#!/usr/bin/env bash
# Supaband Setup — One-command environment prep.
#
# This is a thin wrapper around setup.py — it just ensures Python 3.11+
# and runs the Python setup script (which handles venv, deps, Band registration,
# and config generation).
#
# Usage:
#   ./setup.sh                          Interactive mode
#   ./setup.sh --skip-registration      Skip Band agent registration
#   ./setup.sh --non-interactive ...    CI/scripted mode

set -e
cd "$(dirname "$0")"

echo "🦐 Supaband Setup"
echo "==============="

PYTHON=$(command -v python3.11 || command -v python3 || echo "")
if [ -z "$PYTHON" ]; then
    echo "❌ python3 not found. Install Python 3.11+."
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || echo "(0, 0)")
echo "   Python: $PYTHON ($PY_VER)"
echo ""

exec "$PYTHON" setup.py "$@"
