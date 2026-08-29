# Experiment Contract Agent Skill

This is the canonical skill for operating scientific experiments through Expcon.
It can be installed or symlinked into the global skill directory of a coding agent.

## Purpose

> Operate experiments correctly, not autonomously redesign them.

## Prerequisites

- Expcon installed globally: `uv tool install --editable /path/to/expcon`
- `expcon --version` works
- The project has an `experiments/` directory with experiment contracts

## Skill Rules

### 1. Locate and Read the Contract

Before executing anything, always locate and read the experiment contract:

```bash
expcon inspect <experiment> --json
```

Determine whether the experiment is `DRAFT` or `FROZEN`.

### 2. Validate Before Operating

```bash
expcon validate <experiment>
```

Never proceed if validation fails. Validation is deterministic — let Expcon
decide compliance, not the agent.

### 3. Understand the State Machine

```
DRAFT → VALIDATED → FROZEN → READY → SUBMITTED → RUNNING
  → RESULTS_AVAILABLE → EVIDENCE_VERIFIED → ADJUDICATED → CLOSED
```

Failure states: `BLOCKED`, `FAILED_EXECUTION`, `INVALID_RUN`,
`CONTRACT_VIOLATION`, `EVIDENCE_INVALID`

State transitions are validated by Expcon. Do not bypass them.

### 4. Before Freeze: Creative Mode

Before freeze, the agent may:
- Inspect the experiment
- Repair implementation code (non-scientific)
- Write tests
- Propose configuration changes
- Run smoke tests

Scientific parameters may change freely before freeze.

### 5. After Freeze: Deterministic Mode

After freeze, scientific parameters are immutable. The agent may:
- Validate the frozen contract
- Submit to an allowed backend
- Monitor execution
- Fetch evidence
- Verify evidence integrity
- Analyse results
- Adjudicate conclusions
- Report findings

The agent may **NOT**:
- Change scientific config
- Change datasets, split, model, evaluation, acceptance criteria
- Silently repair a frozen experiment
- Silently replace datasets, model revisions, prompts, metrics, seeds, or config

### 6. Freeze the Experiment

```bash
expcon freeze <experiment>
```

Freeze:
1. Validates the contract
2. Resolves all references
3. Verifies manifests
4. Verifies dependency lock
5. Inspects source state
6. Rejects unresolved scientific aliases (`latest`, `main`, `HEAD`)
7. Calculates deterministic identities
8. Produces `contract.lock.json`
9. Marks the experiment FROZEN

### 7. Check for Divergence

```bash
expcon diff <experiment>
```

After freeze, always run diff to detect scientifically meaningful divergence.
If divergence is detected, do not execute as the current version. Create a
successor experiment version with an explicit scientific deviation.

### 8. Bundle and Verify

```bash
expcon bundle <experiment>
expcon verify-bundle <bundle>
```

The bundle is content-addressed. Its identity is derived from:
- contract hash
- source hash
- dependency hash
- dataset hashes
- runner hash
- config hash

Any protected modification fails verification.

### 9. Submit to an Allowed Backend

```bash
expcon run <experiment> --backend local
expcon run <experiment> --backend kaggle --kernel <kernel>
```

- Never submit to a backend not in `allowed_backends`
- Backend selection reflects "which environment satisfies the experiment?"
- Do not assume Kaggle means GPU — `accelerator: none` is valid
- Do not store Kaggle credentials

### 10. Retrieve and Verify Evidence

```bash
expcon fetch <run_id>
expcon verify <run_id>
```

Verification detects:
- Modified output
- Changed metric
- Changed predictions
- Missing required artifact
- Wrong contract
- Wrong bundle ID
- Wrong dataset manifest
- Broken artifact provenance

Scientific interpretation must not proceed on invalid evidence.

### 11. Adjudicate

```bash
expcon adjudicate <run_id>
```

Three independent statuses:
- `execution_status`: COMPLETED | FAILED | BLOCKED
- `contract_status`: COMPLIANT | VIOLATION
- `scientific_verdict`: SUPPORTED | NOT_SUPPORTED | INCONCLUSIVE

A negative result is not an execution failure.

### 12. Use tmux for Operational Continuity

```bash
expcon workspace <experiment>
expcon attach <experiment>
```

tmux provides operational continuity. Expcon provides scientific continuity.
If the tmux session disappears, Expcon reconstructs state from persistent
run records.

### 13. Handle Failures Correctly

When an experiment fails:

```
current experiment
      ↓
INVALID / FAILED / BLOCKED
      ↓
diagnosis
      ↓
proposed successor experiment
```

Never silently repair a frozen experiment. Instead, propose a new version
with an explicit scientific deviation.

### 14. Security

- Never expose credentials or secrets
- Never store KAGGLE credentials, API tokens, or SSH secrets
- Treat bundles and remote outputs as untrusted
- Use `expcon` commands over bespoke shell workflows

### 15. Machine-Readable Output

All commands support `--json`:

```bash
expcon inspect <experiment> --json
expcon status <run_id> --json
expcon events <run_id> --json
expcon ps --json
```

Use this for programmatic agent workflows.

### 16. Use Exit Codes

- Exit 0: success
- Exit 1: failure (validation, verification, etc.)
- Exit 1: divergence detected (diff command)

Check exit codes before proceeding.

### 17. Event Following

```bash
expcon events <run_id> --follow
```

Follow events in real-time. Events are append-only and persist across
session restarts.

### 18. Artifact Provenance

```bash
expcon artifacts <experiment-or-run> --json
```

Every artifact has:
- artifact_id
- artifact_type
- hash
- experiment_id
- run_id
- parent inputs
- producer stage
- verification state

Artifacts are traceable back to: scientific claim → experiment → run → stage → artifact.

## Workflow Summary

```bash
# 1. Inspect
expcon inspect experiments/E13/v002 --json

# 2. Validate
expcon validate experiments/E13/v002

# 3. Freeze
expcon freeze experiments/E13/v002

# 4. Bundle
expcon bundle experiments/E13/v002

# 5. Verify bundle
expcon verify-bundle experiments/E13/v002/bundle

# 6. Run
expcon run experiments/E13/v002 --backend kaggle --kernel smoke

# 7. Check status
expcon status <run_id>

# 8. Fetch evidence
expcon fetch <run_id>

# 9. Verify evidence
expcon verify <run_id>

# 10. Adjudicate
expcon adjudicate <run_id>
```

## Key Reminders

1. Agents decide what operation is needed. Expcon determines how.
2. AI creativity before freeze. Deterministic control after freeze.
3. Scientific state survives agent/session failure.
4. Remote compute executes. It does not define the experiment.
5. Artifacts without provenance are incomplete.
6. Execution success != scientific success.
7. Post-hoc insight may create the next experiment. It may not rewrite the previous.
8. tmux provides operational continuity. Expcon provides scientific continuity.
9. Use existing infrastructure. Do not become another ML platform.
