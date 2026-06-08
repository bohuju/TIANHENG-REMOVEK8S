#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${PREACT_REPO:-/tmp/preact-bench}"
OUTFILE="$REPO/createElement_usage.md"
[ -f "$OUTFILE" ] || { echo "FAIL: file not found"; exit 2; }
grep -qi "createElement\|h(" "$OUTFILE" || PARTIAL=2
COUNT=$(grep -cE '^\s*-' "$OUTFILE" || echo 0)
[ "$COUNT" -ge 2 ] || PARTIAL=2
exit $PARTIAL
