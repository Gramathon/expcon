# Expcon MCP for Pi + sol-pi

For independent wheel/Pi installation, see [the installation guide](INSTALLATION.md).
The standalone adapter supports EXPCON_MCP_EXECUTABLE and discovers research
workspace environments or PATH without source-path injection.

For development, install the controller in a separate environment from the scientific worker:

```bash
uv venv --python 3.12 .venv-mcp
uv pip install --python .venv-mcp/bin/python --editable '.[mcp]' --group dev
```

These commands preserve the worker's `.venv` and experiment dependency lock.
Start `.venv-mcp/bin/expcon-mcp --stdio --workspace /absolute/research` for a local MCP client,
or omit `--stdio` for loopback Streamable HTTP on port 7680, endpoint `/mcp`.
The official MCP SDK owns protocol handling and Origin/Host validation.

Pi loads `.pi/mcp.json` from the project. Its `command` must be the absolute path
to the controller executable; `args` must include `--stdio` and the absolute
workspace path. The project extension also discovers `.venv-mcp/bin/expcon-mcp`,
then `.venv/bin/expcon-mcp`, then `expcon-mcp` on PATH. An entry in `mcp.json`
takes precedence over extension registration. After changing configuration,
restart Pi or use `/reload`, then check `/mcp` for the `expcon` connection.
An `ENOENT` error means the configured executable is missing; install the
controller and check the `command` path.

This release uses a trusted-host model: agent, controller and workers may share
one OS identity. Integrity checks detect drift; they do not sandbox scientific
Python or protect records from a hostile local process. No independent isolation
attestation is claimed. Do not expose this unauthenticated service off-host.

## Workflow

Use `experiment_init` to create a contract or write an editable draft with Pi's
ordinary tools. New drafts use explicit `expcon-bundle-v3`. Call:

1. `experiment_inspect`, `experiment_validate`, `experiment_preflight`.
2. `experiment_freeze(experiment, expected_candidate_id)` using the preflight ID.
3. `experiment_diff`, `experiment_bundle`, `bundle_verify`.
4. `experiment_run(experiment, idempotency_key, backend, kernel?, inputs?)`.
5. Poll `experiment_status(run_id)` and read `experiment_events`.
6. `experiment_fetch`, `experiment_verify`, `experiment_adjudicate`.
7. `experiment_result`, `experiment_artifacts`, `artifact_read`.

Paths are workspace-relative. Preflight optionally accepts `inputs` and returns
deterministically observed checksums for draft authoring. Declare these hashes
in invocation inputs before freeze. Runtime bindings locate matching bytes.
Freeze rejects missing acceptance rules and scientific input identities.
`experiment_submit` is a deprecated admission-only alias for importing a draft;
it returns FROZEN and never creates a run.

CLI and MCP share the Python service for execution, status reconciliation,
collection, verification and adjudication. MCP errors are SDK tool errors;
lifecycle failures also retain their existing structured status/reason reports.
Lists use offsets with limits 1–100; text reads are bounded to 64 KiB.

## Continuity

Run requests are persisted before launching a detached Python worker. Retry a
request with the same idempotency key; conflicting reuse fails. A dropped client
does not cancel execution. Workers retain their state under `.expcon/requests`.
An uncertain submission must be reconciled, never automatically resubmitted.
Fetch retries return the retained evidence version. Verification and adjudication
reports are versioned; run metadata selects the applicable reports.

`research_history` returns paginated proposals, runs and decisions. Recording
uses a locked atomic append; corrupt history raises an error rather than resetting.
Interpretations never override deterministic scientific verdicts.

## Kaggle

New generic Kaggle workflows require bundle v3 and `execution.kaggle`:

```yaml
execution:
  allowed_backends: [kaggle]
  kaggle:
    metadata:
      id: owner/private-test-kernel
      title: Expcon controlled experiment
      is_private: true
      enable_gpu: false
      enable_internet: false
    inputs: {}  # symbolic invocation name -> mounted absolute path
```

Declare ordinary Python or notebook stages, a dependency lock, and explicit
invocations. The identity-bound bootstrap and its invocation helpers travel in
the bundle. Python stages use declared argv; notebook kernels receive
EXPCON_BUNDLE_ROOT and EXPCON_OUTPUT_ROOT. Remote inputs are hash-checked before
stages start; missing dependencies block instead of being installed implicitly.
Outputs and the remote environment record are downloaded from the bound kernel
version. Install `expcon[kaggle]` under Python >=3.11 for the modern provider API.
Kaggle CLI >=2.2.5 is required for the version-qualified CLI transport.
No latest-only output or placeholder evidence is accepted.

Offline tests are required. Live Kaggle certification additionally requires
configured credentials and private test kernels. No live certification is implied
by fake transport tests. Tinker and Colab retain their existing limitations.
