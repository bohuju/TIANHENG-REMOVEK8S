# Ground Truth: add_config_option

## Correct Implementation

1. Add `maxConcurrency: number` to `ManagedRuntime.Options` type (default `Infinity`)
2. Create a `Semaphore` from `Effect.makeSemaphore(maxConcurrency)` during runtime initialization
3. Wrap fiber execution with `semaphore.withPermit(1)(effect)` before `runPromise`
4. Add test: spawn 5 concurrent effects with maxConcurrency=2, verify at most 2 run concurrently

## Key Files
- `packages/effect/src/ManagedRuntime.ts`
- `packages/effect/src/Effect.ts` (Semaphore/Fiber types)
