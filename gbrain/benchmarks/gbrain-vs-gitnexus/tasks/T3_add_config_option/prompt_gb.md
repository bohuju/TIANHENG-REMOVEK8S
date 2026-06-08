# Task: Add a Configuration Option to Effect Runtime

Effect-TS's `ManagedRuntime` accepts a configuration for the runtime behavior. Your task is to add a `maxConcurrency` option that limits the maximum number of concurrent fibers.

## Your Task

1. Find `ManagedRuntime` in `packages/effect/src/ManagedRuntime.ts`
2. Add a `maxConcurrency: number` option (default: `Infinity`) to the runtime configuration type
3. Wire the option through so that `Runtime.runPromise` respects it by using a semaphore
4. Add a test in `packages/effect/test/` demonstrating the concurrency limit

## Constraints

- Default behavior (no limit) must remain unchanged
- The existing test suite must pass
- The fix should be minimal

## MANDATORY: Using GBrain Knowledge Graph

**Before modifying any code**, use gbrain MCP tools:

1. **search** "ManagedRuntime" to find the configuration type and runtime implementation
2. **search** "Fiber" and "concurrency" to understand fiber scheduling
3. **get_page** the ManagedRuntime module to read the full implementation
4. **traverse_graph** from ManagedRuntime to find downstream consumers

Only propose changes after you've traced the full dependency chain via gbrain.
