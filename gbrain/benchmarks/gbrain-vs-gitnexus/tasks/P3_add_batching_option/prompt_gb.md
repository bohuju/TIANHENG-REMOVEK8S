# Task: Add a Batching Config Option

Preact batches state updates in a microtask. Add an option to disable batching.

## Your Task
1. Read src/component.js and src/options.js to understand batching
2. Add a `batchUpdates` boolean option to options.js (default true)
3. In component.js's setState, skip enqueueRender when batchUpdates=false and call render immediately
4. Don't break existing tests

## Expected Outcome
options.js has a new batchUpdates option; setState respects it.

## MANDATORY: Using GBrain Tools
Before editing, use gbrain to:
1. search "setState" and "enqueueRender"
2. get_page src/component.js and src/options.js
3. traverse_graph from setState
