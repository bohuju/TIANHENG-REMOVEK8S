#!/usr/bin/env bash
# Sherpa shutdown script.
# Usage: ./stop.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# 1. Docker daemon detection
# ---------------------------------------------------------------------------
USE_SG=false
if docker info >/dev/null 2>&1; then
    USE_SG=false
elif sg docker -c "docker info >/dev/null 2>&1"; then
    USE_SG=true
else
    err "Cannot access Docker daemon."
    exit 1
fi

docker_cmd() {
    if $USE_SG; then
        sg docker -c "$*"
    else
        eval "$@"
    fi
}

# ---------------------------------------------------------------------------
# 2. Pre-stop cleanup of dangling resources
# ---------------------------------------------------------------------------

# 2a. Kill any orphaned pool containers
log "Cleaning up orphaned pool containers..."
POOL_IDS=$(docker_cmd "docker ps -q --filter 'name=sherpa-pool-' 2>/dev/null" || echo "")
if [ -n "${POOL_IDS:-}" ]; then
    echo "$POOL_IDS" | while read -r cid; do
        [ -z "$cid" ] && continue
        docker_cmd "docker rm -f ${cid} 2>/dev/null" || true
    done
    log "  Removed orphaned pool container(s)."
fi

# 2b. Stop any lingering runtime containers for Sherpa
log "Stopping lingering runtime containers..."
RUNTIME_IDS=$(docker_cmd "docker ps -q --filter 'label=sherpa.repo_root' 2>/dev/null" || echo "")
if [ -n "${RUNTIME_IDS:-}" ]; then
    echo "$RUNTIME_IDS" | while read -r cid; do
        [ -z "$cid" ] && continue
        docker_cmd "docker rm -f ${cid} 2>/dev/null" || true
    done
    log "  Removed lingering runtime container(s)."
fi

# ---------------------------------------------------------------------------
# 3. Network disconnect (prevent DNS timeout on shutdown)
# ---------------------------------------------------------------------------
log "Disconnecting external containers from compose network..."
NETWORK_NAME="remove_k8s_default"
docker_cmd "docker network disconnect ${NETWORK_NAME} gbrain-mcp-pg 2>/dev/null" || true

# ---------------------------------------------------------------------------
# 4. Stop all compose services
# ---------------------------------------------------------------------------
log "Stopping Sherpa services..."
docker_cmd "docker compose down --remove-orphans"

# ---------------------------------------------------------------------------
# 5. Stop gbrain memory database (external container)
# ---------------------------------------------------------------------------
log "Stopping gbrain memory database..."
docker_cmd "docker stop gbrain-mcp-pg 2>/dev/null" || true
docker_cmd "docker rm gbrain-mcp-pg 2>/dev/null" || true

# ---------------------------------------------------------------------------
# 6. Prune dind resources (lightweight)
# ---------------------------------------------------------------------------
log "Pruning dind resources..."
# Only prune dangling images and expired build cache inside dind
DIND_CID=$(docker_cmd "docker ps -a --filter 'name=sherpa-docker' --format '{{.ID}}' 2>/dev/null" | head -1 || echo "")
if [ -n "${DIND_CID:-}" ]; then
    docker_cmd "docker exec ${DIND_CID} docker image prune --force --filter 'until=1h' 2>/dev/null" || true
    docker_cmd "docker exec ${DIND_CID} docker builder prune --force --filter 'until=1h' 2>/dev/null" || true
    log "  dind resources pruned."
else
    log "  dind container not running, skipping."
fi

# ---------------------------------------------------------------------------
# 7. Prune host Docker build cache
# ---------------------------------------------------------------------------
log "Pruning host Docker build cache (older than 24h)..."
docker_cmd "docker builder prune --force --filter until=24h 2>/dev/null" || true

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
echo ""
log "All Sherpa services stopped and cleaned up."
log "Volumes are preserved. To remove volumes too:"
echo "    sg docker -c 'docker compose down -v'"
echo "    sg docker -c 'docker volume prune -f'"
