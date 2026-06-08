# Task: Write Unit Tests for Effect.gen

The `Effect.gen` function is a core Effect-TS API with incomplete test coverage. Your task is to write comprehensive unit tests.

## Your Task

1. Study `Effect.gen` in `packages/effect/src/Effect.ts` to understand its signature and behavior
2. Write tests covering these cases:
   - Basic generator with sequential yields
   - Error handling within gen
   - Nested gen calls
   - gen with requirements (Context)
   - gen with interruption signal
3. Save tests to `packages/effect/test/gen.test.ts`

## MANDATORY: Using GBrain Knowledge Graph

**Before writing tests**, use gbrain MCP tools to understand the code:

1. **search** "Effect.gen" to find the implementation and existing tests
2. **search** "yield" and "Generator" to find related type helpers
3. **get_page** the Effect module to read the gen function signature
4. **traverse_graph** from gen to understand what other modules it depends on

Your tests should cover the edge cases you discover through gbrain exploration.
