# Task: Write Unit Tests for Effect.gen

The `Effect.gen` function is a core Effect-TS API with incomplete test coverage. Your task is to write comprehensive unit tests.

## Your Task

1. Study `Effect.gen` in `packages/effect/src/Effect.ts` to understand its signature and behavior
2. Write tests covering these cases:
   - Basic generator with sequential yields
   - Error handling within gen (try/catch in generator)
   - Nested gen calls (gen inside gen)
   - gen with requirements (Context)
   - gen with interruption signal
3. Save tests to `packages/effect/test/gen.test.ts`

## Expected Outcome

A test file with at least 5 test cases that exercises `Effect.gen` edge cases and passes when run with `pnpm --filter effect test`.
