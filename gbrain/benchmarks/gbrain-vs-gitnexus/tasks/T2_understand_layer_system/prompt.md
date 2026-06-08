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

## Constraints

- Output must be saved to `layer_explanation.md` at the EFFECT_TS_REPO root

## Expected Outcome

A markdown file that correctly explains the Layer system with at least the 4 topics above. The code example must be valid TypeScript.
