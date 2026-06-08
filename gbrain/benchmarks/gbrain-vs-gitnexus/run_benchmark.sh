#!/bin/bash
set -euo pipefail
cd /home/bohuju/self_project/gbrain

export MINIMAX_API_KEY="sk-api-tvRVJSwEWojQlpD2Ax6skG5Eq5eGUgiDyp1hTl-6LWXuspP-1YkmtoF-PZjlZ85I32HMQL61J5Q1FDCpHsx58wDLBIGzNXjaYusEjS5EzXDCFwzjCuFOduY"
export EMBEDDING_BACKEND=minimax
export JUDGE_API_KEY="sk-33923bd352184d5885118e64846101b9"
export JUDGE_MODEL="deepseek-chat"
export JUDGE_BASE_URL="https://api.deepseek.com/v1"
export PREACT_REPO="/tmp/preact-bench"
export PREACT_COMMIT="a31df28ef6cab46ff877a8a51b69d62f0618eb57"
export GBRAIN_NEXUS_BIN="/home/bohuju/self_project/gbrain-gitnexus/bin/gbrain"
export OPENCODE_CMD='opencode run --model deepseek/deepseek-v4-pro --dangerously-skip-permissions "$(cat {promptFile})"'

echo "=== Starting GBrain GitNexus Benchmark (Preact) ==="
echo "PREACT_REPO=$PREACT_REPO"
echo "GBRAIN_NEXUS_BIN=$GBRAIN_NEXUS_BIN"
echo "JUDGE_MODEL=$JUDGE_MODEL"
echo "EMBEDDING_BACKEND=$EMBEDDING_BACKEND"
echo ""

bun run benchmarks/gbrain-vs-gitnexus/runner/run.ts
