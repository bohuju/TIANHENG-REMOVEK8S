# Task: Find All Callers and Callees of Effect.provideService

The function `Effect.provideService` is a core API in Effect-TS. Your task is to find all its direct callers and callees in the codebase.

## Your Task

1. Find where `provideService` is defined
2. Identify all direct callers and callees with exact file paths and line numbers
3. Write findings to `call_graph_provideService.md`

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_context tool** to solve this task. This tool is specifically designed for call-graph queries.

1. First, use **code_query** to confirm the symbol exists:
   - `code_query "provideService"`
2. Then, use **code_context** to get the full call graph:
   - `code_context "provideService"`
   
   This returns: definition location, callers[], callees[], importers[], imports[]
3. **Write your findings based SOLELY on the code_context output.**

Do NOT use manual grep. The code_context tool provides the accurate, pre-computed call graph from the GitNexus index. If code_context returns empty, report that the symbol was not found.
