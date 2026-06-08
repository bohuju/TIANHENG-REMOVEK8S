#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${PREACT_REPO:-/tmp/preact-bench}"
OUTFILE="$REPO/render_callers.md"
[ -f "$OUTFILE" ] || { echo "FAIL: file not found"; exit 2; }
grep -qi "render" "$OUTFILE" || PARTIAL=2
grep -qiE '[a-z/]+\.js:[0-9]+' "$OUTFILE" || PARTIAL=2
COUNT=$(grep -cE '^\s*-' "$OUTFILE" || echo 0)
[ "$COUNT" -ge 1 ] || PARTIAL=2
exit $PARTIAL
