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
uv tool install expcon

# Development installation
uv tool install --editable --force /path/to/expcon

# Verify
expcon --version
```

Expcon installs as a global tool. It does **not** install inside every ML project's
`.venv`.

## Agent integration

Expcon ships a deterministic CLI/library, a canonical agent skill, and focused
backend playbooks. The skill teaches procedure and permissions; the CLI decides
identity, lifecycle, provenance, and verification; adapters perform provider
operations. Provider API details do not belong in scientific contracts.

```
AGENT → EXPCON SKILL → EXPCON CLI → LOCAL | KAGGLE (API + CLI) | COLAB (Runtime API)
```

Install or inspect the bundled skill with `expcon skill path`, `expcon skill
status --json`, and `expcon skill install --target <agent-skills-dir>`. The
installed bundle includes lifecycle, identity, artifact/evidence, and backend
playbooks; it never includes credentials.

## Quick Start

```bash
# Initialize Expcon control state in an existing ML repository
expcon init

# Create a new experiment contract
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

# Inspect official Colab Runtime API availability and eligible specs
expcon colab doctor
expcon colab specs

# Fetch and verify evidence
expcon fetch <run_id>
expcon verify <run_id>

# Adjudicate
expcon adjudicate <run_id>

# Open tmux workspace
expcon workspace experiments/e13_v002/
```

## Complete CLI reference

`<experiment>` accepts an experiment directory or `EXPERIMENT.yaml`; `<run>` is
an Expcon run ID. Commands marked `--json` emit stable machine-readable data.
Exit code `0` means success; validation, verification, and frozen-diff failures
exit non-zero so agents and CI must stop rather than guess.

### Project and skill setup

| Command | What it does |
|---|---|
| `expcon --version` | Prints installed Expcon version. |
| `expcon init [--json]` | Creates `.expcon/config.toml`, `runs/`, `artifacts/`, `state/`, `experiments/`, and `.expcon/AGENTS.fragment.md` in the current repository. Existing `AGENTS.md` is never overwritten. |
| `expcon init --name E01 --version v001 --title "…" [options]` | Creates an editable experiment contract. Options include `--backend`, `--hypothesis`, `--primary-metric`, repeatable `--required-output`, `--python`, `--reproducibility-level`, and `--seed`. |
| `expcon doctor [--json]` | Reports core version, available tools, packaged skill, and detected project state. |
| `expcon skill path` | Prints the canonical packaged `SKILL.md` location. |
| `expcon skill status [--json]` | Reports bundled skill availability and a `$CODEX_HOME` installation when detectable. |
| `expcon skill install [--target <skills-dir>] [--json]` | Copies the skill to an existing explicit agent-skill directory, or `$CODEX_HOME/skills` when configured. No unknown agent directory is guessed. |

### Contract, identity, and bundle control

| Command | What it does |
|---|---|
| `expcon inspect <experiment> [--json]` | Shows contract identity hashes, lifecycle state, frozen state, stages, outputs, and allowed backends. Run this first. |
| `expcon validate <experiment> [--json]` | Validates schema, stage DAG, output declarations, acceptance-rule form, and mutable scientific aliases. |
| `expcon freeze <experiment> [--json]` | Validates, calculates canonical identities, writes `contract.lock.json`, writes source manifest, and transitions to `FROZEN`. It never rewrites editable YAML. |
| `expcon diff <experiment> [--json]` | Compares frozen scientific/source/config/runner state with the current tree. A detected divergence is non-zero and means create a successor version. |
| `expcon bundle <experiment> [--json]` | Requires a clean frozen contract and creates the protected content-addressed bundle. |
| `expcon verify-bundle <bundle> [--json]` | Verifies protected bundle file hashes, contract hash, extras, and bundle ID. |

### Run lifecycle, evidence, and adjudication

| Command | What it does |
|---|---|
| `expcon run <experiment> --backend local [--accelerator none] [--json]` | Verifies frozen state, clean diff, backend allowance, and bundle; then runs declared stages locally. |
| `expcon run <experiment> --backend kaggle --kernel owner/slug [--accelerator none] [--json]` | Uses the hybrid Kaggle adapter. A remote run must resolve an exact kernel version before Expcon accepts its remote identity. |
| `expcon run <experiment> --backend colab [--json]` | Uses the official allowlisted Colab Runtime API for provisioning/observation. It blocks rather than inventing a workload-execution channel. |
| `expcon ps [--json]` | Lists persisted runs. |
| `expcon status <run> [--json]` | Shows canonical Expcon state plus backend observation. |
| `expcon events <run> [--json]` | Shows the append-only event ledger. |
| `expcon events <run> --follow [--json]` | Tails new event-ledger entries. |
| `expcon fetch <run> [--output-dir <dir>] [--json]` | Retrieves backend evidence, packages it, and advances to fetched evidence where valid. |
| `expcon artifacts <run-or-experiment> [--json]` | Lists registered artifacts and provenance. |
| `expcon verify <run> [--bundle <path>] [--json]` | Verifies evidence, artifacts, metrics, required outputs, contract, and bundle linkage. |
| `expcon adjudicate <run> [--json]` | Separately reports execution, contract, evidence, and scientific verdict. A negative scientific verdict remains a valid execution. |
| `expcon workspace <experiment> [--json]` | Creates an optional tmux operations workspace. |
| `expcon attach <experiment> [--json]` | Returns attachment details for that tmux workspace. |

### Kaggle operator commands

| Command | What it does |
|---|---|
| `expcon kaggle doctor [--json]` | Reports Public API and official CLI availability/authentication separately, plus the transport designated for every capability. |
| `expcon kaggle inspect <owner/slug> [--json]` | Inspects a kernel through the Public API. |
| `expcon kaggle status <run> [--json]` | Gets API-preferred remote status for an Expcon Kaggle run; uses CLI only as an explicit operational fallback. |
| `expcon kaggle dataset inspect <owner/slug> [--json]` | Reads dataset metadata through the Public API without downloading it. |
| `expcon kaggle competition inspect <slug> [--json]` | Reads competition metadata through the Public API without scraping webpages. |

The documented CLI output operation is latest-only. Expcon refuses it for an
already version-bound remote run, returning `OUTPUT_VERSION_AMBIGUOUS` rather
than associating output from a newer kernel version with old evidence.

### Colab operator commands

| Command | What it does |
|---|---|
| `expcon colab doctor [--json]` | Checks configured OAuth access and API/spec availability without emitting a token. |
| `expcon colab specs [--json]` | Lists eligible Runtime API specs, including CPU/GPU/TPU shape information returned by Colab. |
| `expcon colab runtimes [--json]` | Lists the caller’s API-managed runtimes. |
| `expcon colab inspect <runtime> [--json]` | Gets a runtime observation with `ConnectionInfo` redacted. |

### Colab runtime backend

The Colab adapter uses the official allowlisted `v1beta` Runtime API for
capability discovery, runtime provisioning, operations polling, observation,
and release. It records an exact runtime image version when supplied by the
provider and never stores `ConnectionInfo` or its short-lived token.

The published Runtime API manages runtimes but does not provide an arbitrary
bundle-execution or output-fetch endpoint. Consequently `expcon run --backend
colab` provisions only when frozen requirements are met, then deterministically
marks the run `BLOCKED` rather than inventing an execution channel. An approved
artifact transport/execution integration can be added later without changing
the scientific contract.

### Hybrid Kaggle backend

```
                    EXPCON
                       |
                 KaggleBackend
                  /         \\
           Public API       CLI
          structured read  dispatch/fallback
                  \         /
                    KAGGLE
```

Expcon uses the installed official Kaggle Public API for structured kernel,
dataset, competition, and status reads, while retaining the official CLI for
kernel pushes and operational transport. `expcon kaggle doctor --json` reports
the selected transport for each capability.

Kaggle's configured OAuth/API-token mechanism remains the only credential
store. Expcon does not print or persist credentials. API reads use bounded
exponential retry for HTTP 429 and distinguish an authenticated permission
failure from authentication failure.

After a push, Expcon must resolve an API-reported exact kernel version before
it treats the remote execution as bound to a run. The documented CLI output
command retrieves latest output only; it is therefore refused for an older
version-bound run rather than silently attaching newer output. This fail-closed
rule protects kernel-version and artifact provenance.

## Build and verify a release

```bash
uv build
sha256sum dist/* > SHA256SUMS

# Isolated wheel test without changing the user's global tool directory
release_dir=$(mktemp -d)
UV_TOOL_DIR="$release_dir/tools" UV_TOOL_BIN_DIR="$release_dir/bin" \
  uv tool install --force dist/expcon-0.1.0-py3-none-any.whl
"$release_dir/bin/expcon" --version
"$release_dir/bin/expcon" doctor
```

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
