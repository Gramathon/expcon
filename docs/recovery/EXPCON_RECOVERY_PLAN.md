# EXPCON engineering recovery plan

## Baseline and architecture (before implementation)

Revision: a6a36d870ecac990a310e3be6339f6d17f418d4c; branch main.
The working tree already contains Kaggle notebook/version custody changes,
subprocess instrumentation, stage failure transitions and their tests, plus
tracked/untracked bytecode. These are preserved. Initial diff is retained at
/tmp/expcon-recovery-initial.patch; protected examples and historical .expcon
file digests are captured at /tmp/expcon-recovery-protected.json.

Python 3.10.12; pytest 9.1.1; pytest-cov 7.1.0. Runtime dependencies:
click>=8.1, jsonschema>=4, PyYAML>=6, tabulate>=0.9. Optional Tinker>=0.24
requires Python>=3.11. CI configures Python 3.10/3.11/3.12, pytest coverage and
setuptools build. Local reference execution; Kaggle notebook transport;
Colab provisioning only; Tinker frozen local driver with external service.
No live provider execution is authorised.

Baseline command: UV_CACHE_DIR=/tmp/expcon-recovery-uv
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/tmp/expcon-recovery-baseline.coverage
uv run --no-sync --offline python -B -m pytest -p no:cacheprovider
--cov=src/expcon --cov-report=term
--cov-report=json:/tmp/expcon-recovery-baseline-coverage.json
--junitxml=/tmp/expcon-recovery-baseline.xml

Result: 162 passed, 0 failed, 0 skipped, 0 reported warnings, 6.99 seconds;
aggregate statement coverage 63%. Raw XML and coverage JSON accompany this
plan. An initial uv attempt failed before tests because its default cache was
read-only; the temporary-cache retry succeeded. Passing tests are not proof
of the trust invariants.

Architecture: YAML -> schema/semantic validation -> frozen lock -> versioned
bundle identity/source closure -> admission -> backend -> outputs -> evidence
packaging -> verification -> scientific evaluator. JSON run records and event
ledger hold operational state independently of tmux. Current CLI owns too much
workflow logic; repair boundaries before considering structural changes.

## Ranked defect register and dependency order

| ID | Severity | Initial classification | Defect / source | Correction and regression strategy |
|---|---|---|---|---|
| A1 | Critical | STATICALLY CONFIRMED | adjudication._evaluate_metrics trusts output thresholds/verdict | Read immutable contract rules; exercise full adjudication with adversarial observations |
| A2 | Critical | STATICALLY CONFIRMED | _evaluate_aggregate substring accepts NOT_SUPPORTED | Remove verdict authority; exact typed rule results; full-path regression |
| A3 | Critical | STATICALLY CONFIRMED | support not gated on execution/compliance; missing lock returns compliant | Require all upstream conditions; missing trust returns unknown/inconclusive |
| I1 | Critical | STATICALLY CONFIRMED | bundle files checksums not bound back to identity content | Reconstruct materialised protected identities; compare independent expected lock/run identity |
| I2 | Critical | STATICALLY CONFIRMED | evidence verifier mutates manifest and ignores full hashes/run trust | Read-only verification; versioned evidence sealed against trusted run anchor |
| I3 | Critical | STATICALLY CONFIRMED | required copies/environment/provenance incompletely checked | Trusted required outputs; recursive inventory; artifact linkage; targeted mutations |
| L1 | High | STATICALLY CONFIRMED | CLI treats remote non-completion as failure | Explicit provider normalization; fake async workflow tests |
| L2 | High | STATICALLY CONFIRMED | stage dependencies ignored, non-atomic state/history | Stable topological execution; atomic durable records, locking and recovery tests |
| L3 | High | STATICALLY CONFIRMED | shallow flattened packaging, cancellation/cleanup claims | Preserve stage names/trees; honest cancellation; failure-state matrix |
| R1 | High | STATICALLY CONFIRMED | runtime input bytes not bound; direct dependency checks only | Declared file/tree identities and recorded environment scope |
| S1 | High | STATICALLY CONFIRMED | untrusted manifest/stage paths | Containment checks plus malformed and symlink tests |
| S2 | High | STATICALLY CONFIRMED | raw environment bindings persisted; tmux shell interpolation | Redacted context; shell quoting; sentinel-secret tests |
| T1 | High | STATICALLY CONFIRMED | metrics tamper test exits on missing manifest | Valid baseline fixture then one mutation and exact error assertion |
| P1 | Medium | STATICALLY CONFIRMED | Python 3.10 tomli runtime dependency missing | Conditional dependency; isolated installed-wheel validation |
| E1 | High | INCONCLUSIVE | Bayzflow/replay/overhead claims absent here | Read external original records without mutating them; separate historical from independent checks |

Reproduction tests precede fixes. Classifications and red/green outcomes are
updated in EXPCON_AUDIT_RECONCILIATION.md. No failing test will be removed or
weakened merely to make a gate pass.

## Checkpoints

1. Baseline, preservation inventory, plan and trust specification. Exit: baseline
   recorded and trust assumptions explicit. No implementation before this plan.
2. Scientific correctness. Depends on 1. Exit: authoritative acceptance, exact
   verdicts, upstream gating and full-path adversarial regressions pass. Until
   integrity repair, passing tests isolate evaluator logic and do not certify trust.
3. Integrity. Depends on 2. Exit: actual bytes match trusted identity; evidence is
   read-only and anchored to expected run; substitution/path attacks rejected;
   historical formats remain interpretable without silently upgrading assurance.
4. Lifecycle. Depends on 3. Exit: async states, stage order, persistence/recovery,
   repeated operations, packaging and provider limits tested.
5. Input/environment closure. Depends on 4. Exit: declared content changes rejected;
   environment scope and determinism levels explicit.
6. Research validation. Depends on critical gates. Reconcile Bayzflow read-only;
   run an explicitly specified small local real ML workload; positive, negative,
   tamper and replay outcomes; repeated timing with raw records.
7. Maturity. Depends on 6. Coverage, packaging, available interpreter matrix,
   lint/type checks, bounded performance assessment and readiness classifications.

At each checkpoint record changed files, commands/results, failures, limitations,
regression status and gate outcome in EXPCON_VALIDATION_REPORT.md. A failed
critical gate blocks dependent work. Remote integration remains external validation.

## Historical compatibility risks

Do not change v1/v2 hash algorithms or original locks. Recomputed strict checks
may reject historically accepted bundles. Expose that as verification evidence,
not identity migration. Historical output-provided verdicts are retained as
historical assertions and never silently recomputed in place. New evidence and
adjudication reports use versioned, append-only records. Existing .expcon and
examples must retain captured bytes. New acceptance forms require draft contracts;
unsupported historical acceptance is inconclusive, not inferred. State additions
must preserve existing enum values and parse historical records. Preserve the
pre-existing user changes and generated files; do not remove them during recovery.

## Final checkpoint outcome

All seven local checkpoint gates passed in their explicitly documented scope.
Final suite: 230 passed on each of Python 3.10/3.11/3.12. The final validation
report contains actual run identities, separate negative/tamper/replay outcomes,
performance observations, independent checks and retained failed attempts.
External provider integration remains NEEDS EXTERNAL VALIDATION, and general
distributed training is unsupported. No historical identity/result was rewritten.
