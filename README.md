# Expcon

Expcon is a Python CLI for controlling experiments on a trusted research host.
It freezes experiment definitions, checks declared executable and input identities,
preserves execution records, verifies collected evidence, and evaluates scientific
acceptance rules independently of metrics supplied by the workload.

**Successful execution is not scientific support.** A run can complete with valid
evidence and still receive NOT_SUPPORTED or INCONCLUSIVE.

## Current scope

Local validation covers Python 3.10, 3.11 and 3.12 on Linux. The pre-push suite
passed 268 tests on each interpreter. Other platforms and interpreter versions
have not been validated. Local execution and persistence use POSIX conventions.

| Backend | Implemented behavior | Validation boundary |
|---|---|---|
| Local | Sequential subprocess stages, declared input checks, environment preflight, evidence collection and adjudication | A real CPU logistic-regression workflow has been exercised. Contracts declaring local GPU/TPU requirements are refused because accelerator attestation is not implemented. |
| Kaggle | Kernel submission/status and output collection with version-binding checks | Transport and asynchronous lifecycle tests use fakes. Live provider behavior remains unverified. Missing provenance capabilities block admission or collection. |
| Tinker | Optional SDK/CLI transport and a frozen local driver that calls the managed service | Mock-tested; no live training validation in this release preparation. Requires Python 3.11+ for the optional dependency. Expcon does not implement distributed training. |
| Colab | Runtime discovery/provisioning adapter | Generic CLI execution is blocked before allocation; no complete workload-execution and evidence-fetch channel is implemented. |

This is research tooling under active development, not a production-readiness
claim. It is not a security sandbox, a GPU optimiser or a distributed scheduler.

## Install from this checkout

With [uv](https://docs.astral.sh/uv/) available:

```bash
uv sync --locked --group dev --python 3.12
uv run --no-sync expcon --version
uv run --no-sync expcon doctor --json
```

The dependency lock supports the tested Python 3.10–3.12 matrix. The package
declares Python >=3.10; compatibility beyond the tested matrix is not established.

To expose the CLI as an isolated tool from the checkout:

```bash
uv tool install --python 3.12 .
expcon --version
```

The control CLI and a workload's execution environment are separate. Local
execution uses the workspace `.venv/bin/python`, with runtime preflight checks
for the declared lock identity, Python requirement and direct dependencies.
Installing Expcon alone does not install a model's dependencies.

## Run the complete CPU validation workflow

This is the executable introduction to the framework. It generates a small
synthetic dataset, trains and evaluates a real logistic-regression model, and
writes all study records to a new directory outside the checkout.

Run from the repository root after the development installation above:

```bash
study_root=$(mktemp -d)

uv run --no-sync python -B tools/validation/run_study.py \
  --output-root "$study_root"

uv run --no-sync python -B tools/validation/independent_check.py \
  "$study_root"/*/validation.json \
  "$study_root/independent-check.json"
```

The fixed protocol uses 640 training examples, 256 held-out examples, seed 1729,
and acceptance criteria of accuracy >=0.8 **and** log loss <=0.55. The positive
model trains for 120 epochs; the negative control uses an explicitly declared
zero-epoch ablation with the same data and acceptance criteria. Evaluation metrics
are computed by the model code, not hardcoded.

| Case | Execution | Evidence | Scientific verdict |
|---|---|---|---|
| Trained model, five runs | COMPLETED | VERIFIED | SUPPORTED |
| Zero-epoch negative control | COMPLETED | VERIFIED | NOT_SUPPORTED |
| Corrupted copy of a completed run's evidence | COMPLETED | INVALID | INCONCLUSIVE |

The harness exercises validation, freeze, bundle construction, execution, fetch,
verification and adjudication. It compares run identities, metrics, model
weights/bias and artifact hashes across replays. Metric and weight tolerances are
declared in the [protocol](tools/validation/workload/protocol.json) before execution.

The independent checker uses the standard library without importing Expcon.
It rehashes bundle/evidence content and recomputes held-out metrics from saved
weights. It is an independent check of stored bytes and measurements, not a
second implementation of model training or proof against a hostile host.

Each invocation creates a unique workspace and retains failed attempts. The
study also records repeated timing measurements; these are diagnostic wall times,
not GPU performance or large-scale efficiency benchmarks.

## How an experiment moves through Expcon

```text
Experiment definition
  → validation and freeze
  → executable bundle
  → backend execution
  → output collection and evidence packaging
  → verification against retained run identities
  → scientific adjudication against frozen acceptance rules
```

The implementation keeps experiment state, run state and adjudication results
separate. Remote SUBMITTED/PENDING/RUNNING observations are not completion.
Scientific adjudication reports execution, contract compliance, evidence validity
and a scientific verdict independently.

### Author a draft

With the tool installed, run these in your research workspace:

```bash
expcon init
expcon init --name E01 --version v001 --title "My experiment"
expcon inspect experiments/e01_v001 --json
```

The second command creates a contract scaffold, not a runnable model or a complete
scientific specification. Before freezing, provide:

- The actual stage entrypoint and declared source closure.
- A dependency lock and an existing compatible execution environment.
- Dataset/model input bindings and expected content hashes where required.
- Workload parameters, split, seeds, output files and metric definitions.
- Explicit acceptance rules if a scientific verdict is required.

A numeric acceptance-rule excerpt:

```yaml
bundle_identity_algorithm: expcon-bundle-v3
evaluation:
  primary_metric: accuracy
  metrics_file: metrics.json
  acceptance:
    all:
      - metric: accuracy
        operator: ">="
        threshold: 0.8
      - metric: log_loss
        operator: "<="
        threshold: 0.55
outputs:
  required:
    - metrics.json
```

This is an excerpt, not a complete contract. Supported comparison operators are
`>`, `>=`, `<`, `<=` and `==`, with a nonempty `all` conjunction.
Measurements must be finite numbers; booleans are not numeric evidence.
Output-provided thresholds or verdict strings cannot override the frozen rules.
Missing observations or insufficient trusted criteria cannot produce SUPPORTED.

### Operate the configured experiment

The following is a workflow outline for a completed draft. Use actual paths and
the run ID returned by `run`. Inspect and validate the contract before operations;
the [agent guidelines](AGENTS.md) describe the operating procedure. Stop on any
nonzero exit; this outline is not an unattended shell script.

```bash
expcon validate experiments/e01_v001 --json
expcon preflight experiments/e01_v001 --json
expcon freeze experiments/e01_v001 --json
expcon diff experiments/e01_v001 --json
expcon bundle experiments/e01_v001 --json
expcon verify-bundle experiments/e01_v001/bundle --json
expcon run experiments/e01_v001 --backend local --json

expcon status RUN_ID --json
expcon fetch RUN_ID --json
expcon verify RUN_ID --json
expcon artifacts RUN_ID --json
expcon adjudicate RUN_ID --json
```

Pass named runtime inputs using `--input NAME=PATH` when the contract declares
them. The selected backend must be in `execution.allowed_backends`.
Preflight does not execute the model or establish that the runtime can satisfy
every requirement; execution admission also checks the local environment.

After freeze, a scientific change requires a new experiment version and an
explicit deviation. Retained freeze locks cannot be replaced by freezing again.
Do not repair a frozen experiment in place to turn a failure into support.

Use `expcon --help` and `expcon COMMAND --help` for the complete current CLI.
The CLI also exposes provider diagnostics, skill installation and tmux workspace
commands. Provider diagnostics may require credentials and contact the service;
the CPU validation workflow does not use provider accounts.

## Trust and reproducibility boundaries

The host must protect the retained contract locks, run records and evidence seals.
Experiment code, backend adapters and measurements remain part of the trust
assumptions. An operator who can replace both payloads and trusted roots can defeat
local hash-based verification. Arbitrary Python workloads are not sandboxed.

- **Identity:** canonical contract and versioned bundle algorithms identify
  declared content. A digest does not authenticate who produced that content.
- **Executable integrity:** opt-in `expcon-bundle-v3` binds materialised runner,
  source, configuration and declared dependency-lock payload bytes. Historical
  v1/v2 algorithms retain their interpretation and do not acquire v3 assurance.
- **Expected roots:** standalone `verify-bundle` checks internal consistency.
  Execution admission additionally checks the bundle against the frozen lock;
  evidence verification checks against an expected run and retained evidence seal.
- **Runtime inputs:** declared file/tree content hashes are checked at admission.
  Hashing an index file alone does not bind every referenced file. Undeclared
  imports, external reads, network resources and post-check mutations are outside
  complete closure guarantees.
- **Environment:** local preflight checks the lock, Python requirement, direct
  dependency versions/imports and optional declared distribution inventory. It
  records CPU/platform information; it does not certify numerical equivalence
  across hardware.
- **Evidence:** new packages inventory content, require outputs from the frozen
  contract, check linked identities and reject divergent output copies.
  Verification reads protected evidence without modifying it. New attempts retain
  separate verification/adjudication records.
- **Artifacts:** registration records a content hash and provenance metadata with
  REGISTERED status. Registration alone is not independent provenance verification
  or proof of causal lineage.
- **Reproducibility:** a declared seed or reproducibility level does not enable
  framework determinism. Workload code must honour its seeds and execution rules.
  Replay equivalence is demonstrated only for the specified CPU study and tolerances.

Run persistence uses local POSIX advisory locks, atomic writes and a journal with
derived snapshots. Stages execute sequentially in dependency order. These controls
do not provide exactly-once remote submission, general automatic resume or
distributed coordination. An uncertain submission requires reconciliation rather
than blind resubmission.

Known credential bindings and provider fields are redacted in supported paths.
That is not a guarantee that arbitrary workload output is secret-free. Do not put
credentials in contracts, outputs or evidence.

## Development checks and CI

```bash
uv run --no-sync python -B tools/check_quality.py

PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python -B -m pytest \
  -p no:cacheprovider --cov=src/expcon --cov-branch --cov-report=term-missing
```

The quality script runs Ruff lint on all source modules and release tooling,
mypy on all source modules with `check_untyped_defs`, and formatter verification
on an explicit subset. This is not strict mypy or whole-repository formatting
enforcement. Tests cover contracts, identity, tampering, lifecycle, admission,
adjudication, CLI behavior and mocked provider boundaries.

| Workflow | Checks | Triggers |
|---|---|---|
| [CI](.github/workflows/ci.yml) | Python 3.10–3.12 tests, lint/types/scoped formatting, dependency consistency, JUnit and coverage reports | PRs to main, pushes to main, manual dispatch |
| [Research integrity](.github/workflows/research-integrity.yml) | CPU positive/negative results, corruption, replay and independent measurement checks on Python 3.10–3.12 | PRs to main, pushes to main, manual dispatch |
| [Release validation](.github/workflows/release-validation.yml) | Sdist-to-wheel build, metadata/resources and runtime-only installation checks on Python 3.10–3.12 | PRs to main, pushes to main, manual dispatch, `v*`/`rc-*` tag pushes |

Workflows use read-only repository permissions, pinned action commits and bounded
artifact retention: seven days for test/package diagnostics and three days for
CPU-study artifacts. They do not publish packages or create releases.
Only local workflow validation has occurred; GitHub-hosted execution remains
unverified until an authorised PR, qualifying push or dispatch.

Tests generate temporary fixtures and the study creates fresh records. Historical
examples/run records already tracked upstream are unchanged compatibility material,
not results generated by this release candidate. Local recovery folders and new
experiment outputs are excluded from the intended commit.

## Build and check a package

Run from the checkout after installing the development environment:

```bash
package_dir=$(mktemp -d)

uv build --sdist --out-dir "$package_dir"
uv build "$package_dir"/expcon-*.tar.gz --wheel --out-dir "$package_dir"

uv run --no-sync python -B tools/check_distribution.py "$package_dir"

uv run --no-sync python -B tools/validation/check_installation.py \
  --wheel "$package_dir"/expcon-*.whl \
  --interpreter "current=$(uv run --no-sync python -B -c 'import sys; print(sys.executable)')" \
  --report "$package_dir/installation.json"
```

The installation checker creates a separate runtime environment without development
dependencies, runs outside the checkout, checks package resources and exercises CLI
help/version/doctor/skill commands. The package declares the Python 3.10 `tomli`
dependency and a setuptools minimum compatible with its SPDX licence metadata.

Build outputs and generated validation records belong outside version control.
The existing `SHA256SUMS` file describes an older build; do not treat it as this
candidate's checksum manifest or overwrite it as part of a smoke test.

## Source layout

| Path | Purpose |
|---|---|
| [src/expcon](src/expcon) | Contracts, identities, bundles, execution, evidence, adjudication, CLI and adapters |
| [tests](tests) | Unit, lifecycle, CLI, integrity and provider-fake tests |
| [tools/validation](tools/validation) | CPU model/generator/protocol, study harness, independent checker and installation checks |
| [tools/check_distribution.py](tools/check_distribution.py) | Built archive metadata/resource checks |
| [AGENTS.md](AGENTS.md) | Experiment-operation guidance for agents |

## Licence

[MIT](LICENSE).
