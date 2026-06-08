# Task: Search for All Functions with Infallible Effect Signatures

Find all Effect-TS functions whose return type includes `Effect<*, never, *>` (i.e., infallible effects that never error).

## Your Task

1. Search the codebase for all function declarations that return `Effect<..., never, ...>`
2. List them in `infallible_effects.md` at the repo root with:
   - Function name
   - File path and line number
   - Full return type signature
3. Include a total count at the end

## Expected Outcome

A complete list of infallible Effect functions with exact locations and type signatures. Include at least 3 functions with accurate file:line references.
