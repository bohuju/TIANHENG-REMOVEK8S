#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/impact_context_empty.md"

echo "=== Check output file ==="
[ -f "$OUTFILE" ] || { echo "FAIL: output not found"; exit 2; }

echo "=== Check risk levels ==="
grep -qi "HIGH" "$OUTFILE" || { echo "FAIL: no HIGH risk entries"; PARTIAL=2; }
grep -qi "MEDIUM\|LOW" "$OUTFILE" || { echo "FAIL: no MEDIUM/LOW risk entries"; PARTIAL=2; }

echo "=== Check summary ==="
grep -qi "total" "$OUTFILE" || { echo "FAIL: no risk summary with total"; PARTIAL=2; }

echo "=== Check affected count ==="
AFFECTED=$(grep -cE '^\s*[-*]' "$OUTFILE" || echo 0)
echo "Affected symbols: $AFFECTED"
[ "$AFFECTED" -ge 1 ] || { echo "FAIL: no affected symbols listed"; PARTIAL=2; }

echo "=== Check HIGH count ==="
HIGH_COUNT=$(grep -ci "HIGH" "$OUTFILE" || echo 0)
echo "HIGH risk entries: $HIGH_COUNT"

exit $PARTIAL
