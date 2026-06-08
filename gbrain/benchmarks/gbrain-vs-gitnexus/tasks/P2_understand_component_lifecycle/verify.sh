#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${PREACT_REPO:-/tmp/preact-bench}"
OUTFILE="$REPO/component_lifecycle.md"
[ -f "$OUTFILE" ] || { echo "FAIL: file not found"; exit 2; }
grep -qi "render" "$OUTFILE" || PARTIAL=2
grep -qi "setState\|state" "$OUTFILE" || PARTIAL=2
grep -qi "diff" "$OUTFILE" || PARTIAL=2
grep -qiE 'src/[a-z/]+\.js:[0-9]+' "$OUTFILE" || PARTIAL=2
exit $PARTIAL
