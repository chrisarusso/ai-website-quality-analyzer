#!/usr/bin/env bash
set -euo pipefail

# Simple, repeatable starter for the Website Quality Agent dashboard.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

# Ensure dependencies are present (editable install for local dev).
pip install -e .

PORT="${PORT:-8001}"
HOST="${HOST:-127.0.0.1}"

echo "Starting dashboard on http://${HOST}:${PORT}"
uvicorn website_agent.api.app:create_app --factory --reload --host "$HOST" --port "$PORT"

