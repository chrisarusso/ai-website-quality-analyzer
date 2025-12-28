#!/bin/bash
# Run fix flow tests on EC2
# This script:
# 1. Starts the API server
# 2. Runs the comprehensive fix tests
# 3. Logs everything to a file

set -e

cd /home/ubuntu/website-quality-agent

LOG_FILE="test_run_$(date +%Y%m%d_%H%M%S).log"

echo "=========================================="
echo "Fix Flow Test Runner"
echo "Started: $(date)"
echo "Log file: $LOG_FILE"
echo "=========================================="

# Ensure we have latest code
echo "[1/4] Pulling latest code..."
git fetch github
git reset --hard github/master

# Install dependencies
echo "[2/4] Installing dependencies..."
source .venv/bin/activate
pip install -q -r requirements.txt 2>/dev/null || pip install -q -e . 2>/dev/null || true

# Start API server in background
echo "[3/4] Starting API server..."
pkill -f "uvicorn.*website_agent" 2>/dev/null || true
sleep 2

# Start server
nohup python -m uvicorn src.website_agent.api.app:app --host 0.0.0.0 --port 8003 > api_server.log 2>&1 &
API_PID=$!
echo "API server started with PID $API_PID"

# Wait for server to be ready
echo "Waiting for API to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8003/ > /dev/null 2>&1; then
        echo "API is ready"
        break
    fi
    sleep 1
done

# Run tests
echo "[4/4] Running fix flow tests..."
echo ""
python scripts/run_fix_tests.py 2>&1 | tee -a "$LOG_FILE"

echo ""
echo "=========================================="
echo "Test run complete: $(date)"
echo "Results in: $LOG_FILE"
echo "=========================================="
