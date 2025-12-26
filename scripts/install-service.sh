#!/bin/bash
# Install Website Quality Agent as a systemd service on remote server
#
# Usage:
#   ./scripts/install-service.sh          # Install and start service
#   ./scripts/install-service.sh status   # Check service status
#   ./scripts/install-service.sh logs     # View logs
#   ./scripts/install-service.sh restart  # Restart service

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

ssh_cmd() {
    ssh $SSH_OPTS "$REMOTE" "$@"
}

scp_cmd() {
    scp $SSH_OPTS "$@"
}

ACTION="${1:-install}"

case "$ACTION" in
    install)
        echo "Installing Website Quality Agent service on $REMOTE..."

        # Copy service file
        scp_cmd scripts/website-quality-agent.service "${REMOTE}:/tmp/"

        # Install service
        ssh_cmd << 'EOF'
sudo mv /tmp/website-quality-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable website-quality-agent
sudo systemctl start website-quality-agent
sleep 2
sudo systemctl status website-quality-agent --no-pager
EOF
        echo ""
        echo "✅ Service installed and started!"
        echo ""
        echo "Commands:"
        echo "  ./scripts/install-service.sh status   # Check status"
        echo "  ./scripts/install-service.sh logs     # View logs"
        echo "  ./scripts/install-service.sh restart  # Restart"
        ;;

    status)
        ssh_cmd "sudo systemctl status website-quality-agent --no-pager"
        ;;

    logs)
        ssh_cmd "sudo journalctl -u website-quality-agent -f"
        ;;

    restart)
        ssh_cmd "sudo systemctl restart website-quality-agent && sleep 2 && sudo systemctl status website-quality-agent --no-pager"
        ;;

    stop)
        ssh_cmd "sudo systemctl stop website-quality-agent"
        echo "Service stopped."
        ;;

    *)
        echo "Usage: $0 [install|status|logs|restart|stop]"
        exit 1
        ;;
esac
