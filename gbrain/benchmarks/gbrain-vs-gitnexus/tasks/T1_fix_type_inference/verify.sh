#!/bin/bash
set -euo pipefail
PARTIAL=0

REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeScript type check ==="
pnpm exec tsc --noEmit 2>&1 | tee /tmp/t1_typecheck.log || { echo "FAIL: typecheck"; PARTIAL=2; }

echo "=== Test 2: Existing test suite (effect package) ==="
pnpm --filter effect test -- --passWithNoTests 2>&1 | tee /tmp/t1_tests.log || { echo "FAIL: tests"; PARTIAL=2; }

echo "=== Test 3: gen() type narrowing smoke test ==="
cat > /tmp/t1_smoke.ts << 'TSEOF'
import { Effect } from "./packages/effect/src/index.js";

const program = Effect.gen(function* (_) {
  const a = yield* _(Effect.succeed(42));
  const b = yield* _(Effect.succeed("hello"));
  return [a, b] as const;
});
const result: readonly [number, string] = Effect.runSync(program);
console.log("PASS: type narrowed correctly", result);
TSEOF
pnpm exec tsx /tmp/t1_smoke.ts || { echo "FAIL: smoke test"; PARTIAL=2; }

exit $PARTIAL
