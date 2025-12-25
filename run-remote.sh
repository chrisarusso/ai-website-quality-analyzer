#!/bin/bash
# Run website scan on a remote server with Slack notifications
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
#   3. Send Slack notifications on start, completion, and failure
#   4. Show you how to check progress and download results

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
SSH_KEY="${REMOTE_SSH_KEY:-}"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL:-}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Build SSH options
SSH_OPTS=""
if [ -n "$SSH_KEY" ]; then
    SSH_KEY_EXPANDED="${SSH_KEY/#\~/$HOME}"
    SSH_OPTS="-i ${SSH_KEY_EXPANDED}"
fi

echo "========================================"
echo "Remote Website Quality Scanner"
echo "========================================"
echo "Remote server: $REMOTE"
echo "Remote dir:    $REMOTE_DIR"
echo "Scan URL:      $URL"
echo "Max pages:     $MAX_PAGES"
echo "Slack:         $([ -n "$SLACK_WEBHOOK" ] && echo "Enabled" || echo "Disabled")"
echo "========================================"
echo ""

# Step 1: Sync code to remote
echo "[1/3] Syncing code to remote server..."
if [ -n "$SSH_OPTS" ]; then
    rsync -avz -e "ssh ${SSH_OPTS}" --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
        --exclude '.pytest_cache' --exclude '*.log' --exclude 'report_*.html' \
        ./ "${REMOTE}:${REMOTE_DIR}/"
else
    rsync -avz --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
        --exclude '.pytest_cache' --exclude '*.log' --exclude 'report_*.html' \
        ./ "${REMOTE}:${REMOTE_DIR}/"
fi
echo "Done."
echo ""

# Step 2: Create remote scan script with Slack notifications
echo "[2/3] Preparing remote scan..."
SCAN_SCRIPT="scan-${TIMESTAMP}.sh"
cat > "/tmp/${SCAN_SCRIPT}" << 'REMOTE_SCRIPT_START'
#!/bin/bash
set -e

# Configuration injected by run-remote.sh
REMOTE_DIR="__REMOTE_DIR__"
URL="__URL__"
MAX_PAGES="__MAX_PAGES__"
SLACK_WEBHOOK="__SLACK_WEBHOOK__"
TIMESTAMP="__TIMESTAMP__"
REMOTE_HOST="__REMOTE_HOST__"

cd "${REMOTE_DIR}"

# Ensure uv is in PATH
export PATH="$HOME/.local/bin:$PATH"

# Slack notification function
send_slack() {
    local emoji="$1"
    local title="$2"
    local message="$3"
    local color="$4"

    if [ -z "$SLACK_WEBHOOK" ]; then
        echo "[Slack disabled] $title: $message"
        return 0
    fi

    # Build JSON payload
    local payload=$(cat <<EOF
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "${emoji} ${title}",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "${message}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Server: \`${REMOTE_HOST}\` | Timestamp: \`${TIMESTAMP}\`"
                }
            ]
        }
    ]
}
EOF
)

    curl -s -X POST -H 'Content-type: application/json' --data "$payload" "$SLACK_WEBHOOK" > /dev/null 2>&1 || true
}

# Error handler
handle_error() {
    local exit_code=$?
    local line_number=$1
    echo ""
    echo "ERROR: Script failed at line $line_number with exit code $exit_code"
    echo "Check log: ${REMOTE_DIR}/scan-${TIMESTAMP}.log"

    # Get last 10 lines of log for error context
    local error_context=""
    if [ -f "scan-${TIMESTAMP}.log" ]; then
        error_context=$(tail -10 "scan-${TIMESTAMP}.log" | head -c 500)
    fi

    send_slack "❌" "Website Scan FAILED" "*URL:* ${URL}\n*Error:* Script failed at line $line_number (exit code $exit_code)\n\n\`\`\`${error_context}\`\`\`" "danger"
    exit $exit_code
}

# Set up error trap
trap 'handle_error $LINENO' ERR

# Send start notification
send_slack "🚀" "Website Scan Started" "*URL:* ${URL}\n*Max Pages:* ${MAX_PAGES}\n*Started:* $(date '+%Y-%m-%d %H:%M:%S %Z')" "good"

# Install dependencies
echo "Installing dependencies..."
uv sync 2>&1 | tail -5

# Install browser if needed
echo "Checking Playwright browser..."
uv run playwright install chromium 2>&1 | tail -3

# Run the scan
echo ""
echo "=========================================="
echo "Starting scan at: $(date)"
echo "URL: ${URL}"
echo "Max pages: ${MAX_PAGES}"
echo "=========================================="
echo ""

START_TIME=$(date +%s)

# Run scan and capture output
uv run website-agent scan "${URL}" --max-pages ${MAX_PAGES} --output html 2>&1 | tee "scan-${TIMESTAMP}.log"
SCAN_EXIT_CODE=${PIPESTATUS[0]}

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
DURATION_MIN=$((DURATION / 60))
DURATION_SEC=$((DURATION % 60))

echo ""
echo "=========================================="
echo "Scan completed at: $(date)"
echo "Duration: ${DURATION_MIN}m ${DURATION_SEC}s"
echo "Log saved to: ${REMOTE_DIR}/scan-${TIMESTAMP}.log"
echo "=========================================="

# Extract results from log
PAGES_CRAWLED=$(grep -oP 'Crawled \K[0-9]+' "scan-${TIMESTAMP}.log" | tail -1 || echo "?")
TOTAL_ISSUES=$(grep -oP 'Total Issues: \K[0-9]+' "scan-${TIMESTAMP}.log" || echo "?")
OVERALL_SCORE=$(grep -oP 'Overall Score: \K[0-9.]+' "scan-${TIMESTAMP}.log" || echo "?")
REPORT_FILE=$(grep -oP 'HTML report saved to: \K\S+' "scan-${TIMESTAMP}.log" || echo "")

# Build results message
RESULTS_MSG="*URL:* ${URL}\n*Pages Crawled:* ${PAGES_CRAWLED}\n*Total Issues:* ${TOTAL_ISSUES}\n*Overall Score:* ${OVERALL_SCORE}/100\n*Duration:* ${DURATION_MIN}m ${DURATION_SEC}s"

if [ -n "$REPORT_FILE" ]; then
    RESULTS_MSG="${RESULTS_MSG}\n*Report:* \`${REPORT_FILE}\`"
fi

# Send completion notification
if [ $SCAN_EXIT_CODE -eq 0 ]; then
    send_slack "✅" "Website Scan Complete" "$RESULTS_MSG" "good"
else
    send_slack "⚠️" "Website Scan Completed with Warnings" "$RESULTS_MSG\n*Exit Code:* $SCAN_EXIT_CODE" "warning"
fi

echo ""
echo "Slack notification sent!"
REMOTE_SCRIPT_START

# Inject actual values into the script
sed -i '' "s|__REMOTE_DIR__|${REMOTE_DIR}|g" "/tmp/${SCAN_SCRIPT}"
sed -i '' "s|__URL__|${URL}|g" "/tmp/${SCAN_SCRIPT}"
sed -i '' "s|__MAX_PAGES__|${MAX_PAGES}|g" "/tmp/${SCAN_SCRIPT}"
sed -i '' "s|__SLACK_WEBHOOK__|${SLACK_WEBHOOK}|g" "/tmp/${SCAN_SCRIPT}"
sed -i '' "s|__TIMESTAMP__|${TIMESTAMP}|g" "/tmp/${SCAN_SCRIPT}"
sed -i '' "s|__REMOTE_HOST__|${REMOTE_HOST}|g" "/tmp/${SCAN_SCRIPT}"

# Copy script to remote
if [ -n "$SSH_OPTS" ]; then
    scp ${SSH_OPTS} "/tmp/${SCAN_SCRIPT}" "${REMOTE}:${REMOTE_DIR}/${SCAN_SCRIPT}"
else
    scp "/tmp/${SCAN_SCRIPT}" "${REMOTE}:${REMOTE_DIR}/${SCAN_SCRIPT}"
fi
rm "/tmp/${SCAN_SCRIPT}"

# Step 3: Run scan in background on remote
echo "[3/3] Starting scan on remote server..."
if [ -n "$SSH_OPTS" ]; then
    ssh ${SSH_OPTS} "${REMOTE}" "cd ${REMOTE_DIR} && chmod +x ${SCAN_SCRIPT} && nohup ./${SCAN_SCRIPT} > nohup-${TIMESTAMP}.out 2>&1 &"
else
    ssh "${REMOTE}" "cd ${REMOTE_DIR} && chmod +x ${SCAN_SCRIPT} && nohup ./${SCAN_SCRIPT} > nohup-${TIMESTAMP}.out 2>&1 &"
fi
echo "Done."
echo ""

echo "========================================"
echo "Scan is running on remote server!"
echo "========================================"
echo ""
echo "You will receive Slack notifications for:"
echo "  🚀 Scan started"
echo "  ✅ Scan completed (with results summary)"
echo "  ❌ Scan failed (with error details)"
echo ""
echo "Check progress:"
echo "  ssh ${SSH_OPTS} ${REMOTE} 'tail -f ${REMOTE_DIR}/scan-${TIMESTAMP}.log'"
echo ""
echo "Download results when done:"
echo "  scp ${SSH_OPTS} ${REMOTE}:${REMOTE_DIR}/scan-${TIMESTAMP}.log ."
echo "  scp ${SSH_OPTS} ${REMOTE}:${REMOTE_DIR}/report_*.html ."
echo "  scp ${SSH_OPTS} -r ${REMOTE}:${REMOTE_DIR}/data ./data-remote"
echo ""
echo "View report (after downloading data):"
echo "  ./start.sh"
echo "  open http://localhost:8002/api/scans"
echo ""
