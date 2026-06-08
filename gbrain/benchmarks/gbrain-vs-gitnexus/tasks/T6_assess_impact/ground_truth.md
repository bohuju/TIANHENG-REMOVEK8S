# Ground Truth: assess_impact

## Expected Format
- List of affected symbols grouped by risk level (HIGH/MEDIUM/LOW)
- Each symbol must include file path and line
- Risk summary at the end: { total: N, high: N, medium: N, low: N }
- Each symbol should include the dependency path (how it connects to Context.empty)

## Key Files
- `packages/effect/src/Context.ts`
- `packages/effect/src/Layer.ts`
- `packages/effect/src/ManagedRuntime.ts`
