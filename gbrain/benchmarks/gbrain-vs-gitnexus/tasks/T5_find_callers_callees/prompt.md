# Task: Find All Callers and Callees of Effect.provideService

The function `Effect.provideService` is a core API in Effect-TS. Your task is to find all its direct callers and callees in the codebase.

## Your Task

1. Find where `provideService` is defined in the Effect-TS source
2. Trace the code to identify:
   - All functions/methods that directly call `provideService` (callers)
   - All functions/methods that `provideService` directly calls (callees)
3. Write your findings to `call_graph_provideService.md` at the repo root in this format:
   ```
   # Call Graph: Effect.provideService

   ## Definition
   File: path/to/file, Line: N

   ## Callers (N total)
   - FuncName (path/to/file:line)
   - ...

   ## Callees (N total)
   - FuncName (path/to/file:line)
   - ...
   ```

## Constraints

- Each caller/callee must include the exact file path and line number
- You may search the codebase using any method available

## Expected Outcome

A complete call graph file with accurate file paths and line numbers for all direct callers and callees of `provideService`.
