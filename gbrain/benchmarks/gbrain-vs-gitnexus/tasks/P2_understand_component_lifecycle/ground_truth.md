# Ground Truth: understand_component_lifecycle

## Key Concepts
1. Component.render() produces VNodes, passed to diff()
2. setState enqueues state, triggers enqueueRender -> diff
3. Lifecycle: componentWillMount -> render -> componentDidMount; componentWillUpdate -> render -> componentDidUpdate
## Key Files
- src/component.js
- src/render.js
- src/diff/index.js
