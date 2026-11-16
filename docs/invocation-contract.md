# Frozen invocation contracts

`execution.invocation` fixes runner argument order and symbolic bindings before
freeze. It is included in the execution hash and complete contract hash, but
not the scientific hash.

```yaml
execution:
  invocation:
    inputs:
      checkpoint: {kind: file}
      features: {kind: directory}
    argv:
      - --checkpoint
      - ${inputs.checkpoint.path}
      - --features
      - ${inputs.features.root}
      - --output-root
      - ${outputs.root}
      - --bundle-root
      - ${bundle.root}
    environment:
      CACHE_MODE: ${environment.CACHE_MODE}
```

Runtime supplies only named transport bindings (`--input checkpoint=/mounted/x`
and `--env CACHE_MODE=read_only`). An undeclared, missing, traversal-containing,
or type-mismatched binding fails closed. Values are passed directly to the
process argument vector; no shell interpolation occurs. The local backend
records the resolved argv and input paths in the stage `invocation.json` before
launching the runner. Environment values are not recorded, only their names.

The symbolic invocation is execution identity. Physical mounted paths are
transport observations and do not change the scientific or execution hashes.
