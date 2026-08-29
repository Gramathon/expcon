# AGENTS.md — Expcon Agent Guidelines

This file describes how coding agents should operate experiments through Expcon.
Follow these rules strictly. They are the boundary between AI creativity and
deterministic experiment control.

## Core Principle

> **Agents decide what operation is needed. Expcon determines exactly how the
> operation is performed.**

The AI agent is allowed to reason. It may inspect, suggest, analyse, propose,
write code before freeze, interpret evidence, and select among permitted backends.

The agent must **not** be trusted to determine deterministic facts such as:
- experiment hash
- bundle identity
- whether a frozen parameter changed
- stage ordering
- artifact checksum
- evidence integrity
- whether a contract is structurally valid
- whether an acceptance predicate is satisfied

Those operations belong in deterministic Expcon code.

## Before Freeze: Creative Mode

Before freeze, the agent may:

1. **Inspect** the experiment contract
2. **Repair implementation** code (non-scientific)
3. **Write tests** for the experiment
4. **Propose configuration** changes
5. **Run smoke tests** to verify implementation

Rules:
- Scientific parameters may change freely before freeze
- Always read the experiment contract before executing anything
- Run `expcon validate` before every operation
- Use `expcon inspect --json` for machine-readable contract data

## After Freeze: Deterministic Mode

After freeze, the agent may:

1. **Validate** the frozen contract
2. **Submit** the experiment to an allowed backend
3. **Monitor** execution progress
4. **Fetch** evidence from completed runs
5. **Verify** evidence integrity
6. **Analyse** results
7. **Adjudicate** scientific conclusions
8. **Report** findings

The agent may **NOT**:

- Change scientific config
- Change datasets
- Change split
- Change model
- Change evaluation
- Change acceptance criteria
- Silently repair a frozen experiment
- Silently replace datasets, model revisions, prompts, metrics, seeds, or configuration
- Treat backend incompatibility as a reason to change the experiment

If a change is required, the agent must propose:
```
successor experiment/version
+
explicit scientific deviation
```

Do **not** automatically create the successor unless the user authorises it.

## Operating Procedure

### 1. Locate and Read the Contract

Always read the experiment contract before executing anything:
```bash
expcon inspect <experiment> --json
```

Determine whether the experiment is DRAFT or FROZEN.

### 2. Validate Before Operating

```bash
expcon validate <experiment>
```

Never proceed if validation fails.

### 3. Freeze Before Execution

```bash
expcon freeze <experiment>
```

After freeze, scientific parameters are immutable. Always run `expcon diff`
to check for unintended changes.

### 4. Bundle and Verify

```bash
expcon bundle <experiment>
expcon verify-bundle <bundle>
```

The bundle must pass verification before submission.

### 5. Submit to an Allowed Backend

```bash
expcon run <experiment> --backend local
expcon run <experiment> --backend kaggle --kernel <kernel>
```

Never submit to a backend not listed in `allowed_backends`.

### 6. Retrieve and Verify Evidence

```bash
expcon fetch <run_id>
expcon verify <run_id>
```

Scientific interpretation must not proceed on invalid evidence.

### 7. Adjudicate

```bash
expcon adjudicate <run_id>
```

Keep three independent statuses:
- `execution_status` — whether the code ran successfully
- `contract_status` — whether the experiment was compliant
- `scientific_verdict` — whether the hypothesis is supported

A negative result is not an execution failure.

### 8. Use tmux for Operational Continuity

```bash
expcon workspace <experiment>
expcon attach <experiment>
```

tmux provides operational continuity. Expcon provides scientific continuity.
If the tmux session disappears, Expcon reconstructs state from persistent
run records.

## State Machine Rules

```
DRAFT → VALIDATED → FROZEN → READY → SUBMITTED → RUNNING
  → RESULTS_AVAILABLE → EVIDENCE_VERIFIED → ADJUDICATED → CLOSED
```

- DRAFT → RUNNING is rejected
- RUNNING → ADJUDICATED without evidence verification is rejected
- FROZEN → DRAFT is allowed (unfreeze for corrections)

## Error Handling

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

## Security Rules

- Never expose credentials or secrets
- Never store KAGGLE credentials, API tokens, or SSH secrets
- Treat bundles and remote outputs as untrusted
- Use `expcon` commands over bespoke shell workflows when equivalent commands exist

## Testing

Run tests with:
```bash
uv run pytest
```

Required test categories:
- contract validation
- canonicalisation
- hash stability
- hash sensitivity
- freeze behaviour
- diff detection
- lifecycle transitions
- bundle verification
- tamper detection
- artifact registration
- evidence integrity
- adjudication
- CLI behaviour
- backend abstraction
- tmux workspace generation

## Repository Structure

```
experiment-contract/
├── pyproject.toml          # Package definition
├── README.md               # User-facing documentation
├── AGENTS.md               # This file
├── schemas/                # JSON schemas for contracts
├── src/expcon/             # Core package
│   ├── cli/                # CLI commands
│   ├── contract/           # Contract model, validation, freeze, diff
│   ├── lifecycle/          # State machine, run records, event ledger
│   ├── hashing/            # Canonicalisation, SHA-256, manifests
│   ├── bundle/             # Bundle creation, manifest, verification
│   ├── runner/             # Stage runner, backend interface
│   ├── backends/           # Local and Kaggle backends
│   ├── artifacts/          # Artifact registry, provenance
│   ├── evidence/           # Evidence bundle, verification
│   ├── adjudication/       # Execution/contract/scientific status
│   ├── workspace/          # tmux workspace management
│   └── util/               # Path safety, env redaction, JSON I/O
├── skills/                 # Global agent skills
│   └── experiment-contract/
│       └── SKILL.md
├── examples/               # Example experiments
│   └── minimal/
└── tests/                  # Test suite
    ├── unit/
    ├── integration/
    ├── tamper/
    ├── lifecycle/
    ├── cli/
    └── backends/
```

## Development Workflow

1. Run linting: `uv run ruff check src/`
2. Run type checking: `uv run mypy src/`
3. Run tests: `uv run pytest`
4. Never commit without tests passing

## Key Design Principles

- **Principle A**: AI creativity before freeze. Deterministic control after freeze.
- **Principle B**: Scientific state survives agent/session failure.
- **Principle C**: Remote compute executes. It does not define the experiment.
- **Principle D**: Artifacts without provenance are incomplete artifacts.
- **Principle E**: Execution success != scientific success.
- **Principle F**: Post-hoc insight may create the next experiment. It may not rewrite the previous.
- **Principle G**: tmux provides operational continuity. Expcon provides scientific continuity.
- **Principle H**: Use existing infrastructure. Do not become another ML platform.
