#!/bin/bash
# Run website scan on a remote server
#
# Setup once on remote server:
#   1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
#   2. Install playwright: uv run playwright install chromium
#
# Usage:
#   ./run-remote.sh                    # Uses settings from .env
#   ./run-remote.sh https://other.com  # Override URL
#
# The script will:
#   1. Sync code to remote server
#   2. Run the scan in background (survives disconnect)
#   3. Show you how to check progress and download results

set -e
cd "$(dirname "$0")"

# Load config from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Allow URL override from command line
URL="${1:-$SCAN_URL}"
MAX_PAGES="${SCAN_MAX_PAGES:-9999}"

# Validate required settings
if [ -z "$REMOTE_HOST" ] || [ "$REMOTE_HOST" = "your-server.com" ]; then
    echo "Error: Set REMOTE_HOST in .env file"
    echo "Example: REMOTE_HOST=myserver.com"
    exit 1
fi

REMOTE="${REMOTE_USER:-$USER}@${REMOTE_HOST}"
REMOTE_DIR="${REMOTE_DIR:-/home/$USER/website-quality-agent}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "========================================"
echo "Remote Website Quality Scanner"
echo "========================================"
echo "Remote server: $REMOTE"
echo "Remote dir:    $REMOTE_DIR"
echo "Scan URL:      $URL"
echo "Max pages:     $MAX_PAGES"
echo "========================================"
echo ""

# Step 1: Sync code to remote
echo "[1/3] Syncing code to remote server..."
rsync -avz --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude '*.log' \
    ./ "${REMOTE}:${REMOTE_DIR}/"
echo "Done."
echo ""

# Step 2: Create remote scan script
echo "[2/3] Preparing remote scan..."
SCAN_SCRIPT="scan-${TIMESTAMP}.sh"
cat > "/tmp/${SCAN_SCRIPT}" << REMOTE_SCRIPT
#!/bin/bash
cd "${REMOTE_DIR}"

# Ensure uv is in PATH
export PATH="\$HOME/.local/bin:\$PATH"

# Install dependencies
uv sync 2>&1 | tail -5

# Install browser if needed
uv run playwright install chromium 2>&1 | tail -3

# Run the scan
echo ""
echo "Starting scan at: \$(date)"
echo "URL: ${URL}"
echo "Max pages: ${MAX_PAGES}"
echo ""

uv run website-agent scan "${URL}" --max-pages ${MAX_PAGES} 2>&1 | tee "scan-${TIMESTAMP}.log"

echo ""
echo "Scan completed at: \$(date)"
echo "Log saved to: ${REMOTE_DIR}/scan-${TIMESTAMP}.log"
REMOTE_SCRIPT

# Copy and execute
scp "/tmp/${SCAN_SCRIPT}" "${REMOTE}:${REMOTE_DIR}/${SCAN_SCRIPT}"
rm "/tmp/${SCAN_SCRIPT}"

# Step 3: Run scan in background on remote
echo "[3/3] Starting scan on remote server..."
ssh "${REMOTE}" "cd ${REMOTE_DIR} && chmod +x ${SCAN_SCRIPT} && nohup ./${SCAN_SCRIPT} > nohup-${TIMESTAMP}.out 2>&1 &"
echo "Done."
echo ""

echo "========================================"
echo "Scan is running on remote server!"
echo "========================================"
echo ""
echo "Check progress:"
echo "  ssh ${REMOTE} 'tail -f ${REMOTE_DIR}/scan-${TIMESTAMP}.log'"
echo ""
echo "Download results when done:"
echo "  scp ${REMOTE}:${REMOTE_DIR}/scan-${TIMESTAMP}.log ."
echo "  scp -r ${REMOTE}:${REMOTE_DIR}/data ./data-remote"
echo ""
echo "View report (after downloading data):"
echo "  ./start.sh"
echo "  open http://localhost:8002/api/scans"
echo ""
