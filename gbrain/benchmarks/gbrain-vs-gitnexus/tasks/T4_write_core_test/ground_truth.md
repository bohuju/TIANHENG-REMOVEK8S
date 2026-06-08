# Ground Truth: write_core_test

## Expected Test Cases

1. **Sequential yields**: gen that yields succeed(1), succeed(2), returns [1, 2]
2. **Error case**: gen that yields fail("boom"), verifies error propagation
3. **Nested gen**: outer gen yields inner gen, verifies flattening
4. **Requirements**: gen uses Context.Tag, verifies type-safe requirement inference
5. **Interruption**: gen with interruptible region, verifies cleanup runs on interruption

## Key Files
- `packages/effect/src/Effect.ts` (gen implementation)
- `packages/effect/test/Effect/` (existing test patterns to follow)
