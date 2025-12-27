#!/bin/bash
# Deploy website-quality-agent to remote server
# Simple: git pull on server, install deps, restart service
#
# Usage: ./scripts/deploy.sh

set -e

# Configuration
REMOTE_HOST="${REMOTE_HOST:-ubuntu@3.16.155.59}"
SSH_KEY="${SSH_KEY:-~/.ssh/AWS-created-nov-27-2025.pem}"
REMOTE_DIR="/home/ubuntu/website-quality-agent"
SERVICE_NAME="website-quality-agent"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Website Quality Agent - Deploy"
echo "=========================================="

# Check for uncommitted local changes
if ! git diff --quiet HEAD 2>/dev/null; then
    echo -e "${YELLOW}Warning: You have uncommitted local changes${NC}"
    git status --short
    echo ""
    echo "Commit and push first, then deploy."
    exit 1
fi

# Check if local is ahead of remote
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse github/master 2>/dev/null || echo "unknown")

if [ "$LOCAL" != "$REMOTE" ]; then
    echo -e "${YELLOW}Local and github/master differ${NC}"
    echo "Local:  $LOCAL"
    echo "Remote: $REMOTE"
    echo ""
    echo "Push your changes first: git push github master"
    exit 1
fi

echo "Deploying commit: $(git rev-parse --short HEAD)"
echo ""

# SSH and deploy
echo "[1/3] Pulling latest code on server..."
ssh -i "$SSH_KEY" "$REMOTE_HOST" "cd $REMOTE_DIR && git fetch github && git reset --hard github/master"

echo "[2/3] Installing dependencies..."
ssh -i "$SSH_KEY" "$REMOTE_HOST" "cd $REMOTE_DIR && /home/ubuntu/.local/bin/uv sync --quiet"

echo "[3/3] Restarting service..."
ssh -i "$SSH_KEY" "$REMOTE_HOST" "sudo systemctl restart $SERVICE_NAME"
sleep 2

STATUS=$(ssh -i "$SSH_KEY" "$REMOTE_HOST" "systemctl is-active $SERVICE_NAME" 2>/dev/null || echo "failed")

echo ""
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}✓ Deploy successful!${NC}"
    echo "  Commit: $(git rev-parse --short HEAD)"
    echo "  Status: $STATUS"
else
    echo -e "${RED}✗ Deploy failed - service not running${NC}"
    echo "  Check logs: ssh -i $SSH_KEY $REMOTE_HOST 'journalctl -u $SERVICE_NAME -n 50'"
    exit 1
fi
