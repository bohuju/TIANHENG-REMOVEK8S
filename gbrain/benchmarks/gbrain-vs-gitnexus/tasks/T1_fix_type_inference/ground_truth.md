# Ground Truth: fix_type_inference

## Root Cause

The `Effect.gen` function uses a type helper that doesn't properly narrow the `Requirements` type parameter when the generator yields effects. The issue is in the `GenGenerator` type which maps `Generator<T, R, E>` but loses type information at the yield boundary.

## Correct Fix

In `packages/effect/src/Effect.ts`, locate the type definition for `GenGenerator` and ensure the `A` (success type) parameter properly propagates through the yield chain.

## Key Files
- `packages/effect/src/Effect.ts`: `gen` function + `GenGenerator` type
- `packages/effect/src/Types.ts` (if exists): core type helpers

## Verification
- `pnpm typecheck` must pass
- A simple test with `Effect.gen` should produce a correctly narrowed type
