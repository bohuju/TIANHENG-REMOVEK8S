#!/bin/bash
# Sherpa one-click startup script.
# Usage: bash scripts/start.sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "[*] Checking Docker daemon..."
USE_SG=false
if ! docker info >/dev/null 2>&1; then
    if sg docker -c "docker info >/dev/null 2>&1"; then
        USE_SG=true
    else
        echo "[!] Cannot access Docker. Start the daemon first: sudo systemctl start docker"
        exit 1
    fi
fi

# Helper: run a docker command, via sg if needed.
docker_cmd() {
    if $USE_SG; then
        sg docker -c "$*"
    else
        "$@"
    fi
}

echo "[*] Checking Docker DNS..."
if ! docker_cmd docker run --rm alpine cat /etc/resolv.conf 2>/dev/null | grep -q 'nameserver'; then
    echo "[!] Docker DNS may be broken. If builds fail, add to /etc/docker/daemon.json:"
    echo '    {"dns": ["8.8.8.8", "1.1.1.1"]}'
    echo "    Then: sudo systemctl restart docker"
fi

echo "[*] Starting services..."
docker_cmd docker compose up -d

echo "[*] Waiting for services to be ready..."
ATTEMPTS=0
MAX_ATTEMPTS=30
while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/system 2>/dev/null | grep -q '200'; then
        break
    fi
    sleep 2
    ATTEMPTS=$((ATTEMPTS + 1))
done

if [ $ATTEMPTS -ge $MAX_ATTEMPTS ]; then
    echo "[!] API did not become ready within ${MAX_ATTEMPTS}s. Check logs:"
    echo "    docker compose logs sherpa-web"
    exit 1
fi

echo "[+] API ready (http://localhost:8000/api/system)"

# ── GBrain memory database ──────────────────────────────────────────

echo "[*] Starting gbrain memory database..."
if docker_cmd docker ps -a --format '{{.Names}}' | grep -q '^gbrain-mcp-pg$'; then
    docker_cmd docker start gbrain-mcp-pg 2>/dev/null || true
    docker_cmd docker network connect remove_k8s_default gbrain-mcp-pg 2>/dev/null || true
    echo "[+] gbrain-mcp-pg started and connected to network"
else
    echo "[!] gbrain-mcp-pg container not found. Memory features will be unavailable."
    echo "    The gbrain-postgres service (defined in docker-compose.yml) is empty."
    echo "    Restore gbrain-mcp-pg from backup or populate gbrain-postgres."
fi

# ── Verify memory health ────────────────────────────────────────────

echo "[*] Checking memory health..."
sleep 3
MEMORY_HEALTH=$(curl -s http://localhost:8000/api/memory/health 2>/dev/null || echo '{}')
if echo "$MEMORY_HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('healthy') else 1)" 2>/dev/null; then
    echo "[+] GBrain memory healthy"
else
    echo "[!] GBrain memory not healthy: $MEMORY_HEALTH"
    echo "[*] Restarting sherpa-web to reset gbrain connection..."
    docker_cmd docker compose restart sherpa-web
    sleep 5
    MEMORY_HEALTH2=$(curl -s http://localhost:8000/api/memory/health 2>/dev/null || echo '{}')
    if echo "$MEMORY_HEALTH2" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('healthy') else 1)" 2>/dev/null; then
        echo "[+] GBrain memory healthy after restart"
    else
        echo "[!] GBrain memory still not healthy. Check: docker logs remove_k8s-sherpa-web-1 | grep -i gbrain"
    fi
fi

echo ""
echo "============================================"
echo "  TianHeng is running at http://localhost:8000"
echo "============================================"
