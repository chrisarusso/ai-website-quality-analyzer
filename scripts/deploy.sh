#!/bin/bash
# Deploy Website Quality Agent to remote server via git
#
# Usage:
#   ./scripts/deploy.sh          # Deploy latest code and restart service
#   ./scripts/deploy.sh setup    # Initial setup (clone repo, install deps)
#   ./scripts/deploy.sh status   # Check service status
#   ./scripts/deploy.sh logs     # View logs

set -e
cd "$(dirname "$0")/.."

# Load config
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

REMOTE="${REMOTE_USER:-ubuntu}@${REMOTE_HOST}"
SSH_KEY="${REMOTE_SSH_KEY:-}"
SSH_OPTS=""
if [ -n "$SSH_KEY" ]; then
    SSH_KEY_EXPANDED="${SSH_KEY/#\~/$HOME}"
    SSH_OPTS="-i ${SSH_KEY_EXPANDED}"
fi

REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/website-quality-agent}"
GITHUB_REPO_URL="git@github.com:savaslabs/website-quality-agent.git"

ssh_cmd() {
    ssh $SSH_OPTS "$REMOTE" "$@"
}

ACTION="${1:-deploy}"

case "$ACTION" in
    setup)
        echo "Setting up Website Quality Agent on $REMOTE..."

        ssh_cmd << EOF
# Install dependencies
sudo apt-get update -qq
sudo apt-get install -y -qq git curl

# Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Clone or update repo
if [ -d "$REMOTE_DIR" ]; then
    echo "Directory exists, will use existing setup"
else
    echo "Cloning repo..."
    git clone $GITHUB_REPO_URL $REMOTE_DIR
fi

cd $REMOTE_DIR

# Install Python dependencies
~/.local/bin/uv sync

echo "Setup complete!"
EOF
        ;;

    deploy)
        echo "Deploying to $REMOTE..."

        # First, sync code via rsync (until git is set up)
        # Exclude .env to preserve remote-specific config
        echo "Syncing code..."
        rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
            --exclude '.venv' --exclude 'data/*.db' --exclude '.env' \
            -e "ssh $SSH_OPTS" . "${REMOTE}:${REMOTE_DIR}/"

        # Restart service
        ssh_cmd << EOF
cd $REMOTE_DIR
~/.local/bin/uv sync
sudo systemctl restart website-quality-agent
sleep 2
sudo systemctl status website-quality-agent --no-pager | head -10
EOF
        echo ""
        echo "Deployed! API available at http://${REMOTE_HOST}/website-quality-agent/"
        ;;

    deploy-git)
        echo "Deploying via git pull to $REMOTE..."

        ssh_cmd << EOF
cd $REMOTE_DIR
git pull origin main
~/.local/bin/uv sync
sudo systemctl restart website-quality-agent
sleep 2
sudo systemctl status website-quality-agent --no-pager | head -10
EOF
        echo ""
        echo "Deployed! API available at http://${REMOTE_HOST}/"
        ;;

    status)
        ssh_cmd "sudo systemctl status website-quality-agent --no-pager"
        ;;

    logs)
        ssh_cmd "sudo journalctl -u website-quality-agent -f"
        ;;

    logs-file)
        ssh_cmd "tail -f $REMOTE_DIR/api-server.log"
        ;;

    restart)
        ssh_cmd "sudo systemctl restart website-quality-agent && sleep 2 && sudo systemctl status website-quality-agent --no-pager | head -10"
        ;;

    stop)
        ssh_cmd "sudo systemctl stop website-quality-agent"
        echo "Service stopped."
        ;;

    *)
        echo "Usage: $0 [setup|deploy|deploy-git|status|logs|logs-file|restart|stop]"
        echo ""
        echo "Commands:"
        echo "  setup       Initial setup (install deps, clone repo)"
        echo "  deploy      Deploy via rsync and restart (default)"
        echo "  deploy-git  Deploy via git pull and restart"
        echo "  status      Check service status"
        echo "  logs        View systemd logs (live)"
        echo "  logs-file   View file logs (live)"
        echo "  restart     Restart service"
        echo "  stop        Stop service"
        exit 1
        ;;
esac
