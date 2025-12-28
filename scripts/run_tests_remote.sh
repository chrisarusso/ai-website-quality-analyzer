#!/bin/bash
# Run fix flow tests on EC2 with full logging
# All output saved to timestamped log file for later review

set -e

cd /home/ubuntu/website-quality-agent

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="test_run_${TIMESTAMP}.log"
RESULTS_DIR="test_results"

mkdir -p "$RESULTS_DIR"

# Redirect all output to log file AND stdout
exec > >(tee -a "$RESULTS_DIR/$LOG_FILE") 2>&1

echo "=========================================="
echo "FIX FLOW TEST RUNNER"
echo "Started: $(date)"
echo "Log file: $RESULTS_DIR/$LOG_FILE"
echo "=========================================="

# Step 1: Pull latest code
echo ""
echo "[1/5] Pulling latest code from GitHub..."
git fetch origin
git reset --hard origin/master
echo "Code updated to: $(git rev-parse --short HEAD)"

# Step 2: Activate virtualenv
echo ""
echo "[2/5] Activating virtual environment..."
source .venv/bin/activate

# Step 3: Check/start API server
echo ""
echo "[3/5] Checking API server..."
if curl -s http://localhost:8003/ > /dev/null 2>&1; then
    echo "API server already running on port 8003"
else
    echo "Starting API server..."
    pkill -f "uvicorn.*website_agent" 2>/dev/null || true
    sleep 2
    nohup python -m uvicorn src.website_agent.api.app:app --host 0.0.0.0 --port 8003 > api_server.log 2>&1 &
    echo "Waiting for API to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8003/ > /dev/null 2>&1; then
            echo "API is ready"
            break
        fi
        sleep 1
    done
fi

# Step 4: Verify terminus auth
echo ""
echo "[4/5] Verifying terminus authentication..."
TERMINUS_USER=$(terminus auth:whoami 2>&1 || echo "NOT LOGGED IN")
echo "Terminus user: $TERMINUS_USER"
if [[ "$TERMINUS_USER" == "NOT LOGGED IN" ]]; then
    echo "ERROR: Terminus not authenticated. Cannot run Drupal content fixes."
    exit 1
fi

# Step 5: Run tests
echo ""
echo "[5/5] Running fix flow tests..."
echo ""
python scripts/run_fix_tests.py 2>&1

# Copy any generated result files to results dir
mv fix_test_*.json "$RESULTS_DIR/" 2>/dev/null || true
mv fix_test_*.log "$RESULTS_DIR/" 2>/dev/null || true

echo ""
echo "=========================================="
echo "Test run complete: $(date)"
echo "Results saved to: $RESULTS_DIR/"
echo "Log file: $RESULTS_DIR/$LOG_FILE"
echo "=========================================="

# List result files
echo ""
echo "Result files:"
ls -la "$RESULTS_DIR/"
