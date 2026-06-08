#!/bin/bash
# Sherpa shutdown script.
# Usage: bash scripts/stop.sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

USE_SG=false
if ! docker info >/dev/null 2>&1; then
    if sg docker -c "docker info >/dev/null 2>&1"; then
        USE_SG=true
    else
        echo "[!] Cannot access Docker."
        exit 1
    fi
fi

docker_cmd() {
    if $USE_SG; then
        sg docker -c "$*"
    else
        "$@"
    fi
}

echo "[*] Disconnecting gbrain memory database from compose network..."
docker_cmd docker network disconnect remove_k8s_default gbrain-mcp-pg 2>/dev/null || true

echo "[*] Stopping Sherpa services..."
docker_cmd docker compose down

echo "[*] Stopping gbrain memory database..."
docker_cmd docker stop gbrain-mcp-pg 2>/dev/null || true

echo "[+] All services stopped."
