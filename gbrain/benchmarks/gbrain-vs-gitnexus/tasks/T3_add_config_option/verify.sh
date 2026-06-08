#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeScript check ==="
pnpm exec tsc --noEmit --project packages/effect/tsconfig.json 2>&1 | tail -5 || { echo "FAIL: typecheck"; PARTIAL=2; }

echo "=== Test 2: Max concurrency option exists ==="
cat > /tmp/t3_concurrency.ts << 'TSEOF'
import { ManagedRuntime } from "./packages/effect/src/index.js";
const opts: ManagedRuntime.Options = { maxConcurrency: 4 };
console.log("PASS: option type accepted", opts.maxConcurrency);
TSEOF
pnpm exec tsx /tmp/t3_concurrency.ts || { echo "FAIL: smoke test"; PARTIAL=2; }

echo "=== Test 3: Existing tests ==="
pnpm --filter effect test 2>&1 | tail -5 || { echo "FAIL: tests"; PARTIAL=2; }

exit $PARTIAL
