# Ground Truth: add_batching_option
1. Add `export let batchUpdates = true` to options.js
2. In component.js setState, if !options.batchUpdates, call renderComponent directly instead of enqueueRender
## Key Files: src/options.js, src/component.js
