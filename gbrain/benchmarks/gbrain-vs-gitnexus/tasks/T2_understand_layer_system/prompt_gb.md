# Task: Understand Effect's Layer System

Effect-TS uses a `Layer` abstraction for dependency injection. Your task is to understand and explain how the Layer system works.

## Your Task

1. Read the Layer-related source files in `packages/effect/src/`
2. Write a concise explanation (saved to `layer_explanation.md` at the repo root) covering:
   - What is a Layer and how is it constructed?
   - How do layers compose (horizontal `Layer.merge` vs vertical `Layer.provide`)?
   - How does the `Context` system interact with Layers?
   - What's the lifecycle of a layer (construction, memoization, scoping)?
3. Provide a code example demonstrating layer composition

## MANDATORY: Using GBrain Knowledge Graph

**Before writing any explanation**, you MUST use GBrain MCP tools:

1. **search** "Layer" in the codebase to find all Layer-related modules
2. **search** "Layer.provide" and "Layer.merge" to understand composition
3. **traverse_graph** the Layer module to see its dependency graph
4. **get_page** key files to read full source code

Your explanation must reference specific files and function signatures found via gbrain search.
