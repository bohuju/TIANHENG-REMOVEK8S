#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeScript type check ==="
pnpm exec tsc --noEmit --project packages/effect/tsconfig.json 2>&1 | tail -5 || { echo "FAIL: typecheck"; PARTIAL=2; }

echo "=== Test 2: Layer tests pass ==="
pnpm --filter effect test -- --testPathPattern Layer 2>&1 | tail -10 || { echo "FAIL: Layer tests"; PARTIAL=2; }

echo "=== Test 3: Check for remaining direct runtime calls in Layer ==="
if grep -rn "runSync\|defaultRuntime" packages/effect/src/Layer.ts 2>/dev/null; then
  echo "NOTE: Direct runtime references found — agent may have chosen a different dependency to refactor"
fi

echo "=== Test 4: Overall test suite ==="
pnpm --filter effect test 2>&1 | tail -5 || { echo "FAIL: overall tests"; PARTIAL=2; }

exit $PARTIAL
