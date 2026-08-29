# Expcon — Experiment Control System for AI-Assisted ML Research

**Expcon is an experiment control system for reproducible, AI-assisted ML research.**
It allows humans and agents to move quickly while deterministic tooling preserves
experiment identity, lifecycle, artifact provenance, execution evidence, and
scientific validity.

## The Problem

AI coding/research agents can now create experiments, modify code, dispatch remote
jobs, and generate scientific artifacts much faster than a human can reliably audit
them. The central problem is no longer "how do we run ML experiments quickly?" — it is:

> **How do we allow humans and AI agents to run experiments quickly while preserving
> control over scientific identity, allowed state transitions, provenance, artifacts,
> evidence, and conclusions?**

## What Expcon Is

Expcon is a **deterministic experiment control plane** that:

- Defines and freezes scientific experiment identity
- Governs valid experiment lifecycle transitions
- Dispatches execution to replaceable environments (local, Kaggle)
- Registers generated artifacts with full provenance
- Verifies returned evidence for integrity
- Separates execution success from scientific conclusions

### What Expcon Is NOT

| Category | What Expcon Is NOT |
|---|---|
| Experiment tracker | Records *what happened*. Expcon *governs what constitutes the experiment*. |
| Job orchestrator | Runs workloads. Expcon *governs which transitions are valid*. |
| ML platform | Full-stack platform. Expcon *controls identity, state, policy, provenance*. |
| W&B/MLflow replacement | Metric trackers. Expcon *verifies evidence and adjudicates validity*. |

## The Fundamental Invariant

> An execution environment or AI agent may fail to execute a frozen experiment,
> but it may **never silently rewrite the experiment** in order to make it execute.

```
OOM → DO NOT silently lower batch size
Missing dataset → DO NOT substitute another dataset
Unavailable model revision → DO NOT use latest
Metric implementation mismatch → DO NOT silently change the metric
Frozen configuration conflict → DO NOT repair and continue under the same identity
```

Instead: `current experiment → INVALID/FAILED/BLOCKED → diagnosis → proposed successor`

## Architecture

```
                    HUMAN
                      │
                      ▼
                  AI AGENT
                reasoning layer
                      │
                      ▼
            ╔══════════════════╗
            ║      EXPCON      ║
            ║                  ║
            ║ contract         ║
            ║ identity         ║
            ║ state            ║
            ║ policy           ║
            ║ provenance       ║
            ║ evidence         ║
            ╚════════╤═════════╝
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
        LOCAL                 KAGGLE
                                │
                         data / compute
          │                     │
          └──────────┬──────────┘
                     ▼
                  ARTIFACTS
                     │
                     ▼
                   EVIDENCE
                     │
                     ▼
                 ADJUDICATION
                     │
                     ▼
               HUMAN UNDERSTANDING
```

## Installation

```bash
# Global installation via uv tool
uv tool install --editable /path/to/expcon

# Verify
expcon --version
```

Expcon installs as a global tool. It does **not** install inside every ML project's
`.venv`.

## Quick Start

```bash
# Initialize a new experiment
expcon init --name E13 --version v002 --title "My Experiment"

# Validate the contract
expcon validate experiments/e13_v002/EXPERIMENT.yaml

# Freeze the experiment (computes deterministic identity)
expcon freeze experiments/e13_v002/EXPERIMENT.yaml

# Create a content-addressed bundle
expcon bundle experiments/e13_v002/EXPERIMENT.yaml

# Verify bundle integrity
expcon verify-bundle experiments/e13_v002/bundle

# Run locally
expcon run experiments/e13_v002/EXPERIMENT.yaml --backend local

# Or run on Kaggle (data-locality mode, no GPU)
expcon run experiments/e13_v002/EXPERIMENT.yaml --backend kaggle --kernel smoke

# Fetch and verify evidence
expcon fetch <run_id>
expcon verify <run_id>

# Adjudicate
expcon adjudicate <run_id>

# Open tmux workspace
expcon workspace experiments/e13_v002/
```

## CLI Reference

| Command | Description |
|---|---|
| `expcon init` | Initialize a new experiment contract |
| `expcon inspect <exp>` | Inspect an experiment contract |
| `expcon validate <exp>` | Validate contract structure |
| `expcon freeze <exp>` | Freeze contract (compute identity, write lock) |
| `expcon diff <exp>` | Detect scientific divergence from frozen state |
| `expcon bundle <exp>` | Create content-addressed bundle |
| `expcon verify-bundle <bundle>` | Verify bundle integrity |
| `expcon run <exp> --backend` | Execute on local or Kaggle backend |
| `expcon ps` | List all runs |
| `expcon status <run>` | Get run status |
| `expcon events <run>` | Show run event log |
| `expcon fetch <run>` | Fetch evidence from completed run |
| `expcon verify <run>` | Verify evidence integrity |
| `expcon adjudicate <run>` | Adjudicate execution/contract/scientific status |
| `expcon artifacts <exp-or-run>` | List artifacts with provenance |
| `expcon workspace <exp>` | Create tmux operations workspace |
| `expcon attach <exp>` | Attach to existing tmux workspace |

All commands support `--json` for machine-readable output.

## Experiment Lifecycle

```
DRAFT → VALIDATED → FROZEN → READY → SUBMITTED → RUNNING
  → RESULTS_AVAILABLE → EVIDENCE_VERIFIED → ADJUDICATED → CLOSED
```

Failure states: `BLOCKED`, `FAILED_EXECUTION`, `INVALID_RUN`,
`CONTRACT_VIOLATION`, `EVIDENCE_INVALID`

State transitions are explicit and validated. tmux is **not** the database — state
survives terminal closure, tmux destruction, and agent restart.

## Scientific vs Execution Parameters

**Scientific parameters** (changing these changes experiment identity):
- Dataset identity, split, preprocessing
- Model architecture, revision
- Prompt/template, seed
- Learning rate, batch size, epochs
- Metric, acceptance criteria

**Execution parameters** (changing these does NOT change identity):
- Backend, hostname
- GPU model (when unconstrained)
- CPU count, working directory
- Runtime timestamps

## Reproducibility Levels

| Level | Meaning |
|---|---|
| `functional` | Same outputs for same inputs (no seed guarantee) |
| `seeded` | Same random seed used (default) |
| `framework_deterministic` | Framework deterministic flags enabled |
| `hardware_constrained` | Same hardware class required |
| `bitwise` | Bit-identical reproduction required |

Expcon deterministically controls: identity, configuration, state, policy, hashes,
lineage, evidence. Underlying ML execution may be only statistically reproducible.

## Security

- Archives are extracted with path-traversal protection
- Environment variables are redacted before logging
- Kaggle credentials are never stored
- Bundles and remote outputs are treated as untrusted
- No arbitrary pickle deserialization

## License

MIT
