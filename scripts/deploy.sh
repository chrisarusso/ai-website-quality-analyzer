#!/bin/bash
# Sync website-quality-agent with remote server
# Remote server is treated as authoritative - always pull first
#
# Usage:
#   ./scripts/deploy.sh        # Pull from server, show diff, optionally push
#   ./scripts/deploy.sh pull   # Only pull from server (no push)
#   ./scripts/deploy.sh push   # Pull first, then push (with confirmation)

set -e

# Configuration
REMOTE_HOST="${REMOTE_HOST:-ubuntu@3.16.155.59}"
SSH_KEY="${SSH_KEY:-~/.ssh/AWS-created-nov-27-2025.pem}"
REMOTE_DIR="/home/ubuntu/website-quality-agent"
SERVICE_NAME="website-quality-agent"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# What to sync (exclude generated files, keep config)
RSYNC_EXCLUDES=(
    --exclude='.venv'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='.pytest_cache'
    --exclude='.git'
    --exclude='report_*.html'
    --exclude='*.log'
    --exclude='scan-*.log'
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MODE="${1:-interactive}"

echo "=========================================="
echo "Website Quality Agent - Sync"
echo "=========================================="
echo "Remote: $REMOTE_HOST:$REMOTE_DIR"
echo "Local:  $LOCAL_DIR"
echo "Mode:   $MODE"
echo ""

# Check SSH connectivity
echo -e "${BLUE}[1/4]${NC} Checking SSH connectivity..."
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 "$REMOTE_HOST" 'echo "Connected"' 2>/dev/null; then
    echo -e "${RED}✗ Cannot connect to $REMOTE_HOST${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Connected${NC}"

# Step 2: Pull from remote (always do this first)
echo ""
echo -e "${BLUE}[2/4]${NC} Pulling changes from remote server..."

# Dry-run first to see what would change
PULL_CHANGES=$(rsync -avzn "${RSYNC_EXCLUDES[@]}" \
    -e "ssh -i $SSH_KEY" \
    "$REMOTE_HOST:$REMOTE_DIR/" "$LOCAL_DIR/" 2>&1 | grep -E "^[^(sent|total|receiving)]" | grep -v "^$" | grep -v "^\./$")

if [ -z "$PULL_CHANGES" ]; then
    echo -e "${GREEN}✓ Local is up to date with remote${NC}"
else
    echo -e "${YELLOW}Changes on remote server:${NC}"
    echo "$PULL_CHANGES"
    echo ""

    if [ "$MODE" = "pull" ] || [ "$MODE" = "interactive" ] || [ "$MODE" = "push" ]; then
        echo "Pulling changes..."
        rsync -avz "${RSYNC_EXCLUDES[@]}" \
            -e "ssh -i $SSH_KEY" \
            "$REMOTE_HOST:$REMOTE_DIR/" "$LOCAL_DIR/"
        echo -e "${GREEN}✓ Pulled changes from remote${NC}"
    fi
fi

# If pull-only mode, stop here
if [ "$MODE" = "pull" ]; then
    echo ""
    echo -e "${GREEN}=========================================="
    echo "✓ Pull complete"
    echo -e "==========================================${NC}"
    exit 0
fi

# Step 3: Check what local changes would be pushed
echo ""
echo -e "${BLUE}[3/4]${NC} Checking local changes to push..."

PUSH_CHANGES=$(rsync -avzn "${RSYNC_EXCLUDES[@]}" \
    -e "ssh -i $SSH_KEY" \
    "$LOCAL_DIR/" "$REMOTE_HOST:$REMOTE_DIR/" 2>&1 | grep -E "^[^(sent|total|sending)]" | grep -v "^$" | grep -v "^\./$")

if [ -z "$PUSH_CHANGES" ]; then
    echo -e "${GREEN}✓ Remote is up to date with local${NC}"
    echo ""
    echo -e "${GREEN}=========================================="
    echo "✓ Everything in sync!"
    echo -e "==========================================${NC}"
    exit 0
fi

echo -e "${YELLOW}Local changes to push:${NC}"
echo "$PUSH_CHANGES"
echo ""

# Confirm push
if [ "$MODE" = "interactive" ]; then
    read -p "Push these changes to remote? [y/N]: " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Aborted. No changes pushed."
        exit 0
    fi
elif [ "$MODE" != "push" ]; then
    echo "Run with 'push' argument to push changes"
    exit 0
fi

# Step 4: Push to remote and restart
echo ""
echo -e "${BLUE}[4/4]${NC} Pushing changes and restarting service..."

rsync -avz "${RSYNC_EXCLUDES[@]}" \
    -e "ssh -i $SSH_KEY" \
    "$LOCAL_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"

echo -e "${GREEN}✓ Changes pushed${NC}"

# Install dependencies
echo "Installing dependencies..."
ssh -i "$SSH_KEY" "$REMOTE_HOST" "cd $REMOTE_DIR && /home/ubuntu/.local/bin/uv sync --quiet"
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Restart service
echo "Restarting service..."
ssh -i "$SSH_KEY" "$REMOTE_HOST" "sudo systemctl restart $SERVICE_NAME"
sleep 2

STATUS=$(ssh -i "$SSH_KEY" "$REMOTE_HOST" "systemctl is-active $SERVICE_NAME" 2>/dev/null || echo "unknown")

echo ""
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}=========================================="
    echo "✓ Deploy successful!"
    echo -e "==========================================${NC}"
    echo ""
    echo "  Service status: active"
    echo ""
    echo "View logs:"
    echo "  ssh -i $SSH_KEY $REMOTE_HOST 'journalctl -u $SERVICE_NAME -f'"
    exit 0
else
    echo -e "${RED}=========================================="
    echo "✗ Service not running after deploy!"
    echo -e "==========================================${NC}"
    echo ""
    echo "  Service status: $STATUS"
    echo ""
    echo "Check logs:"
    echo "  ssh -i $SSH_KEY $REMOTE_HOST 'journalctl -u $SERVICE_NAME -n 50'"
    exit 1
fi
