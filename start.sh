#!/bin/bash
# Start the Website Quality Agent web app
# Usage: ./start.sh

cd "$(dirname "$0")"

echo "Starting Website Quality Agent..."
echo "API will be available at: http://localhost:8002"
echo "API docs at: http://localhost:8002/docs"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uv run website-agent serve
