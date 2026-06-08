# Ground Truth: refactor_cross_module

## Correct Approach

1. Identify the tightly-coupled dependency in the Layer module
2. Create or use an existing interface/type parameter for the dependency
3. Pass the dependency as a parameter rather than referencing a global/default
4. Update all callers to pass their dependency explicitly
5. Verify no direct call to the internal runtime remains in Layer source

## Key Files
- `packages/effect/src/Layer.ts`
- `packages/effect/src/ManagedRuntime.ts`
- `packages/effect/src/Effect.ts`

## Verification
- No direct runtime calls remain in Layer source
- All existing Layer tests pass
- TypeScript typecheck passes
