# Ground Truth: find_callers_callees

## Expected Structure

The output must contain:
1. **Definition section** with exact file path and line number
2. **Callers section** listing each caller with file path and line
3. **Callees section** listing each callee with file path and line
4. Each entry must have the format: `Name (path:line)`

## Acceptable Results

- If `code_context` is used (Group C), results should match the GitNexus index exactly
- If manual grep is used (Groups A/B), results should be at least 80% complete
- At minimum: must find the definition location correctly

## Key Symbol
- `provideService` is in `packages/effect/src/Effect.ts`
