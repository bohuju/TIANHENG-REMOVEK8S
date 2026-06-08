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

## MANDATORY: Using GBrain Knowledge Graph

**Before making any code changes**, you MUST use GBrain MCP tools to investigate:

1. **search** "Effect.gen" or "gen" — find where `gen` is defined and how its type is constructed
2. **search** "Generator" — find the generator type helpers that `gen` depends on
3. **traverse_graph** the Effect module at depth 2 to understand the type dependency chain
4. **get_page** the relevant file to read the full type definition

Use these tools to trace the type inference chain BEFORE proposing a fix. Your investigation notes should reference specific files and line numbers found via gbrain.
