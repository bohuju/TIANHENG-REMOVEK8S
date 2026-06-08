#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

TESTFILE="packages/effect/test/gen.test.ts"
echo "=== Check test file exists ==="
[ -f "$TESTFILE" ] || { echo "FAIL: test file not created at $TESTFILE"; exit 2; }

echo "=== Check test count ==="
TEST_COUNT=$(grep -cE '\b(it|test|describe)\b' "$TESTFILE" || echo 0)
echo "Test cases found: $TEST_COUNT"
[ "$TEST_COUNT" -ge 5 ] || { echo "FAIL: expected >=5 test cases, got $TEST_COUNT"; PARTIAL=2; }

echo "=== Run the new tests ==="
pnpm --filter effect test -- --testPathPattern gen.test 2>&1 | tail -10 || { echo "FAIL: tests did not pass"; PARTIAL=2; }

exit $PARTIAL
