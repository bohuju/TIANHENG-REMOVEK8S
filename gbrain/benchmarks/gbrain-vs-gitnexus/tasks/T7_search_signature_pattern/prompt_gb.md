# Task: Search for All Functions with Infallible Effect Signatures

Find all Effect-TS functions whose return type includes `Effect<*, never, *>` (infallible effects).

## Your Task

1. Search the codebase for all functions returning `Effect<..., never, ...>`
2. List them in `infallible_effects.md` with function name, file:line, and full signature
3. Include a total count

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_query tool:**

1. **code_query** "Effect<" — search for effect type signatures in code symbols
2. **code_query** "never" --kind Function — filter by function type
3. Use multiple queries with different patterns to ensure comprehensive coverage

The code_query tool searches both full-text and vector embeddings of code chunks, providing better semantic search than grep. Base your answer on code_query results.
