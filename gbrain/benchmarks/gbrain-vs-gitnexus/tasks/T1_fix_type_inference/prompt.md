# Task: Fix Effect Type Inference Bug

In this Effect-TS codebase, a utility function `Effect.gen` has a TypeScript type inference issue: when used with a specific generator pattern, the inferred return type is too wide (`Effect<never, Error, unknown>` instead of the actual resolved type).

## Your Task

1. Investigate how `Effect.gen` infers its return type by reading `packages/effect/src/Effect.ts` and related type definitions
2. Locate the type-level bug that causes the overly-wide inference
3. Fix the type definition so the return type is correctly narrowed
4. Verify the fix by running the project's TypeScript type check

## Constraints

- Do not change runtime behavior — only fix types
- The existing test suite must pass (`pnpm test`)
- The fix should be minimal — a few lines in the type definitions

## Expected Outcome

After the fix, `Effect.gen` should infer the correct narrow return type, and `pnpm typecheck` should pass without errors.
