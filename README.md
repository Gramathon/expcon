# Expcon

**Open, local-first experiment control for AI-assisted ML research.**

Expcon provides a deterministic scientific boundary between probabilistic AI agents and heterogeneous compute backends.

> **Bring your own agent. Bring your own compute. Expcon controls what the experiment is and verifies what it produced.**

AI agents can reason, implement, diagnose, and operate experiments.

Expcon retains deterministic authority over:

- experiment identity
- freeze and semantic drift
- lifecycle
- provenance
- artifacts
- evidence
- scientific adjudication

**Agents reason. Expcon verifies. Compute executes.**

---

## Why Expcon?

AI coding and research agents can now create experiments, modify code, dispatch remote jobs, inspect results, and generate scientific artifacts faster than a human can reliably audit them.

The bottleneck is increasingly no longer:

> How do we run experiments faster?

It is:

> **How do we increase experimental velocity without losing control over what was actually tested, what changed, where artifacts came from, and whether the resulting evidence supports the scientific conclusion?**

Traditional tools solve important pieces of this problem:

- Git controls source.
- `uv` controls Python environments.
- Kaggle and other providers supply compute.
- W&B and MLflow track metrics.
- tmux provides persistent operator sessions.
- AI agents reason and implement.

Expcon is intended to sit between them as a lightweight **scientific control layer**.

---

## Core idea

```text
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
             ║ lifecycle        ║
             ║ policy           ║
             ║ provenance       ║
             ║ artifacts        ║
             ║ evidence         ║
             ╚════════╤═════════╝
                      │
       ┌──────────────┼───────────────┬──────────────┐
       ▼              ▼               ▼              ▼
     LOCAL          KAGGLE          COLAB          TINKER
    generic       generic ML      runtime         distributed
    compute          / DL         provisioning    LLM training
                      │               │              │
                      │          currently no       native
                      │          arbitrary Expcon   OpenAI-compatible
                      │          workload channel   Anthropic-compatible
                      │
       └──────────────┴───────────────┴──────────────┘
                              │
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

Remote compute is infrastructure.

**It does not define the experiment.**

---

## The deterministic boundary

Expcon deliberately separates probabilistic reasoning from deterministic scientific authority.

```text
                 EXPCON

      Probabilistic          Deterministic
      ─────────────          ─────────────

         Skill                  Core

    choose procedure         identity
    reason about state       lifecycle
    diagnose failure         provenance
    select operations        artifacts
    interpret results        verification
    propose successors       adjudication
```

The operating rule is:

> **The skill tells the agent what to do.  
> The CLI tells the agent what is true.**

An agent may reason that an experiment needs verification.

It does not decide whether verification passed.

That is a deterministic Expcon operation.

---

## Fundamental invariant

> **An execution environment or AI agent may fail to execute a frozen experiment, but it may never silently rewrite the experiment in order to make it execute.**

Examples:

```text
OOM
→ DO NOT silently reduce batch size

Missing dataset
→ DO NOT substitute another dataset

Unavailable model revision
→ DO NOT use "latest"

Metric implementation mismatch
→ DO NOT silently change the metric

Full-state checkpoint restore fails
→ DO NOT silently resume weights-only

Backend lacks required capability
→ DO NOT invent another execution path
```

Instead:

```text
current experiment
       │
       ▼
BLOCKED / FAILED / INVALID
       │
       ▼
diagnosis
       │
       ▼
proposed successor experiment
```

Scientific mutation requires a new experiment identity.

---

## Trust model

Expcon does **not** automatically trust:

- AI-agent assertions
- remote console output
- mutable aliases such as `latest`
- remote provider completion states
- unregistered files
- unverified artifacts
- current provider state as historical provenance
- metrics merely printed to stdout
- remote output whose exact producing run cannot be established

Expcon establishes trust through deterministic mechanisms:

```text
canonical contract
       │
       ▼
frozen identity
       │
       ▼
verified execution bundle
       │
       ▼
exact remote identity
       │
       ▼
registered artifacts
       │
       ▼
evidence manifest
       │
       ▼
verification
       │
       ▼
adjudication
```

**UNKNOWN never becomes PASS by inference.**

---

## What Expcon is

Expcon is a deterministic experiment-control layer that:

- defines scientific experiment identity
- freezes experiments
- detects semantic drift
- validates lifecycle transitions
- controls execution admission
- records exact backend identities
- registers artifacts with provenance
- verifies returned evidence
- separates scientific verdicts from execution outcomes

---

## What Expcon is not

| Category | Expcon's role |
|---|---|
| Experiment tracker | Trackers record what happened. Expcon governs what constitutes the experiment. |
| Job orchestrator | Orchestrators run workloads. Expcon controls whether an execution is scientifically admissible. |
| ML platform | Expcon does not replace training frameworks, cloud infrastructure, notebooks, or experiment UIs. |
| W&B / MLflow replacement | Those systems are useful for metrics and tracking. Expcon focuses on identity, provenance, evidence, and validity. |
| Agent framework | Expcon can be operated by humans or different AI agents. |
| GPU provider | Expcon uses existing execution infrastructure rather than trying to replace it. |

---

## Backend model

Expcon intentionally supports **different execution models** rather than pretending every provider behaves the same way.

| Backend | Execution model | Typical use |
|---|---|---|
| **Local** | Local process execution | Generic ML, development, reference execution |
| **Kaggle** | Remote kernel/notebook execution | Generic ML/DL, dataset-local compute, competitions |
| **Colab** | Managed runtime provisioning | Runtime allocation and observation through the official Runtime API |
| **Tinker** | Managed distributed model-training API | LLM post-training, distributed forward/backward, sampling, checkpoints |

The common abstraction is **scientific control**, not transport mechanics.

---

## A 30-second example

Freeze an experiment:

```bash
expcon validate experiments/E01/v001
expcon freeze experiments/E01/v001
```

Now an agent changes:

```yaml
training:
  learning_rate: 0.001
```

to:

```yaml
training:
  learning_rate: 0.003
```

Expcon detects it:

```bash
expcon diff experiments/E01/v001
```

Example result:

```text
EXPCON CONTRACT DIVERGENCE

Experiment
E01/v001

Field
training.learning_rate

Frozen
0.001

Current
0.003

Classification
SCIENTIFIC

Result
EXPERIMENT IDENTITY CHANGED

Execution
BLOCKED

Recommended action
Create a successor experiment version.
```

The agent may explain the change or propose `E01/v002`.

It may not continue calling the modified experiment `E01/v001`.

---

## Successful experiment flow

```text
DRAFT
  │
  ▼
VALIDATED
  │
  ▼
FROZEN
  │
  ▼
READY
  │
  ▼
SUBMITTED
  │
  ▼
RUNNING
  │
  ▼
RESULTS_AVAILABLE
  │
  ▼
EVIDENCE_VERIFIED
  │
  ▼
ADJUDICATED
  │
  ▼
CLOSED
```

Failure and integrity states include:

```text
BLOCKED
FAILED_EXECUTION
INVALID_RUN
CONTRACT_VIOLATION
EVIDENCE_INVALID
```

Lifecycle state is explicit and persisted.

File existence does not define experiment state.

tmux is not the database.

Closing a terminal, restarting an agent, or destroying a tmux session does not destroy the scientific run state.

---

## Execution success is not scientific success

Expcon deliberately keeps these concepts separate.

A completely valid experiment may produce:

```text
Execution       COMPLETED
Contract        COMPLIANT
Evidence        VERIFIED
Scientific      NOT_SUPPORTED
```

That is a successful scientific experiment.

Possible scientific verdicts include:

```text
SUPPORTED
NOT_SUPPORTED
INCONCLUSIVE
```

A negative result does not authorize an agent to silently alter and rerun the same frozen experiment until it becomes positive.

---

## Installation

### Global tool installation

When installing from a published distribution:

```bash
uv tool install expcon
```

During development:

```bash
uv tool install --editable --force /path/to/expcon
```

Verify:

```bash
expcon --version
expcon doctor
```

Expcon is intended to be installed as a global control tool.

It does **not** need to live inside every ML project's `.venv`.

---

## Agent integration

Expcon ships:

1. a deterministic CLI/library
2. a canonical agent skill
3. backend-specific playbooks
4. versioned schemas and project templates

```text
AGENT
  │
  ▼
EXPCON SKILL
  │
  ▼
EXPCON CLI
  │
  ├── LOCAL
  ├── KAGGLE
  │     ├── Public API
  │     └── official CLI
  │
  ├── COLAB
  │     └── Runtime API
  │
  └── TINKER
        ├── SDK
        ├── CLI
        ├── native sampling
        ├── OpenAI-compatible inference
        └── Anthropic-compatible inference
```

The skill teaches:

- what procedure to follow
- what the lifecycle means
- which operations are permitted
- how to react to blockers
- when backend-specific playbooks apply

The deterministic CLI owns:

- identity
- lifecycle
- provenance
- backend capability interpretation
- artifact registration
- evidence verification
- adjudication

Provider API implementation details do **not** belong in scientific contracts.

### Skill commands

```bash
expcon skill path
expcon skill status --json
expcon skill install --target <agent-skills-dir>
```

The installed skill bundle includes playbooks for:

- lifecycle
- scientific vs operational state
- artifacts and evidence
- local execution
- Kaggle
- Colab
- Tinker

Credentials are never included.

---

## Quick start

Initialize an existing repository:

```bash
expcon init
```

Create an experiment:

```bash
expcon init \
  --name E13 \
  --version v002 \
  --title "My Experiment"
```

Validate:

```bash
expcon validate experiments/e13_v002/EXPERIMENT.yaml
```

Freeze:

```bash
expcon freeze experiments/e13_v002/EXPERIMENT.yaml
```

Inspect frozen drift:

```bash
expcon diff experiments/e13_v002/EXPERIMENT.yaml
```

Bundle:

```bash
expcon bundle experiments/e13_v002/EXPERIMENT.yaml
```

Verify the bundle:

```bash
expcon verify-bundle experiments/e13_v002/bundle
```

Run locally:

```bash
expcon run \
  experiments/e13_v002/EXPERIMENT.yaml \
  --backend local
```

Or Kaggle:

```bash
expcon run \
  experiments/e13_v002/EXPERIMENT.yaml \
  --backend kaggle \
  --kernel owner/kernel
```

Inspect Colab capabilities:

```bash
expcon colab doctor --json
expcon colab specs
```

Inspect optional Tinker support:

```bash
expcon tinker doctor --json
```

Then:

```bash
expcon status <run_id>
expcon fetch <run_id>
expcon artifacts <run_id>
expcon verify <run_id>
expcon adjudicate <run_id>
```

---

## Scientific identity

Expcon canonicalizes experiment definitions before calculating identity.

Formatting changes such as:

- YAML indentation
- comments
- key order
- whitespace

must not alter scientific identity.

Scientific changes should.

Conceptually:

```text
Experiment Contract
       +
Source identity
       +
Dependency identity
       +
Dataset manifests
       +
Scientific configuration
       +
Evaluation contract
       │
       ▼
canonical representation
       │
       ▼
SHA256
       │
       ▼
frozen experiment identity
```

Identity algorithms are versioned.

For example:

```json
{
  "schema_version": 1,
  "identity_algorithm": "expcon-canonical-v1",
  "hash_algorithm": "sha256"
}
```

An Expcon upgrade must not silently redefine historical experiment identities.

---

## Scientific vs operational parameters

### Scientific parameters

Changing these normally changes experiment identity:

- dataset identity
- split
- preprocessing
- model architecture
- model revision
- tokenizer revision
- prompt/template
- training algorithm
- learning rate
- batch size when contract-defined scientifically
- epochs
- seed
- reward/loss
- evaluation cohort
- metric
- acceptance criteria
- checkpoint/resume source and semantics

### Operational parameters

These normally do not:

- hostname
- temporary directory
- timestamps
- backend request ID
- CPU count
- filesystem mount path
- unconstrained physical GPU identity

Hardware may become scientific when the contract explicitly constrains it.

Agents should use:

```bash
expcon diff <experiment> --json
```

rather than guessing how a change is classified.

---

## Artifacts and evidence

An output file is not automatically scientific evidence.

```text
OUTPUT
  │
  ▼
registered ARTIFACT
  │
  ▼
provenance
  │
  ▼
EVIDENCE
  │
  ▼
verification
```

Artifacts may include:

- checkpoints
- adapters
- predictions
- OOF predictions
- metrics
- embeddings
- generated datasets
- trajectory analyses
- plots
- reports
- submissions

Each important artifact can retain:

```text
artifact ID
artifact type
SHA256
experiment ID
run ID
producer stage
parent inputs
backend identity
local/remote location
verification state
```

Evidence then proves the relationship between:

```text
Claim
  ↓
Experiment
  ↓
Run
  ↓
Stage
  ↓
Artifact
  ↓
Evidence
  ↓
Conclusion
```

---

## Local backend

Local execution is the reference backend.

```bash
expcon run <experiment> --backend local
```

Local runs still use:

- frozen contract verification
- bundle verification
- lifecycle registration
- artifact registration
- evidence construction
- evidence verification

Local execution does not bypass scientific control merely because it happens on the same machine.

---

## Hybrid Kaggle backend

```text
                 EXPCON
                    │
              KaggleBackend
               /         \
              /           \
      Public API           CLI
      structured         dispatch /
        state             fallback
              \           /
               \         /
                 KAGGLE
```

Expcon uses Kaggle's structured API capabilities where appropriate while retaining the official CLI for mature execution and fallback operations.

Inspect configuration:

```bash
expcon kaggle doctor --json
```

Typical controlled execution:

```bash
expcon run \
  experiments/E01/v001 \
  --backend kaggle \
  --kernel owner/slug
```

### Kaggle exact-version provenance

A Kaggle kernel slug is **not** an immutable run identity.

```text
owner/e19-training
       │
       ├── version 10
       ├── version 11
       └── version 12
```

Expcon binds a controlled run to the exact remote version where Kaggle exposes it.

A later push to the same kernel must never redefine historical Expcon provenance.

### Fail-closed Kaggle output binding

Consider:

```text
Kaggle kernel v12 → Expcon run A
Kaggle kernel v13 → Expcon run B
```

If the available transport can only retrieve:

```text
latest output
```

Expcon must not assume that output belongs to run A.

Instead:

```text
OUTPUT_VERSION_AMBIGUOUS
```

and evidence verification remains blocked.

This protects against silently attaching output from a newer kernel version to an older scientific experiment.

### Kaggle operator commands

```bash
expcon kaggle doctor [--json]

expcon kaggle inspect <owner/slug> [--json]

expcon kaggle status <run> [--json]

expcon kaggle dataset inspect <owner/slug> [--json]

expcon kaggle competition inspect <slug> [--json]
```

Provider status is an operational observation.

For example:

```text
Kaggle COMPLETE
      │
      ▼
RESULTS_AVAILABLE
      │
      ▼
fetch
      │
      ▼
artifact registration
      │
      ▼
evidence
      │
      ▼
verify
      │
      ▼
EVIDENCE_VERIFIED
```

**Kaggle COMPLETE != EVIDENCE_VERIFIED.**

---

## Colab Runtime backend

The Colab adapter uses the official Runtime API for:

- capability discovery
- runtime-spec inspection
- runtime provisioning
- operation polling
- runtime observation
- runtime release

Commands include:

```bash
expcon colab doctor [--json]
expcon colab specs [--json]
expcon colab runtimes [--json]
expcon colab inspect <runtime> [--json]
```

The current supported Runtime API does not provide the arbitrary Expcon workload execution and output-fetch path required for a complete controlled experiment.

Expcon therefore fails closed.

Conceptually:

```text
COLAB CAPABILITIES

provision     ✓
inspect       ✓
release       ✓
execute       ✗
fetch         ✗


EXPERIMENT REQUIRES

execute       ✓
fetch         ✓


RESULT

BLOCKED
BACKEND_CAPABILITY_MISMATCH
```

Expcon never converts:

> runtime exists

into:

> experiment executed

without an actual supported execution path.

Connection credentials and short-lived tokens are never persisted in contracts, events, evidence, bundles, or machine-readable output.

---

## Tinker managed LLM backend

Tinker is **not generic GPU execution**.

It is an optional managed backend for distributed LLM training and sampling.

```text
             EXPCON
                │
          frozen driver
                │
                ▼
          Tinker SDK/API
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
   training   sampling  checkpoints
       │
       ▼
 distributed model compute
```

The local experiment driver controls:

- data
- loss/reward
- training algorithm
- evaluation
- sampling configuration
- checkpoint policy

Tinker supplies managed distributed model computation.

The frozen driver source is therefore part of experiment identity.

### Tinker checkpoint provenance

Expcon distinguishes:

```text
TRAINING STATE CHECKPOINT

weights + training continuation state
```

from:

```text
SAMPLER WEIGHTS CHECKPOINT

weights intended for inference/sampling
```

These are not interchangeable artifacts.

Downloaded checkpoints are hashed locally and registered with Expcon provenance.

Expcon does not automatically:

- publish checkpoints
- push models externally
- upload to Hugging Face

Those are explicit release actions.

### Tinker resume semantics

These are scientifically distinct:

```text
weights_only
```

and:

```text
weights_and_optimizer
```

If a frozen experiment requires:

```text
weights_and_optimizer
```

and the full state cannot be restored, Expcon blocks.

It must not silently fall back to:

```text
weights_only
```

or restart from the base model.

### Tinker-compatible inference APIs

Tinker may expose:

- native sampling
- OpenAI-compatible inference
- Anthropic-compatible inference

These describe **protocol compatibility**, not provider identity.

Correct provenance:

```text
provider = tinker
protocol = openai_compatible
```

or:

```text
provider = tinker
protocol = anthropic_compatible
```

Not:

```text
provider = openai
```

or:

```text
provider = anthropic
```

Protocol changes may alter:

- rendering
- message encoding
- tools
- stop semantics
- thinking representation

Expcon therefore does not silently fall back between native, OpenAI-compatible, and Anthropic-compatible inference transports.

### Tinker operator commands

```bash
expcon tinker doctor [--json]

expcon tinker runs [--json]
expcon tinker run inspect <id>

expcon tinker sessions [--json]
expcon tinker session inspect <id>

expcon tinker checkpoints [training-run] [--json]
expcon tinker checkpoint inspect <tinker://...>
expcon tinker checkpoint fetch <tinker://...> --output-dir <dir>

expcon tinker trace <session> [--json]
```

Only implemented commands should be exposed.

---

## Reproducibility levels

Expcon does not claim that all machine-learning computation can be bitwise reproduced.

Supported conceptual levels include:

| Level | Meaning |
|---|---|
| `functional` | Functionally equivalent behaviour/output |
| `seeded` | Declared random seed is preserved |
| `framework_deterministic` | Framework deterministic controls are enabled |
| `hardware_constrained` | Hardware class is part of execution requirements |
| `bitwise` | Bit-identical reproduction is required |

Expcon itself deterministically controls:

- identity
- configuration
- lifecycle
- policy
- hashes
- provenance
- artifact registration
- evidence verification

The underlying ML computation may have a weaker reproducibility guarantee.

---

## Machine-readable agent interface

Agents should prefer structured output wherever available:

```bash
expcon doctor --json

expcon inspect <experiment> --json
expcon validate <experiment> --json
expcon diff <experiment> --json

expcon status <run> --json

expcon kaggle doctor --json
expcon kaggle status <run> --json

expcon colab doctor --json

expcon tinker doctor --json
```

For example:

```json
{
  "status": "blocked",
  "reason": "BACKEND_CAPABILITY_MISMATCH",
  "required": {
    "execute": true,
    "fetch": true
  },
  "available": {
    "execute": false,
    "fetch": false
  }
}
```

An agent should interpret this as:

> The selected backend cannot satisfy the frozen execution requirements.

It should **not** attempt to invent another execution route.

---

## tmux workspace

tmux is an optional operator interface.

```bash
expcon workspace <experiment>
expcon attach <experiment>
```

A possible cockpit:

```text
Window 1 — Agents

┌──────────────────────┬─────────────────────┐
│ Orchestrator         │ Coding Agent        │
│                      ├─────────────────────┤
│                      │ Review Agent        │
└──────────────────────┴─────────────────────┘


Window 2 — Expcon

┌──────────────────────┬─────────────────────┐
│ Control              │ Source / Diff       │
├──────────────────────┼─────────────────────┤
│ Experiment Overview  │ Backend / Compute   │
└──────────────────────┴─────────────────────┘
```

tmux provides **operational continuity**.

Expcon provides **scientific continuity**.

Destroying the tmux session must not destroy the experiment state.

---

## Complete CLI reference

`<experiment>` accepts an experiment directory or `EXPERIMENT.yaml`; `<run>` is an Expcon run ID.

Commands marked `--json` emit stable machine-readable data.

Exit code `0` means success; validation, verification, and frozen-diff failures exit non-zero so agents and CI must stop rather than guess.

### Project and skill setup

| Command | What it does |
|---|---|
| `expcon --version` | Prints installed Expcon version. |
| `expcon init [--json]` | Creates `.expcon/config.toml`, `runs/`, `artifacts/`, `state/`, `experiments/`, and `.expcon/AGENTS.fragment.md` in the current repository. Existing `AGENTS.md` is never overwritten. |
| `expcon init --name E01 --version v001 --title "…" [options]` | Creates an editable experiment contract. Options may include `--backend`, `--hypothesis`, `--primary-metric`, repeatable `--required-output`, `--python`, `--reproducibility-level`, and `--seed`. |
| `expcon doctor [--json]` | Reports core version, available tools, packaged skill, and detected project state. |
| `expcon skill path` | Prints the canonical packaged `SKILL.md` location. |
| `expcon skill status [--json]` | Reports bundled skill availability and installed-agent compatibility where detectable. |
| `expcon skill install [--target <skills-dir>] [--json]` | Copies the canonical skill bundle to an explicit agent-skill directory. Unknown agent directories are not guessed. |

### Contract, identity, and bundle control

| Command | What it does |
|---|---|
| `expcon inspect <experiment> [--json]` | Shows contract identities, lifecycle state, frozen state, stages, outputs, and allowed backends. |
| `expcon validate <experiment> [--json]` | Validates schema, stage DAG, output declarations, acceptance-rule form, and mutable scientific aliases. |
| `expcon freeze <experiment> [--json]` | Validates, calculates canonical identities, writes `contract.lock.json`, writes source manifest, and transitions to `FROZEN`. It never rewrites editable YAML. |
| `expcon diff <experiment> [--json]` | Compares frozen scientific/source/config/runner state with the current tree. A detected divergence is non-zero and means create a successor version. |
| `expcon bundle <experiment> [--json]` | Requires a clean frozen contract and creates a protected content-addressed bundle. |
| `expcon verify-bundle <bundle> [--json]` | Verifies protected bundle file hashes, contract hash, extras, and bundle identity. |

### Run lifecycle, evidence, and adjudication

| Command | What it does |
|---|---|
| `expcon run <experiment> --backend local [--accelerator none] [--json]` | Verifies frozen state, clean diff, backend allowance, and bundle; then runs declared stages locally. |
| `expcon run <experiment> --backend kaggle --kernel owner/slug [--accelerator none] [--json]` | Uses the hybrid Kaggle adapter. A remote run must resolve an exact kernel version before Expcon accepts its remote identity. |
| `expcon run <experiment> --backend colab [--json]` | Uses the official Colab Runtime API for provisioning/observation. It blocks rather than inventing an unsupported workload-execution channel. |
| `expcon run <experiment> --backend tinker [--json]` | Runs the frozen local LLM-training driver against the optional Tinker managed service. |
| `expcon ps [--json]` | Lists persisted runs. |
| `expcon status <run> [--json]` | Shows canonical Expcon state plus backend observation. |
| `expcon events <run> [--json]` | Shows the append-only event ledger. |
| `expcon events <run> --follow [--json]` | Tails new event-ledger entries. |
| `expcon fetch <run> [--output-dir <dir>] [--json]` | Retrieves backend evidence where supported, packages it, and advances lifecycle only when valid. |
| `expcon artifacts <run-or-experiment> [--json]` | Lists registered artifacts and provenance. |
| `expcon verify <run> [--bundle <path>] [--json]` | Verifies evidence, artifacts, metrics, required outputs, contract, and bundle linkage. |
| `expcon adjudicate <run> [--json]` | Separately reports execution, contract, evidence, and scientific verdict. |
| `expcon workspace <experiment> [--json]` | Creates an optional tmux operations workspace. |
| `expcon attach <experiment> [--json]` | Returns attachment details for that tmux workspace. |

### Kaggle operator commands

| Command | What it does |
|---|---|
| `expcon kaggle doctor [--json]` | Reports Public API and official CLI availability/authentication separately, plus the transport designated for supported capabilities. |
| `expcon kaggle inspect <owner/slug> [--json]` | Inspects a kernel using structured Kaggle metadata where available. |
| `expcon kaggle status <run> [--json]` | Gets API-preferred remote status for an Expcon Kaggle run; uses CLI only as an explicit operational fallback. |
| `expcon kaggle dataset inspect <owner/slug> [--json]` | Reads dataset metadata without downloading it. |
| `expcon kaggle competition inspect <slug> [--json]` | Reads competition metadata without scraping webpages. |

Where an output transport is latest-only, Expcon refuses to associate that output with an already version-bound historical run unless the producing version can be established.

### Colab operator commands

| Command | What it does |
|---|---|
| `expcon colab doctor [--json]` | Checks configured access and API/spec availability without emitting credentials. |
| `expcon colab specs [--json]` | Lists eligible Runtime API specs, including CPU/GPU/TPU shape information returned by Colab. |
| `expcon colab runtimes [--json]` | Lists API-managed runtimes. |
| `expcon colab inspect <runtime> [--json]` | Gets a runtime observation with sensitive connection information redacted. |

### Tinker operator commands

| Command | What it does |
|---|---|
| `expcon tinker doctor [--json]` | Reports optional public SDK and CLI availability, credential-safe authentication/reachability, and capability namespaces. |
| `expcon tinker runs [--json]` / `expcon tinker run inspect <id>` | Lists or inspects training runs through the supported structured API. |
| `expcon tinker sessions [--json]` / `expcon tinker session inspect <id>` | Lists or inspects service sessions. |
| `expcon tinker checkpoints [training-run] [--json]` / `expcon tinker checkpoint inspect <tinker://…>` | Lists or inspects remote checkpoints without publishing or deleting them. |
| `expcon tinker checkpoint fetch <tinker://…> --output-dir <dir> [--json]` | Fetches a checkpoint through a supported transport, rejects unsafe paths, and produces a local manifest. |
| `expcon tinker trace <session> [--json]` | Exports a session trace as an operational artifact where supported. |

---

## Security

Expcon treats bundles and remote outputs as untrusted.

Security controls include:

- archive path-traversal protection
- symlink-escape protection
- environment-variable redaction
- provider credential redaction
- no arbitrary pickle deserialization for verification
- safe subprocess argument handling
- explicit artifact hashing
- fail-closed remote-identity handling

Expcon must never persist:

- Kaggle API credentials
- OAuth tokens
- Colab connection tokens
- `TINKER_API_KEY`
- bearer tokens
- authorization headers
- temporary signed artifact URLs

Credentials belong to the provider's supported credential mechanism, not to the scientific contract.

---

## Build and verify a release

```bash
uv build

sha256sum dist/* > SHA256SUMS
```

Test the built wheel independently:

```bash
release_dir=$(mktemp -d)

UV_TOOL_DIR="$release_dir/tools" \
UV_TOOL_BIN_DIR="$release_dir/bin" \
uv tool install --force dist/expcon-*.whl

"$release_dir/bin/expcon" --version
"$release_dir/bin/expcon" doctor
"$release_dir/bin/expcon" skill status
```

Release artifacts should be immutable.

Changes to canonicalization, identity semantics, schemas, or lifecycle behaviour should be treated more carefully than terminal/UI changes.

---

## Protocol vs implementation

Expcon is moving toward two related concepts:

```text
EXPCON PROTOCOL
────────────────────────
contract semantics
identity algorithms
lifecycle
artifact model
evidence model
backend capability semantics


REFERENCE IMPLEMENTATION
────────────────────────
Python package
CLI
canonical agent skill
Local adapter
Kaggle adapter
Colab adapter
Tinker adapter
```

This distinction allows the scientific protocol to remain portable even if the implementation evolves.

For example:

```text
Contract schema
expcon-schema-v1

Identity
expcon-canonical-v1
```

should retain their meaning across future implementation changes.

---

## Design principles

```text
AI creativity before freeze.
Deterministic authority after freeze.

Agents reason.
Expcon verifies.

Remote compute executes.
It does not define the experiment.

Artifacts without provenance are incomplete artifacts.

Execution success and scientific success are different.

Post-hoc findings create new experiments.
They do not rewrite old ones.

tmux provides operational continuity.
Expcon provides scientific continuity.

Bring your own agent.
Bring your own compute.

Do not become another ML platform.
```

---

## Status

Expcon is under active development.

The project is intentionally proving its control model against multiple execution styles before expanding into additional provider integrations.

Current backend classes include:

```text
Local
  → generic local ML execution

Kaggle
  → generic remote ML/DL execution
  → dataset locality
  → competition workflows

Colab
  → managed runtime provisioning
  → fail-closed when required execution capability is unavailable

Tinker
  → managed distributed LLM post-training
  → native sampling
  → checkpoint lifecycle
  → compatible inference transports
```

The objective is not maximum provider count.

It is to prove that the same experiment identity, lifecycle, provenance, artifact, and evidence model survives meaningfully different execution environments.

---

## License

MIT