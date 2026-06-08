#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/call_graph_provideService.md"

echo "=== Check output file ==="
[ -f "$OUTFILE" ] || { echo "FAIL: output file not found"; exit 2; }

echo "=== Check structure ==="
grep -q "## Definition" "$OUTFILE" || { echo "FAIL: missing Definition section"; PARTIAL=2; }
grep -q "## Callers" "$OUTFILE" || { echo "FAIL: missing Callers section"; PARTIAL=2; }
grep -q "## Callees" "$OUTFILE" || { echo "FAIL: missing Callees section"; PARTIAL=2; }

echo "=== Check file:line references ==="
FILE_LINE_COUNT=$(grep -cE '[a-zA-Z0-9_/]+\.[a-z]+:[0-9]+' "$OUTFILE" || echo 0)
echo "File:line references: $FILE_LINE_COUNT"
[ "$FILE_LINE_COUNT" -ge 1 ] || { echo "FAIL: no file:line references"; PARTIAL=2; }

echo "=== Check mentions provideService ==="
grep -qi "provideService" "$OUTFILE" || { echo "FAIL: does not mention provideService"; PARTIAL=2; }

echo "=== Check caller count ==="
CALLER_LINES=$(sed -n '/## Callers/,/## Callees/p' "$OUTFILE" | grep -cE '^\s*-' || echo 0)
echo "Callers found: $CALLER_LINES"
[ "$CALLER_LINES" -gt 0 ] || { echo "FAIL: no callers listed"; PARTIAL=2; }

exit $PARTIAL
