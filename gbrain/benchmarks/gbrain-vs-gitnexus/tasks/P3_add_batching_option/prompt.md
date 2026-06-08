# Task: Add batchUpdates Option to Preact

## Your Task
Edit 2 files to add a `batchUpdates` option:

1. **src/options.js** — add `export let batchUpdates = true;`
2. **src/component.js** — in setState(), check options.batchUpdates:
   - if true: call enqueueRender(this) (existing behavior)
   - if false: call renderComponent(this) immediately

Do NOT change any other files. Keep existing behavior when batchUpdates is true.
