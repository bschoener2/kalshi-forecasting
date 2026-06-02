#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env so docker compose variable substitution works
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

echo "==> Building Claude container image..."
docker build -t kalshi-forecasting-claude .

echo "==> Starting database..."
docker compose up -d db

# Validate required env vars
if [[ -z "${KALSHI_API_KEY_ID:-}" ]]; then
  echo "ERROR: KALSHI_API_KEY_ID is not set in .env"; exit 1
fi
if [[ -z "${KALSHI_PRIVATE_KEY_PATH:-}" ]]; then
  echo "ERROR: KALSHI_PRIVATE_KEY_PATH is not set in .env"; exit 1
fi
if [[ ! -f "$KALSHI_PRIVATE_KEY_PATH" ]]; then
  echo "ERROR: Private key not found at $KALSHI_PRIVATE_KEY_PATH"; exit 1
fi

# Remove any leftover container from a previous crashed run
docker rm -f secure-claude-agent 2>/dev/null || true

# The compose network name is <project-dir>_<network-name>.
# Project dir = kalshi-forecasting, network = internal.
NETWORK="kalshi-forecasting_internal"

echo "==> Launching Claude agent (--dangerously-skip-permissions)..."
docker run -it --rm \
  --name secure-claude-agent \
  --security-opt=no-new-privileges:true \
  --cap-drop=ALL \
  --memory="12g" \
  --cpus="5" \
  --network "$NETWORK" \
  -v "$SCRIPT_DIR:/workspace" \
  -v "${KALSHI_PRIVATE_KEY_PATH:-/dev/null}:/secrets/private_key.pem:ro" \
  -v "$HOME/.vimrc:/home/claudeuser/.vimrc:ro" \
  -e KALSHI_API_KEY_ID="${KALSHI_API_KEY_ID:-}" \
  -e KALSHI_PRIVATE_KEY_PATH=/secrets/private_key.pem \
  -e POSTGRES_HOST=db \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB="${POSTGRES_DB:-kalshi_forecasting}" \
  -e POSTGRES_USER="${POSTGRES_USER:-kalshi}" \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-localdev}" \
  -e BUDGET_DOLLARS="${BUDGET_DOLLARS:-100.0}" \
  -e MIN_HISTORY_DAYS="${MIN_HISTORY_DAYS:-365}" \
  -e CLAUDE_AGENT_ROLE=dev \
  -e CLAUDE_CONFIG_DIR=/home/claudeuser/.claude \
  kalshi-forecasting-claude
