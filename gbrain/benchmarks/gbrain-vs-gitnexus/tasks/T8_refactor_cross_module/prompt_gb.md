# Task: Refactor Cross-Module Dependency in Effect Layer

The `Layer` module may have tight coupling to internal runtime details. Your task is to find and refactor a cross-module dependency to use dependency injection.

## Your Task

1. Find cross-module dependencies in Layer that could use injection
2. Identify all affected downstream consumers
3. Refactor to use dependency injection
4. Update consumers and verify tests pass

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code tools to map the dependency graph before refactoring:**

1. **code_context** for the `Layer` module to find all callers and callees
2. **code_impact** for the dependency you're refactoring to assess downstream impact
3. **code_query** to find all direct invocations of the internal dependency

**Do NOT make changes until you have the full dependency picture from code_context and code_impact.** List all affected consumers in your response before writing any code. The code tools give you the complete dependency graph — use it to ensure your refactor doesn't break anything.
