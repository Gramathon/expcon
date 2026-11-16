# Engineering validation report

## Checkpoint 1 — baseline and trust model

Gate: PASSED for planning. No implementation changed. Documents created under docs/recovery; historical hashes and pre-existing diff captured in /tmp. Baseline: 162 passed, 0 failed/skipped/reported warnings, 6.99 s, 63% statement coverage. Raw baseline XML and JSON included. Initial uv cache failure preserved in the recovery plan. Next: checkpoint 2 regression reproduction.

## Checkpoint 2 — scientific correctness

Red: 13 failed / 5 passed (checkpoint2-red.xml), reproducing output criteria,
aggregate substring, missing contract and upstream gating defects through the
full adjudication path. The additional test matrix covers numeric >, >=, <, <=,
== and nonempty all conjunctions; absent/nonfinite/boolean observations are
inconclusive. Operators cover the existing >= template, lower-is-better E13
intent, and explicit equality/boundary controls requested by the recovery scope.
No implicit historical direction is inferred.

Changes: adjudication/acceptance.py (new), adjudication/adjudication.py,
contract/operations.py; tests/recovery/conftest.py and test_adjudication.py.
New attempts are separate adjudications/*.json; original adjudication.json is
untouched. Historical unsupported acceptance forms are inconclusive. Evidence
trust remains a checkpoint 3 dependency, so this gate certifies evaluator logic
only, not complete provenance. Initial full regression: 180 passed / 8.38 s.
Expanded conjunction/history suite is recorded in checkpoint2-green.xml.

Gate: PASSED for scientific evaluator scope, conditional on checkpoint 3 trust
repair before research execution. No historical files operated on.

## Checkpoint 3 — integrity correctness

Reproduction: 12 failing adversarial cases in checkpoint3-red.xml, including
payload+mutable-checksum acceptance, output substitution, ignored inventory,
manifest mutation and registration claiming verification. Explicit expected-run
and expected-bundle API tests initially failed because the APIs did not exist.

Changes: bundle/bundle.py materialised runner/source/config checks and explicit
expected identity; opt-in expcon-bundle-v3 binds complete executable payload
(including notebook metadata) without changing v1/v2 hash meanings. Historical
v1 remains consistency inspection only; v2 notebook metadata lacks a strong
binding and strict admission refuses it instead of retroactively changing hashes.
Evidence packaging now emits expcon-evidence-v2, recursively inventories files,
checks trusted required outputs and anchors manifest bytes to the trusted run.
Verification is read-only and requires expected run/bundle; old unanchored evidence
remains historical evidence, not independently upgraded verification. Artifact
registration means REGISTERED, not provenance-verified. Path containment protects
untrusted manifests; payload/manifest and copy-substitution tests use valid
baselines. The old early-return test is explicitly named a missing-manifest test
and supplemented by complete metrics mutation coverage.

Files: bundle/bundle.py, contract/operations.py, evidence/evidence.py,
adjudication/adjudication.py, artifacts/artifact.py, util/path.py;
tests/recovery/{conftest,test_integrity,test_bundle_versions}.py and the existing
tamper test. Full regression result is in checkpoint3-green.xml.

Gate: PASSED for tested identity/integrity boundaries. Host/operator retains
trust roots; this is not malicious-code sandboxing or proof of model mathematics.
Next: checkpoint 4 persistence, async state, stage ordering and output integration.

## Checkpoint 4 — lifecycle reliability

Gate: PASSED in the bounded local/fake-provider scope. Full suite: 218 passed,
30.23 s (checkpoint4-green.xml). Red suite: 8 failed / 1 passed, including a
concurrent read of a truncated snapshot. No remote workload was submitted.

Changes: lifecycle/{state,experiment_state}.py; util/json_io.py (POSIX advisory
locking, fsync and atomic replace); runner/{backends,observation,environment}.py;
cli/commands.py; evidence/collection.py; artifacts/artifact.py;
adjudication/adjudication.py; workspace/workspace.py; tests/recovery and CLI/backend
tests. Pre-existing subprocess/Kaggle work was retained.

Journal entries are the run commit point, run.json a derived snapshot. Revision
checks reject stale metadata writers. Duplicate transitions are idempotent.
Snapshot-write failure after journal commit is injected and recovered. Advisory
locking covers cooperating local writers; network filesystem durability and
malicious writers are not guaranteed. Legacy events remain historical records.

| Failure boundary | Implemented response | Evidence / limitation |
|---|---|---|
| Before submission marker | No provider call established; run may remain nonterminal | No automatic resubmission |
| After marker, before durable completion/identity | SUBMISSION_OUTCOME_UNKNOWN, explicit reconciliation required | test_uncertain_submission_is_not_automatically_retried |
| Provider identifier returned, persistence unavailable | Cannot promise exactly-once submission; retain attempt and refuse retry | External provider reconciliation still required |
| Duplicate same stable run ID | Serialized submission, existing result returned | Duplicate local submission test |
| New CLI run invocation | New trial identity | Not a retry/deduplication key across separate invocations |
| Provider pending/running | SUBMITTED/PENDING/RUNNING, not failure | Fake CLI remote lifecycle test |
| Temporary unknown observation | Preserve nonterminal state | Controlled observation test |
| Child failure | STAGE_FAILED then FAILED_EXECUTION | Existing and new process tests |
| Snapshot persistence failure | Read committed journal entry | Injected snapshot failure test |
| Failed/partial fetch | Preserve raw attempt bytes and failure report; no verified transition | Collection code; live transport failure needs external validation |
| Repeated verification/adjudication | New reports, protected evidence unchanged | Full CLI fixture repeated-operation test |
| Cancellation without real provider/process handle | False / unsupported, no false cancellation claim | Updated cancellation contract/test |
| Colab generic run | Block before allocation | Provisioning-only capability |
| Colab direct provision failure | Release allocated runtime in finally | Missing-version fake cleanup test |

Run snapshots preserve the execution bundle. Collection retains stage namespaces,
rejects ambiguous/missing required outputs and never merges process JSON into
scientific metrics. New evidence versions and attempt reports preserve prior
records. Raw environment-binding values are not serialized. Preflight and local
children disable bytecode writes. tmux workspace paths are shell-quoted.

Limitations: synchronous local cancellation/resumption unsupported; remote APIs
remain mocked; Tinker training/provenance is driver/provider-attested. Atomic
journal persistence does not make provider submission transactional. Next: 5.

## Checkpoint 5 — input and environment closure

Red: 4 failures in checkpoint5-red.xml, reproducing ignored file/environment
content constraints and absence of directory content identities. First complete
green regression: 222 passed, 23.52 s. Follow-up admission/dependency-lock binding
regression is in checkpoint5-green.xml. Changes: runner/inputs.py (new),
runner/invocation.py, runner/environment.py, contract/operations.py,
bundle/bundle.py and cli/commands.py, with tests/recovery/test_input_closure.py.

File/tree digests and declared nonsecret environment digests are enforced. Tree
identity is mount-independent and detects referenced-file mutation within the
declared tree. Runtime attestations record actual input digests, full installed
distribution versions, interpreter and platform; explicit inventory equality is
available. Declared v3 dependency locks are included in the executable payload.
Known exclusions and four assurance levels are in EXPCON_TRUST_MODEL.md.

Gate: PASSED for tested declared local inputs/CPU environment. No claim of
complete dynamic dependency closure, GPU environment consistency or empirical
replay follows from this gate. Next: checkpoint 6 evidence reconciliation and
local real-model validation after the final regression exits successfully.

## Checkpoint 6 — research validation

Gate: PASSED for the local synthetic ML workflow and historical consistency
reconciliation. No Bayzflow file modified; no remote compute.

Raw study: validation/6203b9768887468284cfd96566dce158/validation.json. Dataset generation, 640/256 disjoint
train/test IDs, 4 features, seed 1729, 8% label flips and the protocol acceptance
and replay tolerances were fixed before execution. This is real gradient-based
logistic regression using Python standard-library arithmetic, selected to avoid
installing an ML stack or touching the external research environment. It is a
small infrastructure study, not novel ML research.

Five positive runs: accuracy 0.90625, log loss
0.3370261379601224; all completed/compliant/verified/SUPPORTED.
One zero-training ablation: accuracy 0.55078125, log loss
0.6931471805599466; completed/verified/NOT_SUPPORTED.
Controlled copy output/model.json modification: verification FAIL and scientific
INCONCLUSIVE; original evidence and verdict records preserved. Four independent
replays matched contract, bundle, environment and declared artifact bytes.
Additional numeric weight/input checks: evidence/local-replay-analysis.json.

| Trial | Run identity | Contract | Bundle | Scientific |
|---|---|---|---|---|
| positive 0 | run-RECOVERY_POSITIVE-5574946b | baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572 | 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa | SUPPORTED |
| positive 1 | run-RECOVERY_POSITIVE-264cc1ce | baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572 | 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa | SUPPORTED |
| positive 2 | run-RECOVERY_POSITIVE-8b8609b3 | baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572 | 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa | SUPPORTED |
| positive 3 | run-RECOVERY_POSITIVE-392fe11b | baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572 | 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa | SUPPORTED |
| positive 4 | run-RECOVERY_POSITIVE-6e250336 | baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572 | 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa | SUPPORTED |
| negative 0 | run-RECOVERY_NEGATIVE-ddcea602 | 606e16094e0a8dadb2ae7c512c3417a1dadd1bb28135ec6862f1b3d561392029 | 7c5b6eb783c67ff775c43f9b56edb26c577e36836f16eb5de7e77a3f6f7d6860 | NOT_SUPPORTED |

Timing uses perf_counter, 5 paired direct/controlled trials, raw commands and
wall times retained. Controlled execution includes admission/preflight and child
execution; packaging and verification are separately timed. Required preceding
validate calls are recorded separately, not hidden inside the execution metric.
No provider latency, model-loading or GPU optimisation claim is made.

- bundle_seconds: median 0.345108 s; range 0.336852–0.356251 s.
- controlled_execution_seconds: median 0.677465 s; range 0.645299–0.686157 s.
- direct_seconds: median 0.183194 s; range 0.170836–0.189431 s.
- packaging_seconds: median 0.322655 s; range 0.302851–0.340137 s.
- paired_execution_control_overhead_seconds: median 0.494271 s; range 0.455868–0.509921 s.
- stage_seconds: median 0.185152 s; range 0.183491–0.189530 s.
- validate_seconds: median 0.241199 s; range 0.224727–0.246806 s.
- verification_seconds: median 0.253385 s; range 0.234417–0.280005 s.

First harness attempt failed before model execution because expcon.cli is not a
python -m package entry point. Raw failed workspace 7c5abb803818457e85f190f46e457425
is preserved. The harness was corrected to invoke the public main() entry point
and a new workspace was used. No frozen experiment was repaired in place.

Changes: docs/recovery/{reconcile_bayzflow,validate_local}.py, validation_source/
and raw evidence directories; optional candidate-evidence adjudication parameter
uses the same expected run checks and records its path. Next: checkpoint 7.

## Checkpoint 7 — final engineering maturity gate

Gate: PASSED for the explicitly bounded local recovery. Remote provider and
large-scale/distributed capability gates are DEFERRED/UNSUPPORTED, not reported
as passing integrations. No remote workload, commit, push or PR was performed.

### Final checks

| Python | Tests | Passed | Failed/errors | Skipped | Wall seconds |
|---|---:|---:|---:|---:|---:|
| 310 | 230 | 230 | 0 | 0 | 33.77 |
| 311 | 230 | 230 | 0 | 0 | 26.77 |
| 312 | 230 | 230 | 0 | 0 | 26.86 |

No warnings were reported by these pytest runs. Tests used separate --basetemp
directories per interpreter; raw XML is final-python310/311/312.xml.
Statement coverage: 73.40%; branch coverage:
55.25%; combined coverage:
68.96%. Baseline statement coverage was approximately
63%. Coverage is not proof of integrity; core full-path adversarial and actual
workflow evidence is more important. Workspace and live-provider coverage remains
limited. Raw final-coverage310.json records all exclusions/missing paths.

Ruff check src/: PASS. Mypy, including check_untyped_defs, 42 files: PASS.
Git diff whitespace check: PASS. Exact output: evidence/final-static-checks.json.
Source hashes: evidence/final-source-manifest.json.

Wheel/sdist build succeeded. A runtime-only wheel install on Python 3.10, 3.11 and
3.12 passed import, version, core doctor and skill/resource checks with pytest
absent. The Python 3.10 conditional tomli dependency is now explicit. Build-time
setuptools and dev-only ruff/mypy/type stubs were added only for required tooling;
no ML runtime dependency was introduced. uv.lock was regenerated by uv (67 locked
packages, including optional dependencies; not all installed). CI now executes
static checks and an isolated runtime-wheel smoke test in its existing matrix.
Actual local packaging commands/results/hash: evidence/packaging-final.json.

Initial lint/type checks failed and were repaired: three unused symbols; typed
state-table handling; optional import boundaries; context conversion preserving
the legacy positional API; resource Traversable joins; dict/variable annotations.
Offline uv lock initially lacked registry cache, then normal resolution succeeded.
Python 3.11 interpreter download succeeded under /tmp; its optional user-bin link
failed on the read-only home directory, so the explicit interpreter path was used.
The original environment was not upgraded. No check was disabled to obtain green.

### Additional critical regressions and preserved failures

checkpoint7-additional-red.xml: state namespace and independent execution-status
defects. checkpoint7-metric-copy-red.xml: divergent scientific metric copy.
checkpoint7-timeout-red.xml: timeout log secret exposure using a fake process.
checkpoint7-freeze-red.xml: retained-lock replacement under missing/advanced state.
checkpoint7-traversal-red.xml and checkpoint7-symlink-compat-red.xml: traversal and
legacy entry-set compatibility. All corrected; final suite includes these cases.
Checkpoint7 preservation targeted gate: 85 passed. The earlier parallel temporary
directory failure remains in attempt-python310-interference.xml (225 passed, one
setup error). It was not discarded or relabelled as a successful run.

### Authoritative latest local study

Raw record: validation/bc6d175b5b31494c9420b05673c51a7f/validation.json. This study followed the final retained-lock
and traversal fixes. The same preregistered generator, 640/256 fixed split,
acceptance criteria and replay tolerances were used; no thresholds were adjusted
after observing outcomes. Controller source and harness hashes are captured in
the study. Earlier successful and failed workspaces remain intact.

- positive trial 0: run-RECOVERY_POSITIVE-db6ad87d; contract baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572; bundle 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa; scientific SUPPORTED.
- positive trial 1: run-RECOVERY_POSITIVE-d301df55; contract baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572; bundle 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa; scientific SUPPORTED.
- positive trial 2: run-RECOVERY_POSITIVE-9810539f; contract baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572; bundle 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa; scientific SUPPORTED.
- positive trial 3: run-RECOVERY_POSITIVE-485251c4; contract baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572; bundle 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa; scientific SUPPORTED.
- positive trial 4: run-RECOVERY_POSITIVE-dfda6bba; contract baee9267272f2d487f43d512838fb49af083a324286205d8353ed7eb56690572; bundle 4330b2862c72a36ee611750b358ee4551567bc5c25edd1f8552f9741bce1d0fa; scientific SUPPORTED.
- negative trial 0: run-RECOVERY_NEGATIVE-579fb511; contract 606e16094e0a8dadb2ae7c512c3417a1dadd1bb28135ec6862f1b3d561392029; bundle 7c5b6eb783c67ff775c43f9b56edb26c577e36836f16eb5de7e77a3f6f7d6860; scientific NOT_SUPPORTED.

All five positive runs and the negative ablation completed with compliant contracts
and verified evidence. Positive: accuracy .90625, log loss .3370261379601224.
Negative: accuracy .55078125, log loss .6931471805599466, NOT_SUPPORTED.
The controlled tampered copy failed verification and adjudicated INCONCLUSIVE.
Independent stdlib verifier recomputed held-out metrics from saved weights and
checked every sealed payload/inventory in all six runs: PASS,
evidence/independent-study-check-release.json. It does not authenticate a hostile
host or independently prove the training implementation.

Four preserved successful workspaces contain 20 positive repeat trials and four
negative ablations; these are infrastructure repeats of one fixed dataset, not
20 independent scientific replicates. All declared positive artifact hashes,
contracts, bundles and environment identities agree across workspaces. See
evidence/cross-workspace-replay.json. The initial harness failure before execution
is retained separately; there are no hidden failed model experiments.

### Performance and simplicity assessment

Five paired trials in the latest study; medians and min/max ranges below.
Required preceding validation calls are separately recorded. This is a shared
local host, not a dedicated statistically controlled performance benchmark.

| Measurement | Median s | Minimum s | Maximum s |
|---|---:|---:|---:|
| bundle_seconds | 0.267542 | 0.252132 | 0.274443 |
| controlled_execution_seconds | 0.654338 | 0.635949 | 0.677688 |
| direct_seconds | 0.181030 | 0.171522 | 0.185624 |
| packaging_seconds | 0.316494 | 0.297623 | 0.334428 |
| paired_execution_control_overhead_seconds | 0.473308 | 0.464427 | 0.492064 |
| process_dispatch_seconds | 0.000738 | 0.000586 | 0.000964 |
| stage_seconds | 0.184774 | 0.179291 | 0.186661 |
| validate_seconds | 0.250039 | 0.235274 | 0.250813 |
| verification_seconds | 0.239640 | 0.236924 | 0.252364 |

Resource observations: {"controller_peak_rss_kib": 26980, "largest_child_peak_rss_kib": 29832, "logical_workspace_file_bytes": 3018423, "scope": "Linux ru_maxrss; aggregate child maximum, not per-stage GPU memory; logical bytes exclude symlinked environment"}
These are logical file bytes and Linux process RSS observations, not GPU memory
or physical deduplicated storage. Direct execution is substantially faster for
this short workload; control overhead is not advertised as throughput improvement.
The process dispatch measurement is Popen wall time only, while controlled
execution includes validation/diff/environment admission and process execution.

No integrity check was removed or cached away. Selected-directory traversal was
pruned after a reproduced operational failure; entry-set/hash compatibility has
a dedicated regression. Raw earlier/later timings are retained, but differences
are not treated as a controlled optimisation result. Repeated hashing, full journal
snapshots and duplicate artifact storage remain proportional costs. Large-data
latency/memory, provider API overhead, log streaming and archival growth require
further validation. There is no new scheduler/database or broad architectural
rewrite; the legacy RunContext API is converted explicitly at the backend boundary.

### Preservation and modified files

All 41 initial historical experiment/evidence files remain byte-identical:
evidence/historical-preservation.json. All 28 initially modified tracked bytecode
files remain identical to their starting working-tree blobs:
evidence/preexisting-cache-preservation.json. The complete starting uncommitted
diff is retained in evidence/initial-worktree.patch. Tracked generated files were
not removed because they include pre-existing work and historical identity inputs;
.gitignore now excludes new generated development files.

Files with tracked diffs (includes preserved pre-existing changes):

- .github/workflows/test.yml
- README.md
- pyproject.toml
- src/expcon.egg-info/PKG-INFO
- src/expcon.egg-info/SOURCES.txt
- src/expcon.egg-info/requires.txt
- src/expcon/adjudication/__pycache__/adjudication.cpython-310.pyc
- src/expcon/adjudication/adjudication.py
- src/expcon/artifacts/artifact.py
- src/expcon/backends/__pycache__/colab.cpython-310.pyc
- src/expcon/backends/__pycache__/kaggle.cpython-310.pyc
- src/expcon/backends/colab.py
- src/expcon/backends/kaggle.py
- src/expcon/backends/tinker.py
- src/expcon/bundle/__pycache__/__init__.cpython-310.pyc
- src/expcon/bundle/__pycache__/bundle.cpython-310.pyc
- src/expcon/bundle/bundle.py
- src/expcon/cli/__pycache__/__init__.cpython-310.pyc
- src/expcon/cli/__pycache__/commands.cpython-310.pyc
- src/expcon/cli/commands.py
- src/expcon/contract/__pycache__/__init__.cpython-310.pyc
- src/expcon/contract/__pycache__/canonical.cpython-310.pyc
- src/expcon/contract/__pycache__/contract.cpython-310.pyc
- src/expcon/contract/__pycache__/operations.cpython-310.pyc
- src/expcon/contract/contract.py
- src/expcon/contract/operations.py
- src/expcon/evidence/__pycache__/evidence.cpython-310.pyc
- src/expcon/evidence/evidence.py
- src/expcon/hashing/manifest.py
- src/expcon/lifecycle/__pycache__/experiment_state.cpython-310.pyc
- src/expcon/lifecycle/__pycache__/state.cpython-310.pyc
- src/expcon/lifecycle/experiment_state.py
- src/expcon/lifecycle/state.py
- src/expcon/runner/__pycache__/backends.cpython-310.pyc
- src/expcon/runner/__pycache__/runner.cpython-310.pyc
- src/expcon/runner/backends.py
- src/expcon/runner/environment.py
- src/expcon/runner/invocation.py
- src/expcon/runner/runner.py
- src/expcon/util/__pycache__/env.cpython-310.pyc
- src/expcon/util/json_io.py
- src/expcon/util/path.py
- src/expcon/workspace/__pycache__/workspace.cpython-310.pyc
- src/expcon/workspace/workspace.py
- tests/backends/__pycache__/test_backends.cpython-310-pytest-9.1.1.pyc
- tests/backends/__pycache__/test_kaggle_transports.cpython-310-pytest-9.1.1.pyc
- tests/backends/test_backends.py
- tests/backends/test_colab.py
- tests/backends/test_kaggle_transports.py
- tests/cli/__pycache__/test_cli.cpython-310-pytest-9.1.1.pyc
- tests/cli/test_cli.py
- tests/lifecycle/__pycache__/test_lifecycle_integration.cpython-310-pytest-9.1.1.pyc
- tests/tamper/__pycache__/test_tamper_detection.cpython-310-pytest-9.1.1.pyc
- tests/tamper/test_tamper_detection.py
- tests/unit/__pycache__/test_bundle.cpython-310-pytest-9.1.1.pyc
- tests/unit/__pycache__/test_contract.cpython-310-pytest-9.1.1.pyc
- tests/unit/__pycache__/test_freeze_diff.cpython-310-pytest-9.1.1.pyc
- tests/unit/__pycache__/test_hashing.cpython-310-pytest-9.1.1.pyc
- tests/unit/__pycache__/test_lifecycle.cpython-310-pytest-9.1.1.pyc
- tests/unit/test_invocation.py
- tests/unit/test_lifecycle.py
- uv.lock

New implementation modules: adjudication/acceptance.py, runner/inputs.py,
runner/observation.py, evidence/collection.py. New tests live in tests/recovery/.
New reports/helpers/raw evidence live under docs/recovery/. The next step is
review of this working tree; no commit or external publication was authorised.
