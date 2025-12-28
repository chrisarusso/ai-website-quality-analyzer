#!/bin/bash
# Run fix flow tests on EC2 with full logging
# Uses existing scan 7dc37550 - does NOT run a new scan
# All output saved to timestamped log file for review

set -e

cd /home/ubuntu/website-quality-agent

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="test_run_${TIMESTAMP}.log"
RESULTS_DIR="test_results"

mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR/screenshots"

# Redirect all output to log file AND stdout
exec > >(tee -a "$RESULTS_DIR/$LOG_FILE") 2>&1

echo "=========================================="
echo "FIX FLOW TEST RUNNER"
echo "Started: $(date)"
echo "Log file: $RESULTS_DIR/$LOG_FILE"
echo "Using scan: 7dc37550"
echo "=========================================="

# Step 1: Pull latest code
echo ""
echo "[1/5] Pulling latest code from GitHub..."
git fetch origin 2>/dev/null || git fetch github 2>/dev/null || echo "Git fetch skipped"
git reset --hard origin/master 2>/dev/null || git reset --hard github/master 2>/dev/null || echo "Using current code"
echo "Code version: $(git rev-parse --short HEAD)"

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

# Step 4: Verify terminus auth (needed for Drupal fixes)
echo ""
echo "[4/5] Verifying terminus authentication..."
TERMINUS_USER=$(terminus auth:whoami 2>&1 || echo "NOT LOGGED IN")
echo "Terminus user: $TERMINUS_USER"
if [[ "$TERMINUS_USER" == "NOT LOGGED IN" ]]; then
    echo "WARNING: Terminus not authenticated. Drupal content fixes may fail."
fi

# Step 5: Verify scan exists before running tests
echo ""
echo "[5/5] Verifying scan 7dc37550 exists..."
SCAN_CHECK=$(curl -s http://localhost:8003/api/scan/7dc37550)
if echo "$SCAN_CHECK" | grep -q '"status":"completed"'; then
    echo "Scan found and completed"
    echo "Scan details: $SCAN_CHECK"
else
    echo "ERROR: Scan 7dc37550 not found or not completed!"
    echo "Response: $SCAN_CHECK"
    exit 1
fi

# Run tests
echo ""
echo "=========================================="
echo "RUNNING FIX FLOW TESTS"
echo "=========================================="
echo ""

# Set environment variables
export SCAN_ID="7dc37550"
export API_BASE="http://localhost:8003"

python scripts/run_fix_tests.py 2>&1

# Copy any generated result files to results dir
mv fix_test_*.json "$RESULTS_DIR/" 2>/dev/null || true
mv fix_test_*.log "$RESULTS_DIR/" 2>/dev/null || true

echo ""
echo "=========================================="
echo "Test run complete: $(date)"
echo "=========================================="

# Show result files
echo ""
echo "Result files in $RESULTS_DIR/:"
ls -la "$RESULTS_DIR/"

echo ""
echo "Screenshots in $RESULTS_DIR/screenshots/:"
ls -la "$RESULTS_DIR/screenshots/" 2>/dev/null || echo "(none)"

echo ""
echo "To view full log: cat ~/website-quality-agent/$RESULTS_DIR/$LOG_FILE"
echo "To view JSON results: cat ~/website-quality-agent/$RESULTS_DIR/fix_test_results_*.json"
