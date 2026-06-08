#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/infallible_effects.md"

echo "=== Check output file ==="
[ -f "$OUTFILE" ] || { echo "FAIL: output not found"; exit 2; }

echo "=== Check Effect references ==="
grep -qi "Effect" "$OUTFILE" || { echo "FAIL: no Effect type references"; PARTIAL=2; }

echo "=== Check never references ==="
grep -qi "never" "$OUTFILE" || { echo "FAIL: no 'never' type references"; PARTIAL=2; }

echo "=== Check function count ==="
FUNC_COUNT=$(grep -cE '^\s*[-*]' "$OUTFILE" || echo 0)
echo "Functions found: $FUNC_COUNT"
[ "$FUNC_COUNT" -ge 3 ] || { echo "FAIL: expected >=3 functions, got $FUNC_COUNT"; PARTIAL=2; }

echo "=== Check file:line references ==="
WITH_LOC=$(grep -cE '[a-zA-Z0-9_/]+\.[a-z]+:[0-9]+' "$OUTFILE" || echo 0)
echo "Entries with file:line: $WITH_LOC"
[ "$WITH_LOC" -ge 3 ] || { echo "FAIL: fewer than 3 entries have file:line references"; PARTIAL=2; }

exit $PARTIAL
