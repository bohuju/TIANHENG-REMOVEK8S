# Task: Assess Impact of Modifying Effect.Context

The `Context` type in Effect-TS is fundamental — many modules depend on it. Your task is to assess what would break if we add a new required field to `Context.empty`.

## Your Task

1. Find where `Context.empty` (or `Context.Empty`) is defined
2. Identify all downstream consumers that depend on it
3. For each consumer, classify the risk:
   - **HIGH**: directly uses `Context.empty` and would break
   - **MEDIUM**: uses the Context type but not `empty` directly
   - **LOW**: uses Context only through other abstractions
4. Write the impact assessment to `impact_context_empty.md` at the repo root

## Expected Outcome

An impact report listing all affected symbols with risk levels (HIGH/MEDIUM/LOW) and a risk summary: total affected, high count, medium count, low count.
