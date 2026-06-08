# Task: Assess Impact of Modifying Effect.Context

The `Context` type in Effect-TS is fundamental. Your task is to assess what would break if we add a new required field to `Context.empty`.

## Your Task

1. Identify all downstream consumers of `Context.empty`
2. Classify each by risk level (HIGH/MEDIUM/LOW)
3. Write the impact assessment to `impact_context_empty.md`

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_impact tool:**

1. **code_query** "Context.empty" to find the symbol
2. **code_impact** "Context.empty" --direction downstream --depth 5
   
   This returns the impact chain with risk levels pre-computed by the dependency graph analysis.
3. Base your impact report on the code_impact output. Use the tool's built-in HIGH/MEDIUM/LOW risk classification.

Do NOT manually grep. The code_impact tool analyzes the full dependency graph and assigns risk levels based on graph depth.
