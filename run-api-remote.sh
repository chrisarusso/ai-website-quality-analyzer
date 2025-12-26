#!/bin/bash
# Run the API server on a remote server persistently
#
# Usage:
#   ./run-api-remote.sh           # Start/restart API server
#   ./run-api-remote.sh stop      # Stop API server
#   ./run-api-remote.sh status    # Check if running
#   ./run-api-remote.sh logs      # Tail the logs
#
# The API will be accessible at: http://<REMOTE_HOST>:8002

set -e
cd "$(dirname "$0")"

# Load config from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Validate required settings
if [ -z "$REMOTE_HOST" ] || [ "$REMOTE_HOST" = "your-server.com" ]; then
    echo "Error: Set REMOTE_HOST in .env file"
    exit 1
fi

REMOTE="${REMOTE_USER:-$USER}@${REMOTE_HOST}"
REMOTE_DIR="${REMOTE_DIR:-/home/$USER/website-quality-agent}"
SSH_KEY="${REMOTE_SSH_KEY:-}"
API_PORT="${API_PORT:-8002}"

# Build SSH options
SSH_OPTS=""
SCP_OPTS=""
if [ -n "$SSH_KEY" ]; then
    SSH_KEY_EXPANDED="${SSH_KEY/#\~/$HOME}"
    SSH_OPTS="-i ${SSH_KEY_EXPANDED}"
    SCP_OPTS="-i ${SSH_KEY_EXPANDED}"
fi

ssh_cmd() {
    ssh $SSH_OPTS "$REMOTE" "$@"
}

scp_cmd() {
    scp $SCP_OPTS "$@"
}

rsync_cmd() {
    if [ -n "$SSH_OPTS" ]; then
        rsync -avz -e "ssh ${SSH_OPTS}" "$@"
    else
        rsync -avz "$@"
    fi
}

ACTION="${1:-start}"

case "$ACTION" in
    stop)
        echo "Stopping API server on $REMOTE..."
        ssh_cmd "pkill -f 'uvicorn website_agent.api.app' || true"
        echo "Stopped."
        ;;

    status)
        echo "Checking API server status on $REMOTE..."
        if ssh_cmd "pgrep -f 'uvicorn website_agent.api.app' > /dev/null 2>&1"; then
            echo "✅ API server is RUNNING"
            ssh_cmd "pgrep -af 'uvicorn website_agent.api.app'"
            echo ""
            echo "API URL: http://${REMOTE_HOST}:${API_PORT}"
            echo "Test:    curl http://${REMOTE_HOST}:${API_PORT}/"
        else
            echo "❌ API server is NOT running"
        fi
        ;;

    logs)
        echo "Tailing API logs from $REMOTE..."
        ssh_cmd "tail -f ${REMOTE_DIR}/api-server.log"
        ;;

    start|restart)
        echo "========================================"
        echo "Remote API Server Deployment"
        echo "========================================"
        echo "Remote server: $REMOTE"
        echo "Remote dir:    $REMOTE_DIR"
        echo "API port:      $API_PORT"
        echo "========================================"
        echo ""

        # Step 1: Sync code
        echo "[1/4] Syncing code to remote server..."
        rsync_cmd --exclude '.venv' --exclude '__pycache__' \
            --exclude '.pytest_cache' --exclude '*.log' --exclude 'report_*.html' \
            ./ "${REMOTE}:${REMOTE_DIR}/"
        echo "Done."

        # Step 2: Stop existing server
        echo "[2/4] Stopping existing API server (if running)..."
        ssh_cmd "pkill -f 'uvicorn website_agent.api.app' || true"
        sleep 2
        echo "Done."

        # Step 3: Install dependencies
        echo "[3/4] Installing dependencies..."
        ssh_cmd "cd ${REMOTE_DIR} && ~/.local/bin/uv sync 2>&1 | tail -3"
        echo "Done."

        # Step 4: Start API server
        echo "[4/4] Starting API server..."
        ssh_cmd "cd ${REMOTE_DIR} && nohup ~/.local/bin/uv run uvicorn website_agent.api.app:app --host 0.0.0.0 --port ${API_PORT} > api-server.log 2>&1 &"
        sleep 3

        # Verify it's running
        if ssh_cmd "pgrep -f 'uvicorn website_agent.api.app' > /dev/null 2>&1"; then
            echo ""
            echo "========================================"
            echo "✅ API Server is running!"
            echo "========================================"
            echo ""
            echo "API URL: http://${REMOTE_HOST}:${API_PORT}"
            echo ""
            echo "Test endpoints:"
            echo "  curl http://${REMOTE_HOST}:${API_PORT}/"
            echo "  curl http://${REMOTE_HOST}:${API_PORT}/api/scans"
            echo ""
            echo "View logs:"
            echo "  ./run-api-remote.sh logs"
            echo ""
            echo "Stop server:"
            echo "  ./run-api-remote.sh stop"
            echo ""

            # Quick test
            echo "Testing API..."
            if curl -s "http://${REMOTE_HOST}:${API_PORT}/" > /dev/null 2>&1; then
                echo "✅ API is responding!"
            else
                echo "⚠️  API may still be starting. Wait a few seconds and try:"
                echo "   curl http://${REMOTE_HOST}:${API_PORT}/"
            fi
        else
            echo ""
            echo "❌ API server failed to start!"
            echo "Check logs: ssh $SSH_OPTS $REMOTE 'cat ${REMOTE_DIR}/api-server.log'"
            exit 1
        fi
        ;;

    *)
        echo "Usage: $0 [start|stop|status|logs]"
        exit 1
        ;;
esac
