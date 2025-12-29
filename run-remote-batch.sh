#!/bin/bash
# Run multiple website scans sequentially on remote server
#
# Usage:
#   ./run-remote-batch.sh url1 url2 url3
#   ./run-remote-batch.sh --file sites.txt
#
# Each scan completes before the next starts.
# Slack notifications sent for each scan + batch summary at end.

set -e
cd "$(dirname "$0")"

# Load config from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Parse arguments
URLS=()
if [ "$1" = "--file" ] && [ -f "$2" ]; then
    while IFS= read -r line; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        URLS+=("$line")
    done < "$2"
else
    URLS=("$@")
fi

if [ ${#URLS[@]} -eq 0 ]; then
    echo "Usage: ./run-remote-batch.sh url1 url2 url3"
    echo "       ./run-remote-batch.sh --file sites.txt"
    echo ""
    echo "Example sites.txt:"
    echo "  https://example.com"
    echo "  https://another-site.com"
    exit 1
fi

# Validate required settings
if [ -z "$REMOTE_HOST" ] || [ "$REMOTE_HOST" = "your-server.com" ]; then
    echo "Error: Set REMOTE_HOST in .env file"
    exit 1
fi

REMOTE="${REMOTE_USER:-ubuntu}@${REMOTE_HOST}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/website-quality-agent}"
SSH_KEY="${REMOTE_SSH_KEY:-}"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL:-}"
MAX_PAGES="${SCAN_MAX_PAGES:-9999}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Build SSH options
SSH_OPTS=""
SCP_OPTS=""
if [ -n "$SSH_KEY" ]; then
    SSH_KEY_EXPANDED="${SSH_KEY/#\~/$HOME}"
    SSH_OPTS="-i ${SSH_KEY_EXPANDED}"
    SCP_OPTS="-i ${SSH_KEY_EXPANDED}"
fi

echo "========================================"
echo "Remote Batch Scanner"
echo "========================================"
echo "Remote server: $REMOTE"
echo "Sites to scan: ${#URLS[@]}"
for url in "${URLS[@]}"; do
    echo "  - $url"
done
echo "Max pages:     $MAX_PAGES per site"
echo "Slack:         $([ -n "$SLACK_WEBHOOK" ] && echo "Enabled" || echo "Disabled")"
echo "========================================"
echo ""

# Step 1: Sync code to remote
echo "[1/3] Syncing code to remote server..."
rsync -avz -e "ssh ${SSH_OPTS}" --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude '*.log' --exclude 'report_*.html' \
    ./ "${REMOTE}:${REMOTE_DIR}/"
echo "Done."
echo ""

# Step 2: Create the batch script
echo "[2/3] Preparing batch scan script..."

# Convert URLs array to newline-separated string for embedding
URLS_LIST=$(printf '%s\n' "${URLS[@]}")

cat > "/tmp/batch-${TIMESTAMP}.sh" << 'BATCH_SCRIPT'
#!/bin/bash
set -e

# Configuration (injected by run-remote-batch.sh)
REMOTE_DIR="__REMOTE_DIR__"
MAX_PAGES="__MAX_PAGES__"
SLACK_WEBHOOK="__SLACK_WEBHOOK__"
TIMESTAMP="__TIMESTAMP__"
REMOTE_HOST="__REMOTE_HOST__"

# URLs to scan (one per line)
read -r -d '' URLS_RAW << 'URLS_END' || true
__URLS_LIST__
URLS_END

cd "${REMOTE_DIR}"
export PATH="$HOME/.local/bin:$PATH"

# Parse URLs into array
mapfile -t URLS <<< "$URLS_RAW"

TOTAL_SITES=${#URLS[@]}
BATCH_START=$(date +%s)
SUCCESSFUL=0
FAILED=0
RESULTS_SUMMARY=""

# Slack notification function
send_slack() {
    local emoji="$1"
    local title="$2"
    local message="$3"

    [ -z "$SLACK_WEBHOOK" ] && return 0

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
                    "text": "Server: \`${REMOTE_HOST}\` | Batch: \`${TIMESTAMP}\`"
                }
            ]
        }
    ]
}
EOF
)
    curl -s -X POST -H 'Content-type: application/json' --data "$payload" "$SLACK_WEBHOOK" > /dev/null 2>&1 || true
}

# Send batch start notification
send_slack "🌙" "Overnight Batch Scan Started" "*Sites:* ${TOTAL_SITES}\n*Max Pages:* ${MAX_PAGES} per site\n*Started:* $(date '+%Y-%m-%d %H:%M:%S %Z')"

# Install dependencies once
echo "Installing dependencies..."
uv sync 2>&1 | tail -3
uv run playwright install chromium 2>&1 | tail -2

# Process each URL
CURRENT=0
for URL in "${URLS[@]}"; do
    CURRENT=$((CURRENT + 1))
    SCAN_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="scan-${SCAN_TIMESTAMP}.log"

    echo ""
    echo "========================================"
    echo "[${CURRENT}/${TOTAL_SITES}] Scanning: ${URL}"
    echo "Started: $(date)"
    echo "========================================"

    SCAN_START=$(date +%s)

    # Send individual scan start
    send_slack "🔍" "Scan ${CURRENT}/${TOTAL_SITES} Started" "*URL:* ${URL}"

    # Run the scan
    if uv run website-agent scan "${URL}" --max-pages ${MAX_PAGES} --output html 2>&1 | tee "$LOG_FILE"; then
        SCAN_EXIT=0
    else
        SCAN_EXIT=$?
    fi

    SCAN_END=$(date +%s)
    SCAN_DURATION=$((SCAN_END - SCAN_START))
    SCAN_MIN=$((SCAN_DURATION / 60))
    SCAN_SEC=$((SCAN_DURATION % 60))

    # Extract results
    PAGES=$(grep -oP 'Crawled \K[0-9]+' "$LOG_FILE" 2>/dev/null | tail -1 || echo "?")
    ISSUES=$(grep -oP 'Total Issues: \K[0-9]+' "$LOG_FILE" 2>/dev/null || echo "?")
    SCORE=$(grep -oP 'Overall Score: \K[0-9.]+' "$LOG_FILE" 2>/dev/null || echo "?")

    # Track results
    SITE_RESULT="${URL} → ${PAGES} pages, ${ISSUES} issues, score ${SCORE}"

    if [ $SCAN_EXIT -eq 0 ]; then
        SUCCESSFUL=$((SUCCESSFUL + 1))
        send_slack "✅" "Scan ${CURRENT}/${TOTAL_SITES} Complete" "*URL:* ${URL}\n*Pages:* ${PAGES} | *Issues:* ${ISSUES} | *Score:* ${SCORE}/100\n*Duration:* ${SCAN_MIN}m ${SCAN_SEC}s"
        RESULTS_SUMMARY="${RESULTS_SUMMARY}✅ ${SITE_RESULT}\n"
    else
        FAILED=$((FAILED + 1))
        send_slack "❌" "Scan ${CURRENT}/${TOTAL_SITES} Failed" "*URL:* ${URL}\n*Exit Code:* ${SCAN_EXIT}\n*Duration:* ${SCAN_MIN}m ${SCAN_SEC}s"
        RESULTS_SUMMARY="${RESULTS_SUMMARY}❌ ${URL} (failed)\n"
    fi

    echo ""
    echo "Completed: ${URL}"
    echo "Duration: ${SCAN_MIN}m ${SCAN_SEC}s"
    echo ""

    # Brief pause between scans to be nice to servers
    if [ $CURRENT -lt $TOTAL_SITES ]; then
        echo "Waiting 30 seconds before next scan..."
        sleep 30
    fi
done

# Calculate total duration
BATCH_END=$(date +%s)
BATCH_DURATION=$((BATCH_END - BATCH_START))
BATCH_HOURS=$((BATCH_DURATION / 3600))
BATCH_MIN=$(((BATCH_DURATION % 3600) / 60))

# Send batch complete notification
send_slack "🎉" "Overnight Batch Complete" "*Total Sites:* ${TOTAL_SITES}\n*Successful:* ${SUCCESSFUL}\n*Failed:* ${FAILED}\n*Duration:* ${BATCH_HOURS}h ${BATCH_MIN}m\n\n*Results:*\n${RESULTS_SUMMARY}"

echo ""
echo "========================================"
echo "BATCH COMPLETE"
echo "========================================"
echo "Total sites: ${TOTAL_SITES}"
echo "Successful:  ${SUCCESSFUL}"
echo "Failed:      ${FAILED}"
echo "Duration:    ${BATCH_HOURS}h ${BATCH_MIN}m"
echo "========================================"
BATCH_SCRIPT

# Inject values
sed -i '' "s|__REMOTE_DIR__|${REMOTE_DIR}|g" "/tmp/batch-${TIMESTAMP}.sh"
sed -i '' "s|__MAX_PAGES__|${MAX_PAGES}|g" "/tmp/batch-${TIMESTAMP}.sh"
sed -i '' "s|__SLACK_WEBHOOK__|${SLACK_WEBHOOK}|g" "/tmp/batch-${TIMESTAMP}.sh"
sed -i '' "s|__TIMESTAMP__|${TIMESTAMP}|g" "/tmp/batch-${TIMESTAMP}.sh"
sed -i '' "s|__REMOTE_HOST__|${REMOTE_HOST}|g" "/tmp/batch-${TIMESTAMP}.sh"

# Inject URLs (using a temp file to handle special chars)
echo "$URLS_LIST" > "/tmp/urls-${TIMESTAMP}.txt"
# Use perl for safer substitution with newlines
perl -i -pe "s|__URLS_LIST__|$(cat /tmp/urls-${TIMESTAMP}.txt | sed 's/|/\\|/g')|g" "/tmp/batch-${TIMESTAMP}.sh"
rm "/tmp/urls-${TIMESTAMP}.txt"

# Copy to remote
scp ${SCP_OPTS} "/tmp/batch-${TIMESTAMP}.sh" "${REMOTE}:${REMOTE_DIR}/batch-${TIMESTAMP}.sh"
rm "/tmp/batch-${TIMESTAMP}.sh"

# Step 3: Run batch in background
echo "[3/3] Starting batch scan on remote server..."
ssh ${SSH_OPTS} "${REMOTE}" "cd ${REMOTE_DIR} && chmod +x batch-${TIMESTAMP}.sh && nohup ./batch-${TIMESTAMP}.sh > nohup-batch-${TIMESTAMP}.out 2>&1 &"
echo "Done."
echo ""

echo "========================================"
echo "Batch scan is running on remote server!"
echo "========================================"
echo ""
echo "Slack notifications:"
echo "  🌙 Batch started"
echo "  🔍 Each scan started"
echo "  ✅ Each scan completed"
echo "  🎉 Batch complete with summary"
echo ""
echo "Check progress:"
echo "  ssh ${SSH_OPTS} ${REMOTE} 'tail -f ${REMOTE_DIR}/nohup-batch-${TIMESTAMP}.out'"
echo ""
echo "Download all reports when done:"
echo "  scp ${SCP_OPTS} ${REMOTE}:${REMOTE_DIR}/report_*.html ."
echo "  scp ${SCP_OPTS} -r ${REMOTE}:${REMOTE_DIR}/data ./data-remote"
echo ""
