#!/usr/bin/env bash
set -euo pipefail

# One-command remote runner for Website Quality Agent.
# Uses .env for SSH details and scan settings, then runs a background scan remotely.
#
# Required env (set in .env in this repo):
#   REMOTE_HOST=your.server.ip
#   REMOTE_USER=youruser
#   REMOTE_KEY=/path/to/id_rsa
#   REMOTE_PATH=/path/to/proj-web-qual   # directory on remote containing this repo
#   SCAN_URL=https://example.com         # target site
# Optional:
#   MAX_PAGES=300
#   RATE_LIMIT_SECONDS=1.5
#   SSH_PORT=22
#
# Usage:
#   ./remote_run.sh
#
# The script will:
#   - ssh to REMOTE_HOST
#   - ensure venv + install deps
#   - run website-agent scan in the background via nohup
#   - log to remote-scan.log on the remote host

if [ -f ".env" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

REQ_VARS=(REMOTE_HOST REMOTE_USER REMOTE_KEY REMOTE_PATH SCAN_URL)
for v in "${REQ_VARS[@]}"; do
  if [ -z "${!v-}" ]; then
    echo "Missing required env: $v (set it in .env)" >&2
    exit 1
  fi
done

MAX_PAGES="${MAX_PAGES:-300}"
RATE_LIMIT_SECONDS="${RATE_LIMIT_SECONDS:-1.5}"
SSH_PORT="${SSH_PORT:-22}"

SSH_CMD=(
  ssh
  -i "$REMOTE_KEY"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=accept-new
  "${REMOTE_USER}@${REMOTE_HOST}"
)

read -r -d '' REMOTE_SCRIPT <<'EOSSH'
set -euo pipefail
cd "$REMOTE_PATH"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e .
nohup bash -c "website-agent \"$SCAN_URL\" --max-pages \"$MAX_PAGES\" --rate-limit \"$RATE_LIMIT_SECONDS\"" \
  > remote-scan.log 2>&1 &
echo "Started remote scan with PID $!"
echo "Log: $PWD/remote-scan.log"
EOSSH

# Pass local variables to remote via environment.
env REMOTE_PATH="$REMOTE_PATH" SCAN_URL="$SCAN_URL" MAX_PAGES="$MAX_PAGES" RATE_LIMIT_SECONDS="$RATE_LIMIT_SECONDS" \
  "${SSH_CMD[@]}" "$REMOTE_SCRIPT"

