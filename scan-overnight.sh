#!/bin/bash
# Run a full website scan overnight
# Usage: ./scan-overnight.sh https://example.com
#
# To run in background (survives terminal close):
#   nohup ./scan-overnight.sh https://savaslabs.com &
#
# Check progress:
#   tail -f scan-output.log

cd "$(dirname "$0")"

URL="${1:-https://savaslabs.com}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="scan-output-${TIMESTAMP}.log"

echo "Starting full scan of: $URL"
echo "Output: $LOG_FILE"
echo "Started at: $(date)"
echo ""

# Run scan with no page limit (9999 = effectively unlimited)
uv run website-agent scan "$URL" --max-pages 9999 2>&1 | tee "$LOG_FILE"

echo ""
echo "Scan completed at: $(date)"
echo "Results saved to: $LOG_FILE"

# Start the server so you can view the report
echo ""
echo "Starting server to view report..."
echo "Report will be at: http://localhost:8002/api/scans"
uv run website-agent serve
