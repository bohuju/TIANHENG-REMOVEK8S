# Task: Refactor Cross-Module Dependency in Effect Layer

The `Layer` module may have tight coupling to internal runtime details. Your task is to find and refactor a cross-module dependency to use dependency injection.

## Your Task

1. Find where `Layer` directly depends on an internal runtime implementation (e.g., calling `Runtime.runSync` or accessing `defaultRuntime`)
2. Identify all downstream consumers that would be affected by changing this dependency
3. Refactor to inject the runtime dependency instead of calling it directly
4. Update all affected consumers so they compile correctly
5. Ensure all existing tests pass

## Constraints

- Public API of Layer must remain compatible
- Runtime behavior must be identical
- The fix should be minimal — change only what's necessary

## Expected Outcome

A refactored Layer module with injected runtime dependency, updated consumers, and all tests passing.
