#!/usr/bin/env bash
# Sherpa one-click startup script.
# Usage: ./start.sh
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
log "Checking Docker daemon..."
USE_SG=false
if docker info >/dev/null 2>&1; then
    USE_SG=false
elif sg docker -c "docker info >/dev/null 2>&1"; then
    USE_SG=true
else
    err "Cannot access Docker daemon. Start it first: sudo systemctl start docker"
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
# 2. Pre-flight checks
# ---------------------------------------------------------------------------

# 2a. Disk space check
log "Checking disk space..."
ROOT_USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
ROOT_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
if [ "${ROOT_USAGE:-100}" -ge 95 ]; then
    err "Root filesystem ${ROOT_USAGE}% full (${ROOT_AVAIL} available). Free space before starting."
    exit 1
fi
log "  Root filesystem: ${ROOT_USAGE}% used, ${ROOT_AVAIL} available ✓"

# 2b. Output directory check and stale cleanup
OUTPUT_DIR="${PWD}/output"
if [ -d "$OUTPUT_DIR" ]; then
    OUT_COUNT=$(find "$OUTPUT_DIR" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
    OUT_SIZE=$(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1 || echo "0")
    log "  Output directory: ${OUT_COUNT} workdirs, ${OUT_SIZE}"
    # Clean workdirs older than 14 days
    CLEANED=$(find "$OUTPUT_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +14 2>/dev/null | wc -l)
    if [ "${CLEANED:-0}" -gt 0 ]; then
        warn "  Found ${CLEANED} stale workdir(s) (>14 days). Remove with: find ${OUTPUT_DIR} -maxdepth 1 -mindepth 1 -type d -mtime +14 -exec rm -rf {} +"
    fi
fi

# 2c. Clean host Docker build cache (keep last 24h)
log "Pruning stale Docker build cache..."
BEFORE=$(docker_cmd "docker system df --format '{{.Size}}' 2>/dev/null" | head -1 || echo "0")
docker_cmd "docker builder prune --force --filter until=24h 2>/dev/null" || true
AFTER=$(docker_cmd "docker system df --format '{{.Size}}' 2>/dev/null" | head -1 || echo "0")
log "  Host Docker cache pruned."

# 2d. Check DNS resolution
log "Checking DNS resolution..."
if ! getent hosts registry-1.docker.io >/dev/null 2>&1; then
    warn "  Cannot resolve registry-1.docker.io — docker build may fail."
    warn "  Check /etc/docker/daemon.json DNS settings."
fi

# ---------------------------------------------------------------------------
# 3. Start services
# ---------------------------------------------------------------------------
log "Starting Sherpa services..."
docker_cmd "docker compose up -d"

# ---------------------------------------------------------------------------
# 4. Wait for containers to be healthy
# ---------------------------------------------------------------------------
log "Waiting for services to be healthy..."
MAX_WAIT=90
ELAPSED=0
ALL_HEALTHY=false
while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Count unhealthy containers (health status != 'healthy' and != '')
    UNHEALTHY=$(docker_cmd "docker compose ps -a --format json 2>/dev/null" | \
        python3 -c "
import sys, json
count = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    health = d.get('Health', '')
    if health and health != 'healthy':
        count += 1
print(count)
" 2>/dev/null || echo "99")

    if [ "${UNHEALTHY:-99}" -eq 0 ]; then
        ALL_HEALTHY=true
        log "All services healthy."
        break
    fi

    sleep 3
    ELAPSED=$((ELAPSED + 3))
done

if ! $ALL_HEALTHY; then
    warn "Some services may not be fully healthy after ${MAX_WAIT}s."
    warn "Current status:"
    docker_cmd "docker compose ps -a" || true
fi

# ---------------------------------------------------------------------------
# 5. Verify endpoints
# ---------------------------------------------------------------------------
log "Verifying endpoints..."

check_http() {
    local url="$1" label="$2"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [ "$code" = "200" ] || [ "$code" = "302" ]; then
        log "  ${label} → HTTP ${code} ✓"
    else
        err "  ${label} → HTTP ${code} ✗"
    fi
}

check_http "http://localhost:8000/"            "Gateway  (localhost:8000)"
check_http "http://localhost:8000/api/tasks"    "API      (localhost:8000/api/tasks)"

# GBrain memory health
MEMORY_HEALTH=$(curl -s --max-time 5 http://localhost:8000/api/memory/health 2>/dev/null || echo '{"healthy":false}')
if echo "$MEMORY_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('healthy') else 1)" 2>/dev/null; then
    log "  Memory   (localhost:8000/api/memory/health) → healthy ✓"
else
    warn "  Memory   (localhost:8000/api/memory/health) → unhealthy (may need more time)"
fi

# ---------------------------------------------------------------------------
# 6. Summary
# ---------------------------------------------------------------------------
echo ""
log "Sherpa services started."
echo "  Frontend: http://localhost:8000"
echo "  API:      http://localhost:8000/api/"
echo "  Docs:     http://localhost:8000/api/docs"
echo ""
echo "  Stop with: ./stop.sh"
echo "  Status:    sg docker -c 'docker compose ps'"
