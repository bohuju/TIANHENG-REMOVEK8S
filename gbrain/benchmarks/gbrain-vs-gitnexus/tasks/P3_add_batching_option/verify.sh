#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${PREACT_REPO:-/tmp/preact-bench}"
cd "$REPO"
grep -q "batchUpdates" src/options.js || { echo "FAIL: batchUpdates not in options.js"; PARTIAL=2; }
grep -q "batchUpdates" src/component.js || { echo "FAIL: batchUpdates not used in component.js"; PARTIAL=2; }
node -e "const o=require('./src/options.js'); console.assert(typeof o.batchUpdates==='boolean','batchUpdates should be boolean')" 2>/dev/null || PARTIAL=2
exit $PARTIAL
