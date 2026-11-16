# EXPCON GitHub release readiness

**Verdict: READY WITH LIMITATIONS for review and an authorised GitHub push.**
Local release gates pass. GitHub-hosted workflows have not run. No commit, push,
release, remote experiment or repository-setting change has occurred.

## Preserved starting state and implementation plan

Started on `main` at `a6a36d870ecac990a310e3be6339f6d17f418d4c`, with no staged changes.
The cached `origin/main` is six commits behind; no fetch was used to infer current remote state.
Remote: `https://github.com/Gramathon/expcon.git`. No local tags or release automation existed.
Recovery source, tests, documentation and scientific records were already uncommitted.
`release/initial-inventory.json` classifies every starting changed/untracked path;
the original pre-recovery patch remains in `evidence/initial-worktree.patch`.

| File/directory | Initial state | Classification | Action | Risk |
|---|---|---|---|---|
| `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `README.md` | Recovery modifications/new modules | Implementation and authored content | Preserve, review, stage | Behavioral compatibility reviewed in recovery documents |
| `docs/recovery/validation/`, original reports and `evidence/` | Untracked recovery work | Historical scientific/engineering evidence | Preserve and include, except local environment links and empty advisory locks | Must not rewrite verdicts, locks, bundles or measurements |
| 45 tracked `src/`/`tests/` bytecode files | Tracked, some pre-modified | Development caches | Remove from index only, retain local bytes | Exact list: `release/untrack.json` |
| Six tracked `src/expcon.egg-info/*` files | Tracked build metadata | Reproducible build output | Remove from index only, retain local bytes | Rebuilt from declared metadata |
| `.venv`, caches, build/dist, root test reports | Ignored development output | Environment/cache/build | Keep local, exclude | Narrow patterns preserve scientific records |
| `SHA256SUMS`, root `.expcon/`, `examples/` | Existing tracked content | Historical checksums/experiments/examples | Preserve | Old checksums must not describe current builds |
| `.github/workflows/test.yml` | Uncommitted recovery edits | CI configuration | Consolidate into three workflows | No remote execution implied |

Order: inventory and baseline → regression reproduction → minimal fixes and portable
study harness → CI/package checks → reviewed index-only cleanup → intended-index
snapshot validation → final review. Frozen identities and historical verdicts are
unchanged. Changes to the harness apply only to newly authored studies.

## Baseline and demonstrated corrections

Fresh baseline: 230 passed, zero failures/errors/skips on Python 3.10.12, 3.11.16
and 3.12.13 (34.517, 34.787, 34.034 seconds). Statement coverage 73.3956%; branch
coverage 55.2515%. XML and JSON reports are under `release/`.

`tests/recovery/test_release_regressions.py` established failures before fixes:
oversized JSON integers crashed numeric adjudication; Python zero-padded release
segments compared incorrectly; malformed evidence and bundle manifests crashed
result formatting. Red reports are retained. Oversized measurements now return
INCONCLUSIVE; invalid manifests return verification failure. Python comparisons
pad release segments. No historical identity algorithm or verdict was changed.
The initial red attempt also contained two incorrect expected error names, corrected
against the implementation before the second red report; both attempts are retained.

Additional tests cover v3 executable mutation with an expected root, mutable-checksum
tampering, added/missing payload, full run identity fields, missing run seal,
input-tree additions/removals/mutations/symlinks, and eleven environment rejection
paths after a passing baseline probe. Existing integrity tests gained baseline
assertions and specific rejection reasons. A first strengthened assertion expected
the generic content error for `hashes.json`; corrected to the actual, more specific
`HASHES_MANIFEST_MISMATCH`, with the failed report retained.

Five additional CLI tests confirm refusal before backend construction or new run
creation for missing freeze lock, source drift, disallowed backend, corrupt bundle
and absent environment specification. No provider is contacted.

Packaging minimum correction: the advertised `setuptools>=68` accepted a backend
that rejects the existing SPDX string `license = "MIT"`. A constrained build with
68.0.0 failed on that field (`release/minimum-build.log`); the lower bound is now
77, matching [setuptools' documented PEP 639 support](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html).
A constrained 77.0.1 build passed (`release/minimum-build-fixed.log`). Runtime
dependencies are unchanged; Python 3.10 `tomli` is declared and tested in clean wheels.

`.gitattributes` disables whitespace diagnostics only for raw recovery XML/log
reports and the original preservation patch. The original staged diff reported
191 lines of diagnostics in those immutable traceback reports; their bytes were
preserved, and source whitespace checks remain active. Both diagnostic outputs
are retained under `release/`.

## Quality policy

`tools/check_quality.py` runs lint on all source modules and release tooling and
mypy on all 42 source modules with `check_untyped_defs = true`. This is not strict
mypy. Ruff rules `E4/E7/E9/F` and Python 3.10 target are explicit in `pyproject.toml`;
they no longer inherit unrelated workstation configuration. The inherited policy
reported 102 existing findings; those additional rules are not claimed as passing.
Format verification covers the four new trust modules, new release regression file
and `tools/` (seven files); 43 files failed the initial broader format inspection.
Legacy formatting is a documented backlog, not a silently optional CI check.

## GitHub Actions

`ci.yml`: PRs to main, pushes to main and manual dispatch. Matrix 3.10/3.11/3.12;
locked dependency sync, dependency consistency, quality policy, full pytest suite
including critical adversarial/scientific/fake-backend tests; JUnit and statement/
branch coverage artifacts retained seven days. No required check uses continue-on-error.

`research-integrity.yml`: same triggers/matrix. Five positive logistic-regression
runs, a zero-training negative control, corrupted disposable evidence and replay
comparison under the frozen existing protocol; independent byte/metric recomputation.
Evidence artifacts retained three days using explicit paths, excluding environment
links and credentials. No real backend account is used.

`release-validation.yml`: PRs/pushes to main, manual and `v*`/`rc-*` tag pushes. Build sdist, build wheel
from sdist, verify metadata/entry point/resources/cache exclusions, runtime-only
installation away from checkout, import/CLI help/version/doctor/skill checks.
No automatic package publication or GitHub release creation.

All workflows use `contents: read`, immutable action commits verified through the
official repositories, checkout with persisted credentials disabled, explicit uv
version, bounded timeouts, no cache credentials, no secrets or pull_request_target.
Pins/provenance: `release/action-refs.json`; actionlint provenance and output retained.
GitHub-hosted execution has NOT occurred. Hosted images/network availability and
artifact-upload behavior remain external validation requirements.

Required protection checks after the first authorised push: `Python 3.10 validation`,
`Python 3.11 validation`, `Python 3.12 validation`, and `CPU research integrity 3.10`,
`CPU research integrity 3.11`, `CPU research integrity 3.12`, and `Package Python 3.10`,
`Package Python 3.11`, `Package Python 3.12`. Require PR review, disallow bypass of required checks and
force pushes. Configure these manually in GitHub Settings → Rules → Rulesets after
observing actual check names. No repository settings have been changed.

## Final test evidence

| Check | Python 3.10.12 | Python 3.11.16 | Python 3.12.13 |
|---|---|---|---|
| Unit tests (101) | PASS | PASS | PASS |
| Recovery/tamper tests (103 + 8) | PASS | PASS | PASS |
| CLI/lifecycle integration (16 + 9) | PASS | PASS | PASS |
| Mocked backends (31) | PASS | PASS | PASS |
| Full suite | 268 PASS | 268 PASS | 268 PASS |
| Failures/errors/skips/reported warnings | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| Pytest wall seconds | 50.283 | 49.713 | 49.854 |
| Statement coverage | 75.0538% | 75.0538% | 75.0538% |
| Branch coverage | 58.0502% | 58.0502% | 58.0502% |
| Ruff lint / scoped format | PASS | PASS | PASS |
| Full-source mypy | PASS | PASS | PASS |
| Locked installation / dependency consistency | PASS | PASS | PASS |
| CPU research integrity and independent check | PASS | PASS | PASS |
| Sdist-to-wheel / runtime-only installation | PASS | PASS | PASS |
| CLI help/version/doctor/skill/resources | PASS | PASS | PASS |

Test subsets are collected by the full suite, not additional independent repetitions.
Groups, XML and coverage JSON: `release/test-groups.json`, `release/candidate*.xml`,
`release/candidate*-coverage.json`; exact environment versions in installation logs
and study records. JUnit reports are preserved; CI also emits XML coverage.
Development environments use the committed uv lock, pytest 9.1.1, pytest-cov 7.1.0,
Ruff 0.17.4 and mypy 2.4.1. Coverage increased from 73.40/55.25 to 75.05/58.05
percent (statements/branches), with 38 new parametrized regression cases.

| Trust-critical module | Statements | Branches |
|---|---|---|
| `adjudication/acceptance.py` | 83.72% | 79.17% |
| `bundle/bundle.py` | 76.48% | 57.45% |
| `evidence/evidence.py` | 92.53% | 84.62% |
| `runner/inputs.py` | 90.48% | 75.00% |
| `runner/environment.py` | 93.16% | 85.19% |
| `lifecycle/experiment_state.py` | 81.76% | 47.37% |
| `cli/commands.py` | 60.84% | 30.95% |

CLI provider/admin paths and lifecycle branches remain substantial coverage gaps.
The five new admission cases cover failures before provider construction; they do
not certify all CLI commands. Concurrency tests cover cooperating POSIX writers,
not network filesystems or a distributed scheduler. Legacy backend smoke tests
such as `tests/backends/test_backends.py::TestLocalBackend::test_local_backend_submit`
permit a failed status and establish interface shape only; actual successful
execution is demonstrated by the separate complete CLI/CPU studies. No legacy
test was removed to achieve these results. No operating-system network sandbox
was used; provider tests use fakes and no paid backend workloads were submitted.

## CPU research validation

The final portable harness runs outside the checkout in newly created workspaces,
using the active virtual environment and its Python-specific lock constraint.
It preserves the existing scientific protocol: 896 generated examples, 640 train /
256 held out, seed 1729, 120 gradient-descent epochs for the positive model and
zero epochs for the explicit negative control. Acceptance remains accuracy >= 0.8
AND log loss <= 0.55. There are no hardcoded evaluation measurements.

Each interpreter completed five independently identified positive runs and one
negative control. Positive accuracy was 0.90625 and log loss approximately
0.3370261379601224; negative accuracy 0.55078125 and loss approximately
0.6931471805599466. Both classes completed and verified, with SUPPORTED versus
NOT_SUPPORTED scientific verdicts. A disposable corrupted model output failed
verification and adjudicated INCONCLUSIVE; the original evidence remained intact.

Four replay comparisons per interpreter matched contract, bundle and environment
identities, with accuracy/loss deltas within 1e-12 and model weight/bias maximum
absolute delta 0. The harness now explicitly enforces the already-declared
`weight_absolute` tolerance; formerly it recorded artifact equality without
enforcing that separate tolerance. This is a validation-tool correction, not a
change to the frozen protocol or old verdicts. All compared output artifact hashes
were equal within each interpreter. Cross-interpreter floating-point loss differs
at about 1e-15; this is not a general bitwise reproducibility claim.

`release/replay-study*-records.json` retains actual run/contract/bundle identities,
artifact hashes, environment versions, verdicts, failures, comparisons and repeated
wall-time measurements. `release/replay-independent*.json` records six independent
saved-model metric and byte-consistency checks per interpreter without importing
EXPCON. Fresh raw datasets, model weights, bundles, run journals and tamper copies
remain under `/tmp/expcon-release/replay-study*/` and are not newly committed.
The corresponding CI paths are uploaded as three-day artifacts. Historical recovery
study files already present before this assignment are retained in Git.

The protocol times direct execution, controlled execution, validation, bundling,
dispatch, packaging and verification. These shared-host measurements were collected
with concurrent interpreter validation and are diagnostics, not controlled
performance benchmarks or evidence of GPU optimisation.

## Clean-checkout verification

Method: stage the inspected candidate without committing, export with
`git checkout-index` into `/tmp/expcon-release/candidate`, create three fresh
virtual environments from `uv sync --locked --group dev`, and run all checks away
from the original worktree. The snapshot contains neither the original developer
environment nor tracked caches/egg-info. Tests used bytecode suppression,
`-p no:cacheprovider`, distinct temporary roots, external JUnit/coverage paths.

The source suite, quality policy, real study, independent checker, sdist-to-wheel
build and isolated wheel installation passed. Wheel imports were checked with
`python -I` from `/tmp`, with pytest absent and the module under the new environment;
resources, CLI help/version/doctor/skill were checked. `tomli` is correctly installed
on Python 3.10. `tools/check_distribution.py` verifies archive metadata, SPDX licence,
CLI entry point, four required resources and absence of bytecode. Build timestamps
and ranged build/runtime dependency resolution are not bitwise reproducible build
guarantees. The final replay-tool correction was additionally executed on all three
interpreters; runtime source and all 268 tests remained unchanged.

Functional candidate SHA-256:
`e6f931eecfb3726900b68ee9f64b3f8be378a857b5f84307bb929f319063fbbe`.
Definition: SHA-256 of sorted compact JSON mapping repository-relative paths to
file SHA-256; exact mapping in `release/candidate-functional-manifest.json`.
Includes all source/tests/tools/workflows, package/ignore configuration, README,
licence, AGENTS instructions, recovery Python tools and validation-source protocol/
model/generator. Final engineering reports are outside that functional identity
to avoid self-referential hashes. A final full-index export checks all archived
bytes against the index and the functional manifest; newly added records do not
change the validated executable content. Raw snapshot reports retain their original
intermediate identities/counts (258 and 263); final candidate reports contain 268.

The exact sdist → wheel → runtime-only install sequence was also repeated with
each of Python 3.10, 3.11 and 3.12 selected explicitly as build interpreter in the
final exported snapshot. All passed; `release/python*-build.log`,
`release/python*-distribution.json` and `release/python*-package.json` preserve
the per-interpreter build/install records.

## Repository hygiene and final review

The five original recovery documents, their red/green reports, preservation patch,
all historical contracts/locks/bundles/results/journals/verdicts, root examples and
Bayzflow reconciliation remain unchanged. Of 2,640 inventoried existing files,
only the two explicitly revised authored tools `validate_local.py` and
`check_packaging.py` changed. No external Bayzflow repository was modified.

Exactly 45 development bytecode files and six egg-info files were removed from
tracking, retaining local files. The 45 bytecode files remain byte-identical;
PKG-INFO was subsequently regenerated by the authorised package build. Five local
`.venv` symlinks and empty advisory locks are excluded; run journal/evidence files
are preserved. `.gitignore` narrowly excludes root coverage/JUnit/build output;
scientific JSON/CSV/log files are not generally ignored. `.gitattributes` preserves
raw report trace whitespace rather than editing historical records.

The old workflow was consolidated into three new workflows. Source changes combine
the already-uncommitted recovery and five additional demonstrated edge/packaging
corrections; they must be reviewed together with the recovery audit reconciliation.
The initial inventory separates the starting changes from release work.
`release/final-preservation.json` records preservation and a heuristic credential
scan of indexed content. No private-key blocks or tested token/credential URL
patterns were found; this is not an exhaustive credential or security audit.
No unrelated tracked deletion, frozen-identity rewrite or scientific-result edit
was made. Intentional changes are staged; ignored local development outputs remain.

## Release checklist and commit/push plan

Before committing: review all staged source/CI/documentation changes, especially
the pre-existing recovery, the historical archive and six commits already ahead
of cached origin/main. Local checks pass; GitHub-hosted CI, hosted package indices
and artifact uploads remain to be observed after an authorised push/PR or dispatch.
Require the nine checks named above once they exist; configure protection manually.
No live Kaggle/Tinker, Colab execution, GPU optimisation, distributed training,
hostile-provider attestation or production-readiness claim is supported.

Logical review groups: (1) recovered integrity/lifecycle implementation and its
regressions/evidence; (2) release edge fixes, portable validation and packaging;
(3) CI, preservation hygiene and readiness documentation. The current index is a
single validated candidate, so one atomic commit is the simplest safe commit plan.
If separate commits are preferred, review selective staging and validate each
resulting intermediate tree; no automatic split or commits were performed.

Current branch: main. Configured remote: origin. Proposed review branch:
`release/engineering-hardening`. Remote divergence has not been refreshed;
cached origin/main..HEAD contains six existing local commits. After explicit
commit/push approval, review the refreshed history before continuing:

```bash
git fetch origin
git log --oneline --left-right origin/main...HEAD
git diff --cached --check
git diff --cached --stat
git switch -c release/engineering-hardening
git commit -m "fix: harden experimental integrity and release validation"
git push --set-upstream origin release/engineering-hardening
```

These commands are a proposal, not actions performed. Stop if the refreshed
history or branch name is unexpected; never force-push. PR creation, publication,
release tagging and remote settings require their own authorisation. A feature
branch push alone does not trigger the main-only push workflows; use an authorised
PR or manual dispatch to observe hosted validation.

## Portfolio suitability

The repository now provides inspectable evidence of Python research infrastructure,
frozen-criteria adjudication, expected-root byte verification, failure preservation,
automated regression testing, package installation and CI design. The CPU study
demonstrates an empirical local workflow and bounded replay consistency. Present
these precise capabilities with their trust assumptions and remaining coverage gaps.
This does not establish distributed ML, accelerator runtime engineering, frontier
model training or production deployment experience. Hosted CI remains unproven
until the first authorised execution.
