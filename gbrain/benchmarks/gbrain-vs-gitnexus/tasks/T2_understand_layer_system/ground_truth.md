# Ground Truth: understand_layer_system

## Key Concepts Agent Must Cover

1. **Layer construction**: `Layer.succeed(context)`, `Layer.effect(effect)`, `Layer.scoped(effect)`, `Layer.function(tag, fn)`
2. **Composition**: `Layer.merge` combines two layers; `Layer.provide` feeds one layer into another's requirements
3. **Context integration**: Each layer provides a `Context<Tag, Service>`; `Layer.provideMerge` resolves the dependency graph
4. **Lifecycle**: Layers are memoized (constructed once), scoped resources are acquired/released per scope

## Key Files
- `packages/effect/src/Layer.ts`
- `packages/effect/src/Context.ts`
- `packages/effect/src/ManagedRuntime.ts`
