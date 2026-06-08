#!/bin/bash
set -euo pipefail
PARTIAL=0

REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/layer_explanation.md"

echo "=== Check output file exists ==="
[ -f "$OUTFILE" ] || { echo "FAIL: layer_explanation.md not found"; exit 2; }

echo "=== Check required topics ==="
grep -qi "layer" "$OUTFILE" || { echo "FAIL: missing Layer explanation"; PARTIAL=2; }
grep -qi "merge\|compose\|composition" "$OUTFILE" || { echo "FAIL: missing composition explanation"; PARTIAL=2; }
grep -qi "context" "$OUTFILE" || { echo "FAIL: missing Context explanation"; PARTIAL=2; }
grep -qi "lifecycle\|scop\|memoiz\|construct" "$OUTFILE" || { echo "FAIL: missing lifecycle explanation"; PARTIAL=2; }

echo "=== Check code example ==="
grep -qi '```' "$OUTFILE" || { echo "FAIL: no code example"; PARTIAL=2; }

echo "PASS"
exit $PARTIAL
